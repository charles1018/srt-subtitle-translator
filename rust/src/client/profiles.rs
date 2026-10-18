//! 模型家族偵測與 llama.cpp 請求 profile（對等 Python `TranslationClient` 的 profile 相關方法）。
//!
//! 採樣參數經 benchmark 調校，修改前需 A/B 驗證（見 `llamacpp-server` skill）。

use std::sync::LazyLock;

use fancy_regex::Regex;
use serde::Serialize;
use serde_json::{json, Map, Value};

static HUNYUAN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?:hunyuan[-_/\s]?mt|hy[-_/\s]?mt)").unwrap());
static QWEN36: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"qwen(?:[-_/\s]?3\.6|36)").unwrap());
static QWEN35: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"qwen(?:[-_/\s]?3\.5|35)").unwrap());
static QWEN3: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"qwen[-_/\s]?3\b").unwrap());
static GEMMA4: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"gemma[-_/\s]?4\b").unwrap());
static COMPLETION_TOKENS_GPT5: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^gpt-5(?:\.\d+)?(?:[-_]|$)").unwrap());
static COMPLETION_TOKENS_O: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^o[134](?:[-_]|$)").unwrap());

/// 跳過 llama.cpp JSON schema 強制輸出的家族（Qwen3.6 推理劣化；Hunyuan-MT 翻譯專用模型直接輸出純文字較佳）
pub const SKIP_JSON_SCHEMA_FAMILIES: [&str; 2] = ["qwen3.6", "hunyuan-mt"];
const QWEN_UD_FAMILIES: [&str; 2] = ["qwen3.5", "qwen3.6"];
const QWEN_UD_ALIAS_KEYWORDS: [&str; 3] = ["heretic", "omnimerge", "bartowski"];

/// 標準化模型名稱：去空白、小寫、去掉 `@` 之後的部分。
pub fn normalize_model_name(model_name: &str) -> String {
    let lower = crate::py::strip(model_name).to_lowercase();
    lower.split('@').next().unwrap_or_default().to_string()
}

fn search(re: &Regex, text: &str) -> bool {
    re.is_match(text).unwrap_or(false)
}

/// 根據模型名稱偵測本地模型家族。
pub fn detect_model_family(model_name: &str) -> &'static str {
    let n = normalize_model_name(model_name);
    if search(&HUNYUAN, &n) {
        "hunyuan-mt"
    } else if search(&QWEN36, &n) {
        "qwen3.6"
    } else if search(&QWEN35, &n) {
        "qwen3.5"
    } else if search(&QWEN3, &n) {
        "qwen3"
    } else if n.contains("qwen") {
        "qwen"
    } else if n.contains("llama") {
        "llama"
    } else if search(&GEMMA4, &n) {
        "gemma4"
    } else if n.contains("gemma") {
        "gemma"
    } else if n.contains("mistral") {
        "mistral"
    } else {
        "default"
    }
}

/// Qwen3.5 / Qwen3.6 的 UD 變體（含社群對照組 heretic/omnimerge/bartowski）。
///
/// 注意：與 `prompt::is_qwen_ud_model` 不同，client 端額外接受社群別名關鍵字（與 Python 相同）。
pub fn is_qwen_ud_model(model_name: &str) -> bool {
    if !QWEN_UD_FAMILIES.contains(&detect_model_family(model_name)) {
        return false;
    }
    let n = normalize_model_name(model_name);
    n.split(|c: char| !(c.is_ascii_lowercase() || c.is_ascii_digit())).any(|t| t == "ud")
        || QWEN_UD_ALIAS_KEYWORDS.iter().any(|k| n.contains(k))
}

/// GPT-5.x 與 o-series 推理模型把 `max_tokens` 改名為 `max_completion_tokens`。
pub fn openai_uses_completion_tokens(model_name: &str) -> bool {
    let n = crate::py::strip(model_name).to_lowercase();
    search(&COMPLETION_TOKENS_GPT5, &n) || search(&COMPLETION_TOKENS_O, &n)
}

