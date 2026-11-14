//! OpenAI RPM/TPM 速率限制與 token 估算（對等 Python `_check_rate_limit` / `_estimate_token_count`）。
//!
//! 與 Python 的差異：Python 以 tiktoken 精算 token，Rust 使用 Python 內建的備用估算法
//! （CJK 約 1.5 字元/token、其餘約 4 字元/token）。只影響速率限制的等待判斷，不影響翻譯內容。

use std::sync::Mutex;
use std::time::{Duration, Instant};

use crate::prompt::Message;

fn is_mostly_cjk(text: &str) -> bool {
    let total = text.chars().count();
    if total == 0 {
        return false;
    }
    let cjk = text.chars().filter(|c| ('\u{4e00}'..='\u{9fff}').contains(c)).count();
    cjk as f64 / total as f64 > 0.5
}

/// 粗估請求 token 數。
pub fn estimate_tokens(messages: &[Message]) -> u64 {
    let base = messages.len() as u64 * 4 + 2;
    let content: u64 = messages
        .iter()
        .map(|m| {
            let len = m.content.chars().count() as f64;
            (if is_mostly_cjk(&m.content) { len / 1.5 } else { len / 4.0 }) as u64
        })
        .sum();
    base + content
}

#[derive(Debug, Default)]
struct Window {
    requests: Vec<Instant>,
    tokens: Vec<(Instant, u64)>,
}

#[derive(Debug)]
pub struct RateLimiter {
    pub max_requests_per_minute: u64,
    pub max_tokens_per_minute: u64,
    window: Mutex<Window>,
}

impl RateLimiter {
    pub fn new(max_requests_per_minute: u64, max_tokens_per_minute: u64) -> Self {
        Self { max_requests_per_minute, max_tokens_per_minute, window: Mutex::new(Window::default()) }
    }

    /// 計算接近上限（≥90%）時應等待的時間；使用率 >95% 時退避 3 倍、>90% 時 1.5 倍。
    pub fn required_wait(&self) -> Duration {
        let now = Instant::now();
        let mut w = self.window.lock().unwrap();
        let minute = Duration::from_secs(60);
        w.requests.retain(|t| now.duration_since(*t) < minute);
        w.tokens.retain(|(t, _)| now.duration_since(*t) < minute);

        let rpm = w.requests.len() as u64;
        let tpm: u64 = w.tokens.iter().map(|(_, n)| n).sum();
        let mut wait: i64 = 0;
        let mut need_delay = false;
        let remaining = |t: Instant| (60.0 - now.duration_since(t).as_secs_f64() + 0.5) as i64;
        if rpm as f64 >= self.max_requests_per_minute as f64 * 0.90 {
            need_delay = true;
            if let Some(first) = w.requests.first() {
                wait = wait.max(remaining(*first));
            }
        }
        if tpm as f64 >= self.max_tokens_per_minute as f64 * 0.90 {
            need_delay = true;
            if let Some((first, _)) = w.tokens.first() {
                wait = wait.max(remaining(*first));
            }
        }
        if !need_delay {
            return Duration::ZERO;
        }
        let usage =
            (rpm as f64 / self.max_requests_per_minute as f64).max(tpm as f64 / self.max_tokens_per_minute as f64);
        let factor = if usage > 0.95 {
            3.0
        } else if usage > 0.90 {
            1.5
        } else {
            1.0
        };
        Duration::from_secs((wait as f64 * factor).max(0.0) as u64)
    }

    pub fn record_request(&self, at: Instant) {
        self.window.lock().unwrap().requests.push(at);
    }

    pub fn record_tokens(&self, at: Instant, tokens: u64) {
        self.window.lock().unwrap().tokens.push((at, tokens));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn estimate_matches_python_heuristic() {
        let msgs = vec![Message::system("abcdefgh"), Message::user("你好世界啊")];
        // 2*4+2 + 8/4 + int(5/1.5)
        assert_eq!(estimate_tokens(&msgs), 10 + 2 + 3);
    }

    #[test]
    fn waits_near_limit() {
        let rl = RateLimiter::new(10, 1_000_000);
        assert_eq!(rl.required_wait(), Duration::ZERO);
        for _ in 0..10 {
            rl.record_request(Instant::now());
        }
        assert!(rl.required_wait() >= Duration::from_secs(60));
    }
}
