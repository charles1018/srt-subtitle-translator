//! 純文字處理：後處理、日文名字保護、詞彙正規化。

pub mod japanese;
pub mod normalize;
pub mod opencc;
pub mod post_processor;

pub use post_processor::{NetflixStylePostProcessor, ProcessingResult};
