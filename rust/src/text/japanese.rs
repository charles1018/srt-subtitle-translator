//! 日文人名占位保護與未翻譯日文偵測（對等 Python `TranslationClient` 的對應 classmethod）。
//!
//! 正則逐字搬自 `translation/client.py`，改動前需 A/B benchmark。

use std::sync::LazyLock;

use fancy_regex::{NoExpand, Regex};

use crate::py;

pub const PLACEHOLDER_PREFIX: &str = "JN";

pub const UNTRANSLATED_RETRY_INSTRUCTION: &str = "CRITICAL RETRY INSTRUCTION:\n\
The previous output still contained untranslated Japanese.\n\
You MUST translate the CURRENT subtitle into Traditional Chinese (Taiwan).\n\
Do not leave hiragana or katakana in the final answer unless it is a protected placeholder like [[JN0]].\n\
Return only the translated subtitle text.";

/// Python 版以 `(?:(?<=^)|(?<=[...]))` 起始；`(?<=^)` 與 `^` 等價。
static NAME_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"(?:^|(?<=[、，。！？!?「」（）『』\s]))",
        r"(([ァ-ヶー]{2,10}|[ぁ-ゖーっ]{2,10})(?:ちゃん|くん|君|さん|さま|様|先輩|先生|氏))",
        // 結尾邊界：句尾、標點、空白、格助詞，以及口語句中助詞（って/さ/ね/よ/な）
        r"(?=$|[、，。！？!?」』\s]|の|が|を|に|へ|と|も|は|って|さ|ね|よ|な)",
    ))
    .unwrap()
});
static PLACEHOLDER_PATTERN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\[\[[A-Z0-9]+\]\]").unwrap());
static LEAKED_PLACEHOLDER_PATTERN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?:\[\[\s*JN\d+\s*\]\]|\[\s*JN\d+\s*\]|(?<![A-Z0-9_])JN\d+(?![A-Z0-9_]))").unwrap());
static COMPARISON_STRIP: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"[\s、，。．！？!?…・「」『』（）()【】［］\[\]<>《》〈〉〜～\-—_"'`]+"#).unwrap());

/// `[ぁ-ゖァ-ヺー]`
fn is_kana(c: char) -> bool {
    matches!(c, 'ぁ'..='ゖ' | 'ァ'..='ヺ' | 'ー')
}

/// `[ぁ-ゖ]`
fn is_hiragana(c: char) -> bool {
    matches!(c, 'ぁ'..='ゖ')
}

/// `[一-龯々〆ヵヶ]`
fn is_cjk_ideograph(c: char) -> bool {
    matches!(c, '一'..='龯' | '々' | '〆' | 'ヵ' | 'ヶ')
}

/// 提取需要保護的日文人名或暱稱：去重後依長度由長到短（同長保持出現順序）。
pub fn extract_name_candidates(text: &str) -> Vec<String> {
    let mut candidates: Vec<String> = Vec::new();
    for caps in NAME_PATTERN.captures_iter(text).flatten() {
        let name = caps.get(1).expect("group 1 必定存在").as_str();
        if !candidates.iter().any(|c| c == name) {
            candidates.push(name.to_string());
        }
    }
    candidates.sort_by_key(|c| std::cmp::Reverse(py::len(c)));
    candidates
}

/// 占位符 → 原名，依占位符編號排序。
pub type RestoreMap = Vec<(String, String)>;

/// 將日文人名替換為 `[[JN0]]` 形式的占位符（本文與上下文一併替換）。
pub fn protect_names(text: &str, context_texts: &[String]) -> (String, Vec<String>, RestoreMap) {
    let candidates = extract_name_candidates(text);
    let mut protected_text = text.to_string();
    let mut protected_contexts = context_texts.to_vec();
    let mut restore_map = RestoreMap::new();
    for (index, candidate) in candidates.into_iter().enumerate() {
        let placeholder = format!("[[{PLACEHOLDER_PREFIX}{index}]]");
        protected_text = protected_text.replace(&candidate, &placeholder);
        for ctx in &mut protected_contexts {
            *ctx = ctx.replace(&candidate, &placeholder);
        }
        restore_map.push((placeholder, candidate));
    }
    (protected_text, protected_contexts, restore_map)
}

