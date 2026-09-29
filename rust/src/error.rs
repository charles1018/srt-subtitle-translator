//! 錯誤型別，錯誤碼與 Python `utils/errors.py` 對齊。

use serde_json::{Map, Value};

/// 錯誤附帶的結構化細節（對應 Python `AppError.details`）。
pub type Details = Map<String, Value>;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("[1100] {message}")]
    Config { message: String, details: Details },
    #[error("[1300] {message}")]
    Translation { message: String, details: Details },
    #[error("[1400] {message}")]
    File { message: String, details: Details },
    #[error("[1900] {message}")]
    Validation { message: String, details: Details },
    /// 使用者停止翻譯任務（見 `service::TaskControl`）。
    #[error("[1300] 翻譯已停止")]
    Cancelled,
}

static EMPTY_DETAILS: std::sync::LazyLock<Details> = std::sync::LazyLock::new(Details::new);

impl Error {
    pub fn file(message: impl Into<String>) -> Self {
        Self::File { message: message.into(), details: Details::new() }
    }

    pub fn file_with(message: impl Into<String>, details: Details) -> Self {
        Self::File { message: message.into(), details }
    }

    pub fn validation(message: impl Into<String>, details: Details) -> Self {
        Self::Validation { message: message.into(), details }
    }

    pub fn error_code(&self) -> u32 {
        match self {
            Self::Config { .. } => 1100,
            Self::Translation { .. } | Self::Cancelled => 1300,
            Self::File { .. } => 1400,
            Self::Validation { .. } => 1900,
        }
    }

    pub fn details(&self) -> &Details {
        match self {
            Self::Config { details, .. }
            | Self::Translation { details, .. }
            | Self::File { details, .. }
            | Self::Validation { details, .. } => details,
            Self::Cancelled => &EMPTY_DETAILS,
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;
