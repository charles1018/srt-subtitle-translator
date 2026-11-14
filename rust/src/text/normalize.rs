//! 翻譯輸出的文字清理與正規化（對等 Python `TranslationClient` / `TranslationService` 的靜態方法）。

use std::sync::LazyLock;

use fancy_regex::Regex;

use crate::py;

const TERM_REPLACEMENTS: [(&str, &str); 8] = [
    ("首席執行官", "執行長"),
    ("聯邦儲備局", "聯準會"),
    ("美聯儲", "聯準會"),
    ("通貨膨脹", "通膨"),
    ("通脹", "通膨"),
    ("增長", "成長"),
    ("招聘", "招募"),
    ("威廉姆斯", "威廉斯"),
];

static REGEX_REPLACEMENTS: LazyLock<Vec<(Regex, &'static str)>> = LazyLock::new(|| {
    [
        (r"美國聯邦儲備(?!銀行)", "聯準會"),
        (r"美國聯準會", "聯準會"),
        (r"聯邦儲備(?!銀行)", "聯準會"),
        (r"美東時間", "東部時間"),
        (r"約翰\s*[·•‧]?\s*威廉斯", "約翰·威廉斯"),
        (r"([\x{4e00}-\x{9fff}])\s*[·•‧]\s*([\x{4e00}-\x{9fff}])", "${1}·${2}"),
    ]
    .into_iter()
    .map(|(p, r)| (Regex::new(p).unwrap(), r))
    .collect()
});

/// 將常見的陸式詞彙收斂為台灣字幕慣用用語。
pub fn normalize_taiwan_subtitle_terminology(text: &str) -> String {
    let mut out = text.to_string();
    for (from, to) in TERM_REPLACEMENTS {
        out = out.replace(from, to);
    }
    for (pattern, replacement) in REGEX_REPLACEMENTS.iter() {
        out = pattern.replace_all(&out, *replacement).into_owned();
    }
    out
}

/// `re.sub(r"\s+", repl, text)`
pub fn collapse_whitespace(text: &str, repl: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut in_space = false;
    for c in text.chars() {
        if py::is_space(c) {
            if !in_space {
                out.push_str(repl);
                in_space = true;
            }
        } else {
            out.push(c);
            in_space = false;
        }
    }
    out
}

/// 原文為單行時，移除模型插入的換行與多餘空白。
pub fn clean_single_line_translation(original_text: &str, translated_text: &str) -> String {
    if original_text.contains('\n') {
        return translated_text.to_string();
    }
    py::strip(&collapse_whitespace(translated_text, " ")).to_string()
}

static OIL_SHOCK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A(?:the )?oil shock\.?\z").unwrap());
static STRAIGHT_AHEAD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\Astraight ahead\.?\z").unwrap());
static MUCH_MORE_LEADING: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    [
        r"^稍後請看",
        r"^接下來(?:我們)?(?:將)?(?:會)?(?:來)?(?:繼續)?(?:深入)?(?:探討|看看|談談)",
        r"^接下來是",
        r"^更多內容將\s*[與跟]",
        r"^更多內容將",
        r"^更多(?:的是)?",
    ]
    .into_iter()
    .map(|p| Regex::new(p).unwrap())
    .collect()
});
static MUCH_MORE_TRAILING: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    [r"(?:的)?更多觀點[。！？]?$", r"(?:的)?更多內容[。！？]?$", r"討論[。！？]?$", r"的看法[。！？]?$"]
        .into_iter()
        .map(|p| Regex::new(p).unwrap())
        .collect()
});

/// 根據原文片語修正少數高頻但容易失真的字幕譯法。
pub fn normalize_source_aware_subtitle_phrases(original_text: &str, translated_text: &str) -> String {
    let normalized_source = py::strip(&collapse_whitespace(original_text, " ")).to_lowercase();
    let mut translation = py::strip(translated_text).to_string();

    if OIL_SHOCK.is_match(&normalized_source).unwrap_or(false) {
        translation = translation.replace("石油危機", "油價衝擊").replace("石油衝擊", "油價衝擊");
    }
    if STRAIGHT_AHEAD.is_match(&normalized_source).unwrap_or(false) {
        return "稍後回來".to_string();
    }
    if normalized_source.starts_with("much more with ") {
        let mut candidate = translation.clone();
        for p in MUCH_MORE_LEADING.iter().chain(MUCH_MORE_TRAILING.iter()) {
            candidate = p.replace_all(&candidate, "").into_owned();
        }
        let candidate = collapse_whitespace(&candidate, "");
        let candidate = py::strip_chars(&candidate, "，。！？、");
        if !candidate.is_empty() {
            return format!("稍後請看{candidate}");
        }
    }
    translation
}

