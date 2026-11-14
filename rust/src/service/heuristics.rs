//! 上下文視窗與智慧批次的啟發式判斷（對等 Python `TranslationService` 的靜態判斷方法）。
//!
//! 這些規則決定每句送給模型的上下文量與是否合併批次，直接影響翻譯品質，修改前需 benchmark。

use std::sync::LazyLock;

use fancy_regex::Regex;

use crate::py;

pub const ASCII_ENGLISH_SOURCE_RATIO_MIN: f64 = 0.6;
pub const DEFAULT_MAX_CONTEXT_ITEMS: i64 = 3;
pub const MAX_STRUCTURED_BATCH_SIZE: i64 = 30;

const LEADING_LINKERS: [&str; 23] = [
    "and",
    "but",
    "so",
    "then",
    "because",
    "if",
    "when",
    "while",
    "before",
    "after",
    "unless",
    "though",
    "since",
    "until",
    "as",
    "also",
    "still",
    "meanwhile",
    "besides",
    "plus",
    "or",
    "nor",
    "yet",
];
const TRAILING_LINKERS: [&str; 14] = [
    "when", "if", "because", "although", "while", "before", "after", "unless", "though", "since", "until", "as",
    "where", "whereas",
];
const AMBIGUOUS_PRONOUNS: [&str; 21] = [
    "he",
    "she",
    "it",
    "they",
    "them",
    "this",
    "that",
    "these",
    "those",
    "his",
    "her",
    "hers",
    "their",
    "theirs",
    "its",
    "him",
    "himself",
    "herself",
    "themselves",
    "there",
    "here",
];
const SHORT_QUESTION_STARTERS: [&str; 15] =
    ["do", "does", "did", "is", "are", "was", "were", "have", "has", "had", "can", "could", "would", "will", "should"];
const SAFE_SHORT_STARTERS: [&str; 15] =
    ["a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "their", "our", "its", "no"];
const INCOMPLETE_ENDINGS: [&str; 8] = [",", ";", ":", "-", "—", "–", "...", "…"];

static LEADING_LINKER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!(r"^({})\b", LEADING_LINKERS.join("|"))).unwrap());
static WORD_TOKENS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[A-Za-z']+").unwrap());
static TIME_LIKE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A[\d\s:./,\-APMapm]+\z").unwrap());

/// 執行期可調設定（`user_settings.json` 的 `translation.*`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeSettings {
    pub batch_size: i64,
    pub max_context_items: i64,
    pub smart_context_enabled: bool,
    pub compact_prompt_enabled: bool,
    pub terminology_enabled: bool,
}

impl Default for RuntimeSettings {
    fn default() -> Self {
        Self {
            batch_size: 10,
            max_context_items: DEFAULT_MAX_CONTEXT_ITEMS,
            smart_context_enabled: true,
            compact_prompt_enabled: true,
            terminology_enabled: true,
        }
    }
}

fn word_tokens(text: &str) -> Vec<String> {
    WORD_TOKENS.find_iter(text).flatten().map(|m| m.as_str().to_string()).collect()
}

/// ASCII 英文字母占所有字母的比例（沒有字母時為 1.0）。
pub fn ascii_letter_ratio(text: &str) -> f64 {
    let letters: Vec<char> = text.chars().filter(|c| c.is_alphabetic()).collect();
    if letters.is_empty() {
        return 1.0;
    }
    letters.iter().filter(|c| c.is_ascii_alphabetic()).count() as f64 / letters.len() as f64
}

pub fn is_english_source_lang(source_lang: Option<&str>) -> bool {
    let normalized = py::strip(source_lang.unwrap_or_default()).to_lowercase();
    ["英文", "english", "en", "en-us", "en_us", "en-gb", "en_gb"].contains(&normalized.as_str())
}

/// 是否允許套用英文短句的上下文/批次啟發式。
pub fn allows_english_short_text_heuristics(text: &str, source_lang: Option<&str>) -> bool {
    if source_lang.is_some_and(|s| !s.is_empty()) && !is_english_source_lang(source_lang) {
        return false;
    }
    ascii_letter_ratio(text) >= ASCII_ENGLISH_SOURCE_RATIO_MIN
}

