//! 翻譯任務的暫停 / 繼續 / 停止控制（對應 Python `TranslationThread` 的 pause/resume/stop）。
//!
//! 與 Python 的差異：Python 的 stop 只停止回報進度，背景翻譯仍會跑完並寫出檔案；
//! 這裡的停止會中止進行中的請求，且不寫出輸出檔。

use std::future::Future;
use std::sync::Arc;

use tokio::sync::watch;

use crate::error::{Error, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    Running,
    Paused,
    Stopped,
}

/// 可跨執行緒共用的任務控制；clone 後指向同一個任務。
#[derive(Debug, Clone)]
pub struct TaskControl {
    state: Arc<watch::Sender<State>>,
}

impl Default for TaskControl {
    fn default() -> Self {
        Self::new()
    }
}

impl TaskControl {
    pub fn new() -> Self {
        Self { state: Arc::new(watch::Sender::new(State::Running)) }
    }

    /// 暫停：進行中的批次會完成，之後不再送出新請求。
    pub fn pause(&self) {
        self.transition(State::Running, State::Paused);
    }

    pub fn resume(&self) {
        self.transition(State::Paused, State::Running);
    }

    fn transition(&self, from: State, to: State) {
        self.state.send_if_modified(|s| {
            let hit = *s == from;
            if hit {
                *s = to;
            }
            hit
        });
    }

    /// 停止：中止進行中的請求，任務回傳 [`Error::Cancelled`]。無法復原。
    pub fn stop(&self) {
        self.state.send_replace(State::Stopped);
    }

    pub fn is_paused(&self) -> bool {
        *self.state.borrow() == State::Paused
    }

    pub fn is_stopped(&self) -> bool {
        *self.state.borrow() == State::Stopped
    }

    /// 暫停中則等待繼續；已停止則回傳 `Err(Cancelled)`。
    pub async fn checkpoint(&self) -> Result<()> {
        let mut rx = self.state.subscribe();
        let state = *rx.wait_for(|s| *s != State::Paused).await.expect("sender 由 self 持有");
        if state == State::Stopped {
            return Err(Error::Cancelled);
        }
        Ok(())
    }

    async fn stopped(&self) {
        let mut rx = self.state.subscribe();
        let _ = rx.wait_for(|s| *s == State::Stopped).await;
    }

    /// 執行 `fut`，期間若被停止則捨棄它（中止進行中的請求）並回傳 `Err(Cancelled)`。
    pub async fn run<T>(&self, fut: impl Future<Output = T>) -> Result<T> {
        tokio::select! {
            biased;
            _ = self.stopped() => Err(Error::Cancelled),
            out = fut => Ok(out),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn pause_resume_stop_transitions() {
        let c = TaskControl::new();
        assert!(c.checkpoint().await.is_ok());
        c.resume();
        assert!(!c.is_paused());
        c.pause();
        assert!(c.is_paused());
        let waiter = tokio::spawn({
            let c = c.clone();
            async move { c.checkpoint().await }
        });
        tokio::task::yield_now().await;
        assert!(!waiter.is_finished());
        c.resume();
        assert!(waiter.await.unwrap().is_ok());

        c.pause();
        let waiter = tokio::spawn({
            let c = c.clone();
            async move { c.checkpoint().await }
        });
        c.stop();
        assert!(matches!(waiter.await.unwrap(), Err(Error::Cancelled)));
        // 停止後不可再暫停或繼續
        c.pause();
        c.resume();
        assert!(c.is_stopped());
    }

    #[tokio::test]
    async fn run_aborts_pending_future_on_stop() {
        let c = TaskControl::new();
        assert_eq!(c.run(async { 7 }).await.unwrap(), 7);
        let c2 = c.clone();
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            c2.stop();
        });
        let r = c.run(std::future::pending::<()>()).await;
        assert!(matches!(r, Err(Error::Cancelled)));
    }
}
