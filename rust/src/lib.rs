//! SRT Subtitle Translator — Rust 移植版。
//!
//! 移植計畫與進度見 `rust/PORTING_PLAN.md`。Python 版（`src/srt_translator/`）為行為規格。

pub mod cache;
pub mod client;
pub mod config;
pub mod error;
pub mod glossary;
pub mod models;
pub mod output;
pub mod prompt;
pub mod py;
pub mod service;
pub mod subtitle;
pub mod text;
pub mod tools;

pub use error::{Error, Result};