/// 保守判斷句子是否依賴前後文（多行、小寫開頭、連接詞、代名詞短句…）。
pub fn text_needs_context(text: &str) -> bool {
    let stripped = py::strip(text);
    if stripped.is_empty() {
        return false;
    }
    if stripped.contains('\n') || stripped.chars().next().is_some_and(char::is_lowercase) {
        return true;
    }
    let normalized = stripped.to_lowercase();
    if LEADING_LINKER_RE.is_match(&normalized).unwrap_or(false)
        || TRAILING_LINKERS.iter().any(|l| normalized.ends_with(&format!(" {l}")))
        || INCOMPLETE_ENDINGS.iter().any(|e| stripped.ends_with(e))
    {
        return true;
    }
    let tokens = word_tokens(&normalized);
    let has_pronoun = tokens.iter().any(|t| AMBIGUOUS_PRONOUNS.contains(&t.as_str()));
    let is_question = stripped.contains('?') || stripped.contains('？');
    if is_question
        && (1..=4).contains(&tokens.len())
        && (has_pronoun || SHORT_QUESTION_STARTERS.contains(&tokens[0].as_str()))
    {
        return true;
    }
    (1..=6).contains(&tokens.len()) && has_pronoun
}

/// 可安全獨立翻譯的短句（純時間/數字，或 ≤24 字且不依賴上下文）。
pub fn is_context_free_short_text(text: &str) -> bool {
    let stripped = py::strip(text);
    if stripped.is_empty() {
        return false;
    }
    if TIME_LIKE.is_match(stripped).unwrap_or(false) {
        return true;
    }
    let compact_len = stripped.chars().filter(|c| !py::is_space(*c)).count();
    compact_len <= 24 && !text_needs_context(stripped)
}

/// 是否適合進入智慧批次（避免短問答與碎片句錯配）。
pub fn is_batch_safe_short_text(text: &str, source_lang: Option<&str>) -> bool {
    let stripped = py::strip(text);
    if !allows_english_short_text_heuristics(stripped, source_lang) || !is_context_free_short_text(stripped) {
        return false;
    }
    if ["?", "？", "!", "！"].iter().any(|m| stripped.contains(m)) {
        return false;
    }
    if TIME_LIKE.is_match(stripped).unwrap_or(false) {
        return true;
    }
    let tokens = word_tokens(&stripped.to_lowercase());
    if tokens.is_empty() {
        return false;
    }
    if tokens.len() <= 3 {
        if tokens.iter().any(|t| t.contains('\'')) {
            return false;
        }
        return SAFE_SHORT_STARTERS.contains(&tokens[0].as_str());
    }
    true
}

fn uses_question_mood(text: &str) -> bool {
    let s = py::strip(text);
    s.contains('?') || s.contains('？')
}

fn uses_exclamation_mood(text: &str) -> bool {
    let s = py::strip(text);
    s.contains('!') || s.contains('！')
}

/// 批次翻譯是否保留每一行的疑問/驚嘆句型。
pub fn batch_translation_preserves_sentence_mood(sources: &[String], translations: &[String]) -> bool {
    sources.len() == translations.len()
        && sources.iter().zip(translations).all(|(s, t)| {
            uses_question_mood(s) == uses_question_mood(t) && uses_exclamation_mood(s) == uses_exclamation_mood(t)
        })
}

/// 依句子特徵決定上下文視窗大小（前後各幾句）。
pub fn context_window_for_text(text: &str, settings: &RuntimeSettings, source_lang: Option<&str>) -> usize {
    let max = settings.max_context_items;
    if max <= 0 || py::strip(text).is_empty() {
        return 0;
    }
    let max = max as usize;
    if !settings.smart_context_enabled
        || !allows_english_short_text_heuristics(text, source_lang)
        || text_needs_context(text)
    {
        return max;
    }
    if is_context_free_short_text(text) {
        0
    } else {
        max.min(1)
    }
}

/// 從指定位置開始、可合併為智慧批次的連續字幕數。
pub fn count_consecutive_batchable(start: usize, flags: &[bool], max_batch_size: usize) -> usize {
    flags.iter().skip(start).take(max_batch_size).take_while(|f| **f).count()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn context_heuristics() {
        assert!(text_needs_context("and then he left"));
        assert!(text_needs_context("Is it?"));
        assert!(!text_needs_context("The fire is out."));
        assert!(is_context_free_short_text("10:30 PM"));
        assert!(is_batch_safe_short_text("The car.", Some("英文")));
        assert!(!is_batch_safe_short_text("The car.", Some("日文")));
        assert!(!is_batch_safe_short_text("Go!", None));
        assert_eq!(count_consecutive_batchable(1, &[true, true, true, false, true], 10), 2);
    }
}
