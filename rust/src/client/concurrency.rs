//! 自適應並行控制（對等 Python `AdaptiveConcurrencyController`）。
//!
//! - 回應快（EMA < 0.5s）→ 並行 +1；回應慢（EMA > 1.5s）→ 並行 -1
//! - 429 速率限制 → 並行直接減半

use std::sync::Mutex;

#[derive(Debug)]
struct State {
    current: usize,
    avg_response_time: f64,
    sample_count: u64,
}

#[derive(Debug)]
pub struct AdaptiveConcurrencyController {
    min: usize,
    max: usize,
    state: Mutex<State>,
}

impl Default for AdaptiveConcurrencyController {
    fn default() -> Self {
        Self::new(3, 2, 10)
    }
}

impl AdaptiveConcurrencyController {
    pub fn new(initial: usize, min: usize, max: usize) -> Self {
        Self { min, max, state: Mutex::new(State { current: initial, avg_response_time: 0.8, sample_count: 0 }) }
    }

    /// 以 EMA（10% 新樣本）更新平均回應時間並調整並行數。
    pub fn update(&self, response_time: f64) -> usize {
        let mut s = self.state.lock().unwrap();
        s.avg_response_time = 0.9 * s.avg_response_time + 0.1 * response_time;
        s.sample_count += 1;
        if s.avg_response_time < 0.5 && s.current < self.max {
            s.current = (s.current + 1).min(self.max);
        } else if s.avg_response_time > 1.5 && s.current > self.min {
            s.current = (s.current - 1).max(self.min);
        }
        s.current
    }

    /// 遇到速率限制時並行數減半（不低於下限）。
    pub fn penalize(&self) -> usize {
        let mut s = self.state.lock().unwrap();
        s.current = (s.current / 2).max(self.min);
        s.current
    }

    pub fn current(&self) -> usize {
        self.state.lock().unwrap().current
    }

    pub fn avg_response_time(&self) -> f64 {
        self.state.lock().unwrap().avg_response_time
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adapts_to_latency() {
        let c = AdaptiveConcurrencyController::default();
        for _ in 0..30 {
            c.update(0.1);
        }
        assert_eq!(c.current(), 10);
        assert_eq!(c.penalize(), 5);
        for _ in 0..60 {
            c.update(5.0);
        }
        assert_eq!(c.current(), 2);
    }
}