pub const OPENAI_BATCH_BASE_TOKENS: i64 = 100;
pub const OPENAI_BATCH_TOKENS_PER_LINE: i64 = 60;
pub const OPENAI_BATCH_MIN_TOKENS: i64 = 200;
pub const OPENAI_BATCH_MAX_TOKENS: i64 = 2000;

/// 依批次行數估算 OpenAI 輸出 token 預算。
pub fn openai_batch_max_tokens(line_count: i64) -> i64 {
    (OPENAI_BATCH_BASE_TOKENS + line_count * OPENAI_BATCH_TOKENS_PER_LINE)
        .clamp(OPENAI_BATCH_MIN_TOKENS, OPENAI_BATCH_MAX_TOKENS)
}

/// llama.cpp profile 原始定義（`null` 代表從 default 移除該鍵），逐字對齊 Python `LLAMACPP_MODEL_PROFILES`。
static LLAMACPP_MODEL_PROFILES: LazyLock<Map<String, Value>> = LazyLock::new(|| {
    let qwen = |max_tokens: i64| {
        json!({
            "batch_concurrency_limit": null,
            "options": {"temperature": 0.7, "top_p": 0.8, "max_tokens": max_tokens},
            "extra_body": {"presence_penalty": 1.5, "top_k": 20, "min_p": 0.0},
        })
    };
    let value = json!({
        "default": {
            "batch_concurrency_limit": null,
            "options": {"temperature": 0.1, "max_tokens": 256},
            "extra_body": {
                "cache_prompt": true,
                "reasoning_format": "deepseek",
                "reasoning_budget_tokens": 0,
                "seed": 42,
                "chat_template_kwargs": {"enable_thinking": false},
            },
        },
        "qwen3": qwen(256),
        "qwen3.5": qwen(256),
        "qwen3.5-ud": qwen(96),
        "qwen3.6": qwen(256),
        "qwen3.6-ud": qwen(96),
        "gemma4": {
            "batch_concurrency_limit": null,
            "options": {"temperature": 1.0, "top_p": 0.95, "max_tokens": 256},
            "extra_body": {
                "top_k": 64,
                // Gemma 4 的 thinking 格式不是 deepseek，覆蓋 default 的設定
                "reasoning_format": "none",
                // 新版 llama.cpp 建議改用 reasoning=off，而非 template kwargs
                "reasoning": "off",
                "reasoning_budget_tokens": null,
                "chat_template_kwargs": null,
            },
        },
        // Hunyuan-MT2：官方建議 temp 0.7 / top_p 0.6 / top_k 20 / repetition_penalty 1.05，無 thinking 模式。
        // max_tokens 256：128 對繁中→日等反向方向會截斷長句。
        "hunyuan-mt": {
            "batch_concurrency_limit": null,
            "options": {"temperature": 0.7, "top_p": 0.6, "max_tokens": 256},
            "extra_body": {
                "repetition_penalty": 1.05,
                "top_k": 20,
                "min_p": 0.0,
                "reasoning_format": "none",
                "reasoning_budget_tokens": null,
                "chat_template_kwargs": null,
            },
        },
    });
    match value {
        Value::Object(map) => map,
        _ => unreachable!(),
    }
});

/// 合併後的 llama.cpp 請求設定。
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct LlamacppProfile {
    pub family: &'static str,
    pub profile: String,
    pub batch_concurrency_limit: Option<i64>,
    pub options: Map<String, Value>,
    pub extra_body: Map<String, Value>,
}

fn object(v: Option<&Value>, key: &str) -> Map<String, Value> {
    v.and_then(|p| p.get(key)).and_then(Value::as_object).cloned().unwrap_or_default()
}