static THINK_BLOCK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)<think>[\s\S]*?</think>\s*").unwrap());
static IM_START: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)^<\|im_start\|>assistant\s*").unwrap());
static IM_END: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)\s*<\|im_end\|>$").unwrap());
static FENCE_JSON: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)^```json\s*").unwrap());
static FENCE_OPEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)^```\s*").unwrap());
static FENCE_CLOSE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?is)\s*```$").unwrap());

fn sub(re: &Regex, text: &str) -> String {
    py::strip(&re.replace_all(text, "")).to_string()
}

/// 清理本地模型回傳中常見的推理與模板殘留。
pub fn sanitize_local_translation(translation: &str) -> String {
    let cleaned = sub(&THINK_BLOCK, py::strip(translation));
    let cleaned = sub(&IM_START, &cleaned);
    let cleaned = sub(&IM_END, &cleaned);
    py::strip(&cleaned.replace("<think>", "").replace("</think>", "")).to_string()
}

/// 從 llama.cpp schema-constrained JSON 回應提取翻譯文字；非 JSON 時回傳清理後原文。
pub fn extract_llamacpp_structured_translation(content: &str) -> String {
    let cleaned = py::strip(content);
    if cleaned.is_empty() {
        return String::new();
    }
    let mut cleaned = sub(&THINK_BLOCK, cleaned);
    if let Some(start) = cleaned.find('{') {
        if start > 0 {
            cleaned = cleaned[start..].to_string();
        }
    }
    let cleaned = sub(&FENCE_JSON, &cleaned);
    let cleaned = sub(&FENCE_OPEN, &cleaned);
    let cleaned = sub(&FENCE_CLOSE, &cleaned);

    match serde_json::from_str::<serde_json::Value>(&cleaned) {
        Ok(serde_json::Value::Object(map)) => match map.get("translation") {
            Some(serde_json::Value::String(t)) => py::strip(t).to_string(),
            _ => cleaned,
        },
        _ => cleaned,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn taiwan_terms() {
        assert_eq!(normalize_taiwan_subtitle_terminology("美聯儲宣布通脹增長"), "聯準會宣布通膨成長");
        assert_eq!(normalize_taiwan_subtitle_terminology("約翰 • 威廉姆斯"), "約翰·威廉斯");
        assert_eq!(normalize_taiwan_subtitle_terminology("聯邦儲備銀行"), "聯邦儲備銀行");
    }

    #[test]
    fn source_aware_phrases() {
        assert_eq!(normalize_source_aware_subtitle_phrases("Straight ahead.", "直走"), "稍後回來");
        assert_eq!(normalize_source_aware_subtitle_phrases("The oil shock", "石油危機"), "油價衝擊");
        assert_eq!(
            normalize_source_aware_subtitle_phrases("Much more with  John", "接下來我們將探討約翰的更多觀點。"),
            "稍後請看約翰"
        );
    }

    #[test]
    fn single_line_cleanup() {
        assert_eq!(clean_single_line_translation("one line", "第一\n第二 "), "第一 第二");
        assert_eq!(clean_single_line_translation("a\nb", "第一\n第二"), "第一\n第二");
    }

    #[test]
    fn structured_output() {
        assert_eq!(extract_llamacpp_structured_translation("<think>x</think>{\"translation\": \" 你好 \"}"), "你好");
        assert_eq!(extract_llamacpp_structured_translation("```json\n{\"translation\":\"嗨\"}\n```"), "嗨");
        assert_eq!(extract_llamacpp_structured_translation("純文字"), "純文字");
        assert_eq!(sanitize_local_translation("<|im_start|>assistant\n你好<|im_end|>"), "你好");
    }
}
