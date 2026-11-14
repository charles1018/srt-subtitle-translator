//! API 錯誤與分類（對等 Python `ApiErrorType` / `_classify_error` / `_get_rate_limit_wait_time`）。

use std::fmt;
use std::sync::LazyLock;

use fancy_regex::Regex;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApiErrorKind {
    RateLimit,
    Timeout,
    Connection,
    Server,
    Authentication,
    ContentFilter,
    Unknown,
}

impl ApiErrorKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::RateLimit => "rate_limit",
            Self::Timeout => "timeout",
            Self::Connection => "connection",
            Self::Server => "server",
            Self::Authentication => "authentication",
            Self::ContentFilter => "content_filter",
            Self::Unknown => "unknown",
        }
    }
}

/// 傳輸層錯誤來源（Python 版以 SDK 例外字串分類，連線/逾時會落入 unknown；Rust 直接依來源分類）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transport {
    Connect,
    Timeout,
}

#[derive(Debug, Clone)]
pub struct ApiError {
    pub message: String,
    pub status: Option<u16>,
    pub transport: Option<Transport>,
    /// 回應標頭 `retry-after-ms` / `retry-after` 換算的秒數
    pub retry_after: Option<f64>,
}

impl ApiError {
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into(), status: None, transport: None, retry_after: None }
    }

    /// 仿 OpenAI SDK 的 `Error code: {status} - {body}` 格式，讓字串分類與 Python 一致。
    pub fn http(status: u16, body: &str, retry_after: Option<f64>) -> Self {
        Self { message: format!("Error code: {status} - {body}"), status: Some(status), transport: None, retry_after }
    }

    pub fn from_reqwest(e: &reqwest::Error) -> Self {
        let transport = if e.is_timeout() {
            Some(Transport::Timeout)
        } else if e.is_connect() || e.is_request() {
            Some(Transport::Connect)
        } else {
            None
        };
        let message = match transport {
            Some(Transport::Timeout) => "Request timed out.".to_string(),
            Some(Transport::Connect) => format!("Connection error. ({e})"),
            None => e.to_string(),
        };
        Self { message, status: None, transport, retry_after: None }
    }

    pub fn kind(&self) -> ApiErrorKind {
        match self.transport {
            Some(Transport::Connect) => ApiErrorKind::Connection,
            Some(Transport::Timeout) => ApiErrorKind::Timeout,
            None => classify_message(&self.message),
        }
    }
}

impl fmt::Display for ApiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ApiError {}

/// 依錯誤訊息分類（與 Python `_classify_error` 的字串規則相同）。
pub fn classify_message(message: &str) -> ApiErrorKind {
    let s = message.to_lowercase();
    let has = |needles: &[&str]| needles.iter().any(|n| s.contains(n));
    if has(&["rate limit", "rate_limit", "too many requests"]) {
        ApiErrorKind::RateLimit
    } else if has(&["timeout"]) {
        ApiErrorKind::Timeout
    } else if has(&["unauthorized", "authentication", "api key"]) {
        ApiErrorKind::Authentication
    } else if has(&["content filter", "content_filter", "content policy"]) {
        ApiErrorKind::ContentFilter
    } else if has(&["server error", "500", "502", "503", "504"]) {
        ApiErrorKind::Server
    } else {
        ApiErrorKind::Unknown
    }
}

/// 429 等待時間上限：超過多半是日限額，重試也無法在合理時間內成功
pub const RATE_LIMIT_MAX_WAIT: f64 = 120.0;

static TRY_AGAIN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)try again in (?:(\d+)m(?!s))?\s*(?:([\d.]+)\s*(ms|s))?").unwrap());

/// 429 後的等待秒數：retry-after 標頭 → 訊息中的 "try again in 1m2.5s" → 指數退避加抖動。
pub fn rate_limit_wait_time(error: &ApiError, tries: u32) -> f64 {
    if let Some(secs) = error.retry_after {
        return (secs + 0.5).min(RATE_LIMIT_MAX_WAIT);
    }
    if let Ok(Some(caps)) = TRY_AGAIN.captures(&error.message) {
        let minutes = caps.get(1).and_then(|m| m.as_str().parse::<f64>().ok());
        let value = caps.get(2).and_then(|m| m.as_str().parse::<f64>().ok());
        if minutes.is_some() || caps.get(2).is_some() {
            let mut seconds = minutes.unwrap_or(0.0) * 60.0;
            if let Some(v) = value {
                // 與 Python 相同，只有小寫 "ms" 視為毫秒
                seconds += if caps.get(3).is_some_and(|u| u.as_str() == "ms") { v / 1000.0 } else { v };
            }
            if seconds > 0.0 {
                return (seconds + 0.5).min(RATE_LIMIT_MAX_WAIT);
            }
        }
    }
    2f64.powi(tries as i32).min(60.0) + rand::random::<f64>()
}

/// 解析 `retry-after-ms` / `retry-after` 標頭（秒）。
pub fn parse_retry_after(headers: &reqwest::header::HeaderMap) -> Option<f64> {
    let get = |name: &str| headers.get(name).and_then(|v| v.to_str().ok()).and_then(|v| v.trim().parse::<f64>().ok());
    get("retry-after-ms").map(|ms| ms / 1000.0).or_else(|| get("retry-after"))
}