/// 以 default 為底合併家族 profile；`effective_name` 應為已解析的實際模型名稱。
pub fn llamacpp_profile(effective_name: &str) -> LlamacppProfile {
    let family = detect_model_family(effective_name);
    let profile_key = if is_qwen_ud_model(effective_name) { format!("{family}-ud") } else { family.to_string() };
    let default = LLAMACPP_MODEL_PROFILES.get("default");
    let family_profile = LLAMACPP_MODEL_PROFILES.get(&profile_key);

    let default_extra = object(default, "extra_body");
    let family_extra = object(family_profile, "extra_body");
    let mut extra_body = default_extra.clone();
    for (key, value) in &family_extra {
        if value.is_null() {
            extra_body.shift_remove(key);
        } else {
            extra_body.insert(key.clone(), value.clone());
        }
    }
    let default_ctk = default_extra.get("chat_template_kwargs").and_then(Value::as_object);
    let family_ctk_entry = family_extra.get("chat_template_kwargs");
    if family_ctk_entry.is_some_and(Value::is_null) {
        extra_body.shift_remove("chat_template_kwargs");
    } else if default_ctk.is_some() || family_ctk_entry.is_some_and(Value::is_object) {
        let mut merged = default_ctk.cloned().unwrap_or_default();
        if let Some(Value::Object(f)) = family_ctk_entry {
            merged.extend(f.clone());
        }
        extra_body.insert("chat_template_kwargs".into(), Value::Object(merged));
    }

    let mut options = object(default, "options");
    options.extend(object(family_profile, "options"));
    LlamacppProfile {
        family,
        profile: profile_key,
        batch_concurrency_limit: family_profile.and_then(|p| p.get("batch_concurrency_limit")).and_then(Value::as_i64),
        options,
        extra_body,
    }
}

/// 每 token 單價（USD），用於 metrics 估算費用。
pub fn pricing(llm_type: &str, model_name: &str) -> Option<(f64, f64)> {
    let table: &[(&str, f64, f64)] = match llm_type {
        "openai" => &[
            ("gpt-4.1-mini", 0.0000004, 0.0000016),
            ("gpt-4.1", 0.000002, 0.000008),
            ("gpt-4.1-nano", 0.0000001, 0.0000004),
            ("gpt-4o", 0.0000025, 0.00001),
            ("gpt-4o-mini", 0.00000015, 0.0000006),
            ("gpt-3.5-turbo", 0.0000005, 0.0000015),
            ("gpt-4", 0.00003, 0.00006),
            ("gpt-4-turbo", 0.00001, 0.00003),
        ],
        "google" => &[
            ("gemini-2.0-flash", 0.0, 0.0),
            ("gemini-2.5-flash", 0.00000015, 0.0000006),
            ("gemini-2.5-pro", 0.00000125, 0.000005),
            ("gemini-1.5-flash", 0.000000075, 0.0000003),
            ("gemini-1.5-pro", 0.00000125, 0.000005),
        ],
        _ => &[],
    };
    table.iter().find(|(m, _, _)| *m == model_name).map(|(_, i, o)| (*i, *o))
}

/// 各 provider 的回退模型（llama-server 只載入單一模型，無需回退）。
pub fn fallback_models(llm_type: &str, model_name: &str) -> &'static [&'static str] {
    match (llm_type, model_name) {
        ("openai", "gpt-4") => &["gpt-3.5-turbo"],
        ("openai", "gpt-4-turbo") => &["gpt-4", "gpt-3.5-turbo"],
        ("google", "gemini-2.5-pro") => &["gemini-2.5-flash", "gemini-2.0-flash"],
        ("google", "gemini-2.5-flash") => &["gemini-2.0-flash", "gemini-1.5-flash"],
        ("google", "gemini-2.0-flash") => &["gemini-1.5-flash"],
        ("google", "gemini-1.5-pro") => &["gemini-1.5-flash"],
        _ => &[],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hunyuan_profile_drops_thinking_settings() {
        let p = llamacpp_profile("Hy-MT2-7B-Q4_K_M.gguf");
        assert_eq!(p.family, "hunyuan-mt");
        assert_eq!(p.options["top_p"], json!(0.6));
        assert!(!p.extra_body.contains_key("chat_template_kwargs"));
        assert!(!p.extra_body.contains_key("reasoning_budget_tokens"));
        assert_eq!(p.extra_body["seed"], json!(42));
    }

    #[test]
    fn batch_tokens_are_clamped() {
        assert_eq!(openai_batch_max_tokens(1), 200);
        assert_eq!(openai_batch_max_tokens(10), 700);
        assert_eq!(openai_batch_max_tokens(40), 2000);
    }
}