/// 還原模型輸出中的占位符，容忍 `[[ JN0 ]]`、`[JN0]`、裸 `JN0` 等變形。
pub fn restore_names(translation: &str, restore_map: &RestoreMap) -> String {
    let mut restored = translation.to_string();
    for (placeholder, original) in restore_map {
        let inner = fancy_regex::escape(&placeholder[2..placeholder.len() - 2]);
        let pattern =
            Regex::new(&format!(r"(?<![A-Z0-9_])(?:\[\[\s*{inner}\s*\]\]|\[\s*{inner}\s*\]|{inner})(?![A-Z0-9_])"))
                .expect("占位符正則必定合法");
        restored = pattern.replace_all(&restored, NoExpand(original)).into_owned();
    }
    restored
}

/// 移除日文未翻譯檢測中允許保留的占位符與人名。
fn remove_retry_exempt_tokens(text: &str, source_text: &str) -> String {
    let mut cleaned = PLACEHOLDER_PATTERN.replace_all(text, "").into_owned();
    for candidate in extract_name_candidates(source_text) {
        cleaned = cleaned.replace(&candidate, "");
    }
    cleaned
}

/// 正規化文字，便於比對是否幾乎原樣回傳。
pub fn normalize_for_comparison(text: &str) -> String {
    COMPARISON_STRIP.replace_all(text, "").into_owned()
}

/// 判斷翻譯結果是否仍包含明顯未翻譯的日文。
pub fn should_retry_untranslated_japanese(source_text: &str, translated_text: &str) -> bool {
    let cleaned_source = remove_retry_exempt_tokens(source_text, source_text);
    let cleaned_translation = remove_retry_exempt_tokens(translated_text, source_text);

    let source_has_cjk = cleaned_source.chars().any(is_cjk_ideograph);
    let source_kana = cleaned_source.chars().filter(|&c| is_kana(c)).count();
    let translation_kana = cleaned_translation.chars().filter(|&c| is_kana(c)).count();
    let translation_hiragana = cleaned_translation.chars().filter(|&c| is_hiragana(c)).count();

    if py::strip(&cleaned_translation).is_empty() {
        return false;
    }
    if source_kana == 0 && !source_has_cjk {
        return false;
    }
    // 正常的繁中輸出不應殘留任何平假名
    if translation_hiragana >= 1 {
        return true;
    }
    if source_kana >= 1 && translation_kana >= 1 {
        return true;
    }

    let normalized_source = normalize_for_comparison(&cleaned_source);
    let normalized_translation = normalize_for_comparison(&cleaned_translation);
    if normalized_source.is_empty() {
        return false;
    }
    if source_kana >= 1 && normalized_translation == normalized_source {
        return true;
    }
    translation_kana >= 1 && normalized_translation.contains(&normalized_source)
}

/// 判斷翻譯結果是否不適合直接信任或存入快取；回傳拒絕原因。
pub fn cache_rejection_reason(source_text: &str, translated_text: &str) -> Option<&'static str> {
    if py::strip(translated_text).is_empty() {
        return Some("empty_translation");
    }
    if LEAKED_PLACEHOLDER_PATTERN.is_match(translated_text).unwrap_or(false) {
        return Some("leaked_name_placeholder");
    }
    if should_retry_untranslated_japanese(source_text, translated_text) {
        return Some("untranslated_japanese");
    }
    None
}

pub fn is_cacheable_translation_result(source_text: &str, translated_text: &str) -> bool {
    cache_rejection_reason(source_text, translated_text).is_none()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_names_with_honorifics() {
        assert_eq!(extract_name_candidates("メアちゃん、こっち来て"), vec!["メアちゃん"]);
        assert_eq!(extract_name_candidates("「ゆいさんの」とメアちゃん"), vec!["ゆいさん"]);
        assert!(extract_name_candidates("お兄ちゃん").is_empty());
    }

    #[test]
    fn protect_and_restore_roundtrip() {
        let (text, ctx, map) = protect_names("メアちゃん、好き", &["メアちゃんは？".to_string()]);
        assert_eq!(text, "[[JN0]]、好き");
        assert_eq!(ctx, vec!["[[JN0]]は？"]);
        assert_eq!(restore_names("[ JN0 ]，我喜歡你", &map), "メアちゃん，我喜歡你");
        assert_eq!(restore_names("JN0說", &map), "メアちゃん說");
    }

    #[test]
    fn rejection_reasons() {
        assert_eq!(cache_rejection_reason("こんにちは", ""), Some("empty_translation"));
        assert_eq!(cache_rejection_reason("こんにちは", "JN3你好"), Some("leaked_name_placeholder"));
        assert_eq!(cache_rejection_reason("こんにちは", "こんにちは"), Some("untranslated_japanese"));
        assert_eq!(cache_rejection_reason("こんにちは", "你好"), None);
        assert_eq!(cache_rejection_reason("Hello", "你好"), None);
    }
}
