//! 提示詞管理（對等 Python `core/prompt.py`）。
//!
//! **高風險模組**：prompt 文字、訊息結構與模型特化策略都經過 A/B benchmark 調校，
//! 修改前必須依 `FUTURE_AGENT_REPO_GUIDE.md` §1 跑 benchmark。
//!
//! 內建預設 prompt（`default_prompts.json`）由 `rust/tools/gen_golden.py` 從 Python 版匯出，
//! 不要手動編輯；CI 會檢查它與 Python 版一致。
//!
//! 未移植：`analyze_prompt`、`get_version_history`、`restore_version`（僅 GUI 使用）。

use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use fancy_regex::{NoExpand, Regex};
use indexmap::IndexMap;
use serde::Serialize;
use serde_json::{json, Map, Value};

use crate::cache::md5_hex;
use crate::config::{now_isoformat, to_json_indent4, ConfigFile, ConfigKind};
use crate::error::{Error, Result};
use crate::py;

pub const CONTENT_TYPES: [&str; 5] = ["general", "adult", "anime", "movie", "english_drama"];
pub const SUPPORTED_LLM_TYPES: [&str; 3] = ["openai", "google", "llamacpp"];
pub const DEFAULT_LANGUAGE_PAIR: &str = "日文→繁體中文";

/// (代碼, 描述)
pub const TRANSLATION_STYLES: [(&str, &str); 4] = [
    ("standard", "標準翻譯 - 平衡準確性和自然度"),
    ("literal", "直譯 - 更忠於原文的字面意思"),
    ("localized", "本地化翻譯 - 更適合台灣繁體中文文化"),
    ("specialized", "專業翻譯 - 保留專業術語"),
];

/// 語言對 → (來源, 目標)
pub const LANGUAGE_PAIRS: [(&str, &str, &str); 9] = [
    ("日文→繁體中文", "日文", "繁體中文"),
    ("英文→繁體中文", "英文", "繁體中文"),
    ("繁體中文→英文", "繁體中文", "英文"),
    ("繁體中文→日文", "繁體中文", "日文"),
    ("韓文→繁體中文", "韓文", "繁體中文"),
    ("法文→繁體中文", "法文", "繁體中文"),
    ("德文→繁體中文", "德文", "繁體中文"),
    ("西班牙文→繁體中文", "西班牙文", "繁體中文"),
    ("俄文→繁體中文", "俄文", "繁體中文"),
];

/// 中文語言名稱 → (英文 system prompt 用名, 中文 user message 用名)
const HUNYUAN_LANG_NAMES: [(&str, &str, &str); 8] = [
    ("日文", "Japanese", "日文"),
    ("繁體中文", "Taiwan Traditional Chinese (zh-TW)", "繁體中文（台灣）"),
    ("英文", "English", "英文"),
    ("韓文", "Korean", "韓文"),
    ("法文", "French", "法文"),
    ("德文", "German", "德文"),
    ("西班牙文", "Spanish", "西班牙文"),
    ("俄文", "Russian", "俄文"),
];

const CONJUNCTIONS: [&str; 14] = [
    "when", "if", "because", "although", "while", "before", "after", "unless", "though", "since", "until", "as",
    "where", "whereas",
];

const INCOMPLETE_ENDINGS: [&str; 12] = [",", "，", "、", ";", "；", ":", "：", "-", "—", "–", "...", "…"];

const QWEN35_UD_ADULT_ACTION_MARKERS: [&str; 22] = [
    "舐め",
    "なめ",
    "しゃぶ",
    "フェラ",
    "咥",
    "乳首",
    "まんこ",
    "おまんこ",
    "ちんこ",
    "ちんぽ",
    "ペニス",
    "根元",
    "奥",
    "ビンビン",
    "硬",
    "挿",
    "入れ",
    "出して",
    "出ちゃ",
    "イク",
    "イっ",
    "中出し",
];

const BATCH_LINE_MAPPING_INSTRUCTION: &str = "## Strict Line Mapping (CRITICAL):
Your output MUST have EXACTLY the same number of lines as the input.
Each input line maps to exactly one output line — no exceptions.
- If input has N lines, output MUST have exactly N lines
- Do NOT merge lines, skip lines, or add extra lines
- Do NOT add blank lines or explanatory text between translations
- Preserve literal \\n (two characters: backslash + n) when present in a line
- Preserve each line's sentence mood and speech act.
- A statement must stay a statement, a question must stay a question, and an imperative must stay an imperative on the same line.
- Do NOT move a question or answer meaning onto a neighboring line.
- Count your output lines carefully before submitting";

const QWEN_UD_ADULT_PROMPT: &str = "You translate Japanese adult subtitles into natural Taiwan Traditional Chinese.
Rules:
1. Translate ONLY the CURRENT line. Never translate or copy context.
2. Keep the exact same number of lines and line breaks. If the source is single-line, output a single line only.
3. Output ONLY the translated subtitle text. No labels, quotes, explanations, or extra notes.
4. The output MUST NOT end with 。 or ，. Examples — WRONG: \"我來了。\" / \"好喔。\" / \"不行了，\". RIGHT: \"我來了\" / \"好喔\" / \"不行了\". Question marks (？?), exclamation marks (！!), and ellipses (…) are allowed at the end.
5. Do not censor, soften, or moralize sexual wording.
6. Preserve who does the action to whom.
7. Preserve imperative tone, body-part target, penetration direction, and ejaculation intent accurately.
8. When the source is short or ambiguous, stay literal to the action instead of inventing softer wording.
9. Keep Japanese personal names and nicknames in their original Japanese form. Do not translate or romanize names into Chinese characters.
10. Use concise Taiwan Traditional Chinese suitable for spoken subtitles.";

const COMPACT_BASE_RULES: [&str; 17] = [
    "You translate subtitles into natural Taiwan Traditional Chinese.",
    "Translate ONLY the CURRENT text.",
    "Use reference context only to resolve ambiguity. Never copy or translate the reference text.",
    "Output ONLY the translated subtitle text.",
    "Prioritize meaning, tone, natural spoken flow, and consistency of names/terms.",
    "Translate every meaning in CURRENT; do not drop clauses or sentences.",
    "If CURRENT is an incomplete clause, keep it incomplete. Do not complete it with reference context.",
    "Prefer Taiwan subtitle wording. Avoid Mainland variants such as 通脹, 增長, 首席執行官, 美聯儲.",
    "Filler Word Filtering: omit routine fillers (well, uh, um, you know, like, I mean). Do not add 嗯/呃/啊 unless hesitation matters.",
    "Dynamic Equivalency: translate idioms and slang by function and meaning, not literally.",
    "CPS Compression: prefer concise wording that still preserves intent and tone.",
    "Keep the output as one subtitle only. Do not add explanations, labels, quotes, or extra notes.",
    "Do not arbitrarily add, remove, merge, or split line breaks.",
    "Preserve necessary punctuation and sentence mood.",
    "Do not end lines with 。, ，, or 、. Keep ？/！ when the source asks or exclaims.",
    "Use half-width Arabic digits for numbers, ages, and counts (70, 80), not Chinese numerals or full-width digits.",
    "Avoid overly long subtitle lines while preserving meaning.",
];

fn compact_content_rules(content_type: &str) -> &'static [&'static str] {
    match content_type {
        "adult" => &[
            "Use direct and accurate adult terminology when the source is explicit.",
            "Do not censor, soften, or moralize explicit content.",
        ],
        "anime" => &[
            "Preserve character names, honorifics, and iconic anime terminology when appropriate.",
            "Use wording that feels natural to Taiwan anime audiences.",
        ],
        "movie" => &[
            "Keep English personal names in English.",
            "Preserve character voice, emotion, slang, and culturally natural dialogue.",
        ],
        "english_drama" => {
            &["Keep English personal names in English.", "Preserve TV-drama dialogue rhythm, tone, and subtext."]
        }
        _ => &[],
    }
}

/// (style, llm) → 修飾語
fn style_modifier(style: &str, llm_type: &str) -> Option<&'static str> {
    Some(match (style, llm_type) {
        ("literal", "llamacpp") => "Focus on providing a more literal translation that is closer to the original text meaning. Prioritize accuracy to source text over natural flow in the target language. Remember to ONLY translate the CURRENT text, not context.",
        ("literal", "openai") => "Translate literally. Prioritize source accuracy over target fluency. Only translate the current text, never context.",
        ("localized", "llamacpp") => "Focus on adapting the content to the target culture. Use Taiwan-specific expressions, cultural references, and idioms where appropriate to make the translation feel natural to local readers. Remember to ONLY translate the CURRENT text, not context.",
        ("localized", "openai") => "Translate with cultural adaptation. Use Taiwan expressions and references. Only translate the current text, never context.",
        ("specialized", "llamacpp") => "Focus on accurate translation of terminology relevant to the content domain. Prioritize precision in specialized terms and concepts. Remember to ONLY translate the CURRENT text, not context.",
        ("specialized", "openai") => "Translate with domain precision. Prioritize accurate terminology. Only translate the current text, never context.",
        _ => return None,
    })
}

type DefaultPrompts = IndexMap<String, IndexMap<String, String>>;

static DEFAULT_PROMPTS: LazyLock<DefaultPrompts> =
    LazyLock::new(|| serde_json::from_str(include_str!("default_prompts.json")).expect("內建預設 prompt 格式錯誤"));

static QWEN_UD_FAMILY: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"qwen(?:[-_/\s]?3\.[56]|3[56])").unwrap());
static HUNYUAN_MT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?:hunyuan[-_/\s]?mt|hy[-_/\s]?mt)").unwrap());
static LANGUAGE_REFERENCE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(Taiwan Mandarin|繁體中文|Traditional Chinese)").unwrap());
static SHORT_CACHE_STRIP: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[、，。．！？!?…・「」『』（）()【】\s]").unwrap());
static KANA_ONLY: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A[ぁ-ゖゝゞァ-ヶー]+\z").unwrap());

/// 與 `PROMPT_PROVIDER_FALLBACKS` 相同：google 使用 openai 家族的模板。
fn resolve_prompt_llm_type(llm_type: &str) -> &str {
    if llm_type == "google" {
        "openai"
    } else {
        llm_type
    }
}

/// 標準化模型名稱：去空白、小寫、去掉 `@` 之後的部分。
pub fn normalize_model_name(model_name: Option<&str>) -> String {
    let Some(name) = model_name else { return String::new() };
    let lower = py::strip(name).to_lowercase();
    lower.split('@').next().unwrap_or_default().to_string()
}

fn is_qwen_ud_family_model(model_name: Option<&str>) -> bool {
    QWEN_UD_FAMILY.is_match(&normalize_model_name(model_name)).unwrap_or(false)
}

/// Qwen3.5 / Qwen3.6 的 UD 變體。
pub fn is_qwen_ud_model(model_name: Option<&str>) -> bool {
    let normalized = normalize_model_name(model_name);
    if normalized.is_empty() || !is_qwen_ud_family_model(Some(&normalized)) {
        return false;
    }
    normalized.split(|c: char| !(c.is_ascii_lowercase() || c.is_ascii_digit())).any(|t| t == "ud")
}

pub fn is_hunyuan_mt_model(model_name: Option<&str>) -> bool {
    HUNYUAN_MT.is_match(&normalize_model_name(model_name)).unwrap_or(false)
}

fn is_batch_translation_request(text: &str) -> bool {
    py::lstrip(text).starts_with("[BATCH:")
}

fn compact_prompt_text(content_type: &str) -> String {
    COMPACT_BASE_RULES
        .iter()
        .chain(compact_content_rules(content_type))
        .enumerate()
        .map(|(i, rule)| format!("{}. {rule}", i + 1))
        .collect::<Vec<_>>()
        .join("\n")
}

fn language_pair(pair: &str) -> Option<(&'static str, &'static str)> {
    LANGUAGE_PAIRS.iter().find(|(name, _, _)| *name == pair).map(|(_, s, t)| (*s, *t))
}

fn hunyuan_names(lang: &str) -> (String, String) {
    HUNYUAN_LANG_NAMES
        .iter()
        .find(|(zh, _, _)| *zh == lang)
        .map_or_else(|| (lang.to_string(), lang.to_string()), |(_, en, display)| (en.to_string(), display.to_string()))
}

fn contains_adult_action_markers(text: &str) -> bool {
    let compact: String = text.chars().filter(|c| !py::is_space(*c)).collect();
    QWEN35_UD_ADULT_ACTION_MARKERS.iter().any(|m| compact.contains(m))
}

fn is_qwen35_ud_short_cache_candidate(text: &str) -> bool {
    if text.contains('\n') {
        return false;
    }
    let normalized = SHORT_CACHE_STRIP.replace_all(text, "");
    if normalized.is_empty() || py::len(&normalized) > 8 {
        return false;
    }
    KANA_ONLY.is_match(&normalized).unwrap_or(false)
}

/// 為 qwen3.5-ud 壓縮成人字幕上下文（只留前後各 1 句；短句含成人動作標記時完全捨棄）。
fn compact_qwen35_ud_context(text: &str, before: &[String], after: &[String]) -> (Vec<String>, Vec<String>) {
    let compact: String = text.chars().filter(|c| !py::is_space(*c)).collect();
    if !text.contains('\n') && py::len(&compact) <= 24 && contains_adult_action_markers(&compact) {
        return (Vec::new(), Vec::new());
    }
    (before.iter().rev().take(1).cloned().collect(), after.iter().take(1).cloned().collect())
}

fn build_qwen35_ud_user_message(text: &str, before: &[String], after: &[String]) -> String {
    let mut parts = vec!["CURRENT:".to_string(), text.to_string()];
    if !before.is_empty() || !after.is_empty() {
        parts.extend(["".into(), "REFERENCE ONLY. DO NOT TRANSLATE OR COPY.".into()]);
        if let Some(b) = before.last() {
            parts.push(format!("Before: {b}"));
        }
        if let Some(a) = after.first() {
            parts.push(format!("After: {a}"));
        }
    }
    parts.join("\n")
}

/// Python 真值判斷（None/空字串/空容器/0/False 為假）。
fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python `x or current`：`None` 與空字串都退回目前設定。
fn or_current<'a>(value: Option<&'a str>, current: &'a str) -> &'a str {
    value.filter(|v| !v.is_empty()).unwrap_or(current)
}

fn value_to_prompt(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Message {
    pub role: String,
    pub content: String,
}

impl Message {
    pub fn system(content: impl Into<String>) -> Self {
        Self { role: "system".into(), content: content.into() }
    }

    pub fn user(content: impl Into<String>) -> Self {
        Self { role: "user".into(), content: content.into() }
    }
}

pub struct PromptManager {
    config: ConfigFile,
    user_config: ConfigFile,
    templates_dir: PathBuf,
    pub current_content_type: String,
    pub current_style: String,
    pub current_language_pair: String,
    custom_prompts: Map<String, Value>,
    version_history: Map<String, Value>,
}

impl PromptManager {
    /// 以設定目錄建立（讀寫 `prompt_config.json`、`user_settings.json` 與 `prompt_templates/`）。
    pub fn open(config_dir: &Path) -> Result<Self> {
        let config = ConfigFile::load(config_dir, ConfigKind::Prompt)?;
        let user_config = ConfigFile::load(config_dir, ConfigKind::User)?;
        let templates_dir = config_dir.join("prompt_templates");
        std::fs::create_dir_all(&templates_dir).map_err(|e| Error::file(format!("無法建立模板目錄: {e}")))?;

        let mut manager = Self {
            config,
            user_config,
            templates_dir,
            current_content_type: String::new(),
            current_style: String::new(),
            current_language_pair: String::new(),
            custom_prompts: Map::new(),
            version_history: Map::new(),
        };
        manager.load_config()?;
        manager.current_content_type = manager.config_str("current_content_type", "general");
        manager.current_style = manager.config_str("current_style", "standard");
        manager.current_language_pair = manager.config_str("current_language_pair", DEFAULT_LANGUAGE_PAIR);
        manager.version_history = manager.config_object("version_history");
        manager.load_custom_prompts()?;
        Ok(manager)
    }

    fn config_str(&self, key: &str, default: &str) -> String {
        self.config.get_str(key).unwrap_or(default).to_string()
    }

    fn config_object(&self, key: &str) -> Map<String, Value> {
        self.config.get(key).and_then(Value::as_object).cloned().unwrap_or_default()
    }

    /// 確保必要鍵存在（值為假時以預設值補上）後儲存。
    fn load_config(&mut self) -> Result<()> {
        let defaults = [
            ("current_content_type", json!("general")),
            ("current_style", json!("standard")),
            ("current_language_pair", json!(DEFAULT_LANGUAGE_PAIR)),
            ("custom_prompts", json!({})),
            ("version_history", json!({})),
            ("last_updated", json!(now_isoformat())),
        ];
        for (key, value) in defaults {
            if !truthy(self.config.get(key)) {
                self.config.set(key, value);
            }
        }
        self.config.save()
    }

    /// 載入自訂 prompt，並合併 `prompt_templates/<content_type>_template.json`（設定檔優先）。
    fn load_custom_prompts(&mut self) -> Result<()> {
        self.custom_prompts = self.config_object("custom_prompts");
        for content_type in CONTENT_TYPES {
            let entry = self.custom_prompts.entry(content_type).or_insert_with(|| json!({}));
            let template_file = self.templates_dir.join(format!("{content_type}_template.json"));
            let templates = std::fs::read_to_string(&template_file)
                .ok()
                .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                .and_then(|v| v.as_object().cloned());
            if let (Some(templates), Some(existing)) = (templates, entry.as_object_mut()) {
                for (llm_type, prompt) in templates {
                    existing.entry(llm_type).or_insert(prompt);
                }
            }
        }
        self.config.set_and_save("custom_prompts", Value::Object(self.custom_prompts.clone()))
    }

    pub fn user_config_mut(&mut self) -> &mut ConfigFile {
        &mut self.user_config
    }

    fn should_use_compact_prompt(&self, llm_type: &str) -> bool {
        llm_type == "openai" && self.user_config.get_bool("translation.compact_prompt_enabled", true)
    }

    fn should_use_qwen_ud_adult_prompt(llm_type: &str, content_type: &str, model_name: Option<&str>) -> bool {
        llm_type == "llamacpp" && content_type == "adult" && is_qwen_ud_model(model_name)
    }

    /// Hunyuan-MT2 為翻譯專用模型，所有 content_type 都改走簡化單句策略。
    fn should_use_hunyuan_mt_prompt(llm_type: &str, model_name: Option<&str>) -> bool {
        llm_type == "llamacpp" && is_hunyuan_mt_model(model_name)
    }

    /// 回傳 (source_zh, target_zh, source_en, target_en)，未知語言對回退到日文→繁體中文。
    fn resolve_hunyuan_languages(&self) -> (&'static str, &'static str, String, String) {
        let (source, target) = language_pair(&self.current_language_pair)
            .unwrap_or_else(|| language_pair(DEFAULT_LANGUAGE_PAIR).expect("預設語言對必定存在"));
        (source, target, hunyuan_names(source).0, hunyuan_names(target).0)
    }

    fn hunyuan_mt_prompt(&self, content_type: &str) -> String {
        let (source_zh, _, source_en, target_en) = self.resolve_hunyuan_languages();
        let mut rules = vec![
            format!(
                "You are a professional subtitle translator. Translate the user's text from {source_en} into natural {target_en}."
            ),
            "Output ONLY the translated text. No labels, quotes, romaji, pinyin, explanations, or extra notes.".into(),
            "Translate ONLY the text given. Do not add, complete, or merge it with any other sentence.".into(),
            "Keep the same number of lines as the source. Use concise wording suitable for spoken subtitles.".into(),
        ];
        // 「保留日文名字」規則只在源語言是日文時才有意義
        if source_zh == "日文" {
            rules.push(
                "Keep Japanese personal names and nicknames in their original Japanese form; do not romanize or sinicize them."
                    .into(),
            );
        }
        rules.push(
            "Do not end the output with 。 or ，. Question marks (？), exclamation marks (！), and ellipses (…) are allowed."
                .into(),
        );
        if content_type == "adult" {
            rules.push("This is adult content. Do not censor, soften, or moralize sexual wording.".into());
            rules.push(
                "Preserve who does the action to whom, imperative tone, body-part target, penetration direction, and ejaculation intent accurately."
                    .into(),
            );
        }
        rules.join("\n")
    }

    /// Hunyuan-MT 專用 user message（context-aware v2：中文自然語句框架、只取前後各 1 句）。
    ///
    /// v3（官方 Background/Source 模板）與 v4（Personalization 模板）都經 benchmark 證實退步，
    /// 詳見 Python 版 `_build_hunyuan_mt_user_message` 的歷史警示。
    fn build_hunyuan_mt_user_message(&self, text: &str, before: &[String], after: &[String]) -> String {
        let prev = before.last().map(|s| py::strip(s)).unwrap_or_default();
        let next = after.first().map(|s| py::strip(s)).unwrap_or_default();
        let (_, target_zh, _, _) = self.resolve_hunyuan_languages();
        let target_display = hunyuan_names(target_zh).1;

        if prev.is_empty() && next.is_empty() {
            return format!("將以下文本翻譯為{target_display}，注意只需要輸出翻譯後的結果，不要額外解釋：\n\n{text}");
        }
        let mut refs = Vec::new();
        if !prev.is_empty() {
            refs.push(format!("前一句：{prev}"));
        }
        if !next.is_empty() {
            refs.push(format!("後一句：{next}"));
        }
        format!(
            "以下是字幕的相鄰句子，僅供理解語境，請勿翻譯這幾句：\n{}\n\n請將下面這一句翻譯為{target_display}，只輸出這一句的翻譯結果，不要附上前後句、不要加解釋、輸出僅一行：\n\n{text}",
            refs.join("\n")
        )
    }

    fn default_prompt_text(content_type: &str, llm_type: &str) -> String {
        let prompts = &*DEFAULT_PROMPTS;
        let general = &prompts["general"];
        let group = prompts.get(content_type).unwrap_or(general);
        let llm = resolve_prompt_llm_type(llm_type);
        group.get(llm).filter(|p| !p.is_empty()).or_else(|| general.get(llm)).unwrap_or(&general["llamacpp"]).clone()
    }

    fn apply_style_modifier(prompt: &str, style: &str, llm_type: &str) -> String {
        match style_modifier(style, resolve_prompt_llm_type(llm_type)) {
            Some(m) => format!("{prompt}\n\nAdditional instruction: {m}"),
            None => prompt.to_string(),
        }
    }

    fn apply_language_pair_modifier(prompt: &str, pair: &str) -> String {
        if pair == DEFAULT_LANGUAGE_PAIR {
            return prompt.to_string();
        }
        let Some((source, target)) = language_pair(pair) else { return prompt.to_string() };
        let replaced = LANGUAGE_REFERENCE.replace_all(prompt, NoExpand(target));
        format!(
            "{replaced}\nTranslate from {source} to {target}. Remember to ONLY translate the CURRENT text, not context."
        )
    }

    fn custom_prompt(&self, content_type: &str, llm_type: &str) -> Option<String> {
        self.custom_prompts.get(content_type)?.as_object()?.get(llm_type).map(value_to_prompt)
    }

    /// 依 LLM 類型、內容類型、風格與模型取得 system prompt。
    pub fn get_prompt(
        &self,
        llm_type: &str,
        content_type: Option<&str>,
        style: Option<&str>,
        model_name: Option<&str>,
    ) -> String {
        let content_type = or_current(content_type, &self.current_content_type);
        let style = or_current(style, &self.current_style);

        let mut prompt = if let Some(custom) = self.custom_prompt(content_type, llm_type) {
            custom
        } else if Self::should_use_hunyuan_mt_prompt(llm_type, model_name) {
            self.hunyuan_mt_prompt(content_type)
        } else if Self::should_use_qwen_ud_adult_prompt(llm_type, content_type, model_name) {
            QWEN_UD_ADULT_PROMPT.to_string()
        } else if self.should_use_compact_prompt(llm_type) {
            compact_prompt_text(content_type)
        } else {
            Self::default_prompt_text(content_type, llm_type)
        };
        if style != "standard" {
            prompt = Self::apply_style_modifier(&prompt, style, llm_type);
        }
        prompt = Self::apply_language_pair_modifier(&prompt, &self.current_language_pair);
        py::strip(&prompt).to_string()
    }

    /// 批次（structure-text）翻譯專用 prompt：一般 prompt + 嚴格行對行映射指令。
    pub fn get_batch_translation_prompt(
        &self,
        llm_type: &str,
        content_type: Option<&str>,
        style: Option<&str>,
        model_name: Option<&str>,
    ) -> String {
        let content_type = or_current(content_type, &self.current_content_type);
        let style = or_current(style, &self.current_style);
        let prompt = if self.should_use_compact_prompt(llm_type) {
            let mut p = compact_prompt_text(content_type);
            if style != "standard" {
                p = Self::apply_style_modifier(&p, style, llm_type);
            }
            Self::apply_language_pair_modifier(&p, &self.current_language_pair)
        } else {
            self.get_prompt(llm_type, Some(content_type), Some(style), model_name)
        };
        py::strip(&format!("{prompt}\n\n{BATCH_LINE_MAPPING_INSTRUCTION}")).to_string()
    }

    fn message_strategy_signature(
        &self,
        llm_type: &str,
        content_type: Option<&str>,
        model_name: Option<&str>,
    ) -> &'static str {
        let content_type = or_current(content_type, &self.current_content_type);
        if Self::should_use_hunyuan_mt_prompt(llm_type, model_name) {
            "hunyuan_mt_context_v2"
        } else if Self::should_use_qwen_ud_adult_prompt(llm_type, content_type, model_name) {
            "qwen35_ud_adult_compact_context_v3"
        } else {
            "default_structured_context_v1"
        }
    }

    /// 提示詞版本雜湊（快取鍵的一部分）：`md5(prompt + 訊息策略)` 前 8 碼。
    pub fn get_prompt_version(
        &self,
        llm_type: &str,
        content_type: Option<&str>,
        style: Option<&str>,
        model_name: Option<&str>,
        batch_request: bool,
    ) -> String {
        let content_type = or_current(content_type, &self.current_content_type);
        let prompt = if batch_request {
            self.get_batch_translation_prompt(llm_type, Some(content_type), None, model_name)
        } else {
            self.get_prompt(llm_type, Some(content_type), style, model_name)
        };
        let mut strategy = self.message_strategy_signature(llm_type, Some(content_type), model_name).to_string();
        if batch_request {
            strategy.push_str("|batch");
        }
        md5_hex(&format!("{prompt}\n\n[MESSAGE_STRATEGY]{strategy}"))[..8].to_string()
    }

    /// 解析目前字幕在上下文中的位置；優先使用 `current_index`，重複句取最接近中心者。
    fn resolve_context_index(text: &str, context: &[String], current_index: Option<usize>) -> Option<usize> {
        if let Some(i) = current_index {
            if context.get(i).is_some_and(|c| c == text) {
                return Some(i);
            }
        }
        let matches: Vec<usize> = context.iter().enumerate().filter(|(_, c)| *c == text).map(|(i, _)| i).collect();
        match matches.len() {
            0 => None,
            1 => Some(matches[0]),
            _ => {
                // 以兩倍座標比較 |idx - (len-1)/2|，避免浮點
                let twice_center = context.len() as i64 - 1;
                matches.into_iter().min_by_key(|&i| ((2 * i as i64 - twice_center).abs(), i))
            }
        }
    }

    fn split_context(
        text: &str,
        context: &[String],
        current_index: Option<usize>,
    ) -> (Vec<String>, Vec<String>, Option<usize>) {
        match Self::resolve_context_index(text, context, current_index) {
            None => (context.to_vec(), Vec::new(), None),
            Some(i) => (context[..i].to_vec(), context[i + 1..].to_vec(), Some(i)),
        }
    }

    /// 實際用於 prompt 的上下文（Qwen UD 成人字幕會被壓縮）。
    pub fn get_effective_context_texts(
        &self,
        text: &str,
        context: &[String],
        llm_type: &str,
        model_name: &str,
        current_index: Option<usize>,
    ) -> Vec<String> {
        if !Self::should_use_qwen_ud_adult_prompt(llm_type, &self.current_content_type, Some(model_name)) {
            return context.to_vec();
        }
        let (before, after, resolved) = Self::split_context(text, context, current_index);
        if resolved.is_none() {
            return context.to_vec();
        }
        let (before, after) = compact_qwen35_ud_context(text, &before, &after);
        before.into_iter().chain(std::iter::once(text.to_string())).chain(after).collect()
    }

    /// 供快取鍵使用的上下文：加上 `[CURRENT_INDEX]` 標記避免重複句碰撞；
    /// Qwen3.5 UD 的純假名短句改用寬鬆的上下文分類。
    pub fn get_effective_cache_context_texts(
        &self,
        text: &str,
        context: &[String],
        llm_type: &str,
        model_name: &str,
        current_index: Option<usize>,
    ) -> Vec<String> {
        if let Some(relaxed) =
            self.qwen35_ud_short_line_cache_context(text, context, llm_type, model_name, current_index)
        {
            return relaxed;
        }
        let effective = self.get_effective_context_texts(text, context, llm_type, model_name, current_index);
        match Self::resolve_context_index(text, context, current_index) {
            None => effective,
            Some(i) => std::iter::once(format!("[CURRENT_INDEX]{i}")).chain(effective).collect(),
        }
    }

    fn qwen35_ud_short_line_cache_context(
        &self,
        text: &str,
        context: &[String],
        llm_type: &str,
        model_name: &str,
        current_index: Option<usize>,
    ) -> Option<Vec<String>> {
        if !Self::should_use_qwen_ud_adult_prompt(llm_type, &self.current_content_type, Some(model_name))
            || !is_qwen35_ud_short_cache_candidate(text)
        {
            return None;
        }
        let (before, after, _) = Self::split_context(text, context, current_index);
        let nearby: Vec<&String> = before.last().into_iter().chain(after.first()).collect();
        let mut classes = Vec::new();
        if nearby.iter().any(|c| contains_adult_action_markers(c)) {
            classes.push("adult_action_nearby");
        }
        if nearby.iter().any(|c| c.contains('?') || c.contains('？')) {
            classes.push("question_nearby");
        }
        if classes.is_empty() {
            classes.push("plain");
        }
        Some(vec!["[CACHE_MODE]qwen35_ud_short_utterance_v1".into(), format!("[CONTEXT_CLASS]{}", classes.join("+"))])
    }

    /// 產生送給模型的訊息（system + user），依 provider/模型套用對應的 user message 結構。
    pub fn get_optimized_message(
        &self,
        text: &str,
        context: &[String],
        llm_type: &str,
        model_name: &str,
        current_index: Option<usize>,
    ) -> Vec<Message> {
        let content_type = self.current_content_type.as_str();
        let model = Some(model_name);
        if is_batch_translation_request(text) {
            let prompt = self.get_batch_translation_prompt(llm_type, Some(content_type), None, model);
            return vec![Message::system(prompt), Message::user(text)];
        }

        let prompt = self.get_prompt(llm_type, None, None, model);
        let (mut before, mut after, resolved) = Self::split_context(text, context, current_index);
        if resolved.is_none() {
            before = context.to_vec();
            after = Vec::new();
        }

        if Self::should_use_hunyuan_mt_prompt(llm_type, model) {
            let user = self.build_hunyuan_mt_user_message(text, &before, &after);
            return vec![Message::system(prompt), Message::user(user)];
        }

        let use_qwen_ud = Self::should_use_qwen_ud_adult_prompt(llm_type, content_type, model);
        if use_qwen_ud {
            (before, after) = compact_qwen35_ud_context(text, &before, &after);
        }

        let text_lower = py::strip(text).to_lowercase();
        let detected_conj = CONJUNCTIONS.iter().find(|c| text_lower.ends_with(&format!(" {c}")));
        let incomplete = INCOMPLETE_ENDINGS.iter().any(|e| py::strip(text).ends_with(e));

        let user = if use_qwen_ud {
            build_qwen35_ud_user_message(text, &before, &after)
        } else if self.should_use_compact_prompt(llm_type) {
            let mut parts = vec!["CURRENT:".to_string(), text.to_string()];
            if let Some(conj) = detected_conj {
                parts.extend(["".into(), format!("NOTE: preserve the trailing conjunction '{conj}' in translation.")]);
            }
            if incomplete {
                parts.extend([
                    "".into(),
                    "NOTE: CURRENT is an incomplete subtitle fragment. Translate only CURRENT; do not complete it with AFTER."
                        .into(),
                ]);
            }
            if !before.is_empty() {
                parts.extend(["".into(), "BEFORE (reference only):".into()]);
                parts.extend(before.iter().cloned());
            }
            if !after.is_empty() {
                parts.extend(["".into(), "AFTER (reference only):".into()]);
                parts.extend(after.iter().cloned());
            }
            parts.join("\n")
        } else {
            let mut parts: Vec<String> = Vec::new();
            if let Some(conj) = detected_conj {
                let upper = conj.to_uppercase();
                parts.extend([
                    "🚨 **MANDATORY WARNING** 🚨".into(),
                    format!("The [CURRENT] sentence ends with the conjunction '{upper}'."),
                    format!("YOU **MUST** PRESERVE '{upper}' in your translation."),
                    "DO NOT remove it. DO NOT omit it. DO NOT \"complete\" the sentence.".into(),
                    "Keep the translation incomplete, matching the original structure.".into(),
                    "".into(),
                    "---".into(),
                    "".into(),
                ]);
            }
            parts.extend(["[CURRENT] (請只翻譯這一句):".into(), text.to_string(), "".into()]);
            if !before.is_empty() {
                parts.push("[CONTEXT_BEFORE] (前文參考，不要翻譯):".into());
                parts.extend(before.iter().map(|c| format!("- {c}")));
                parts.push("".into());
            }
            if !after.is_empty() {
                parts.push("[CONTEXT_AFTER] (後文參考，不要翻譯):".into());
                parts.extend(after.iter().map(|c| format!("- {c}")));
            }
            parts.join("\n")
        };
        vec![Message::system(prompt), Message::user(user)]
    }

    fn custom_group_mut(&mut self, content_type: &str) -> &mut Map<String, Value> {
        let entry = self.custom_prompts.entry(content_type.to_string()).or_insert_with(|| json!({}));
        if !entry.is_object() {
            *entry = json!({});
        }
        entry.as_object_mut().expect("剛確認為物件")
    }

    fn save_prompt_template(&self, content_type: &str) -> Result<()> {
        let group = self.custom_prompts.get(content_type).cloned().unwrap_or_else(|| json!({}));
        let path = self.templates_dir.join(format!("{content_type}_template.json"));
        std::fs::create_dir_all(&self.templates_dir).map_err(|e| Error::file(format!("無法建立模板目錄: {e}")))?;
        std::fs::write(&path, to_json_indent4(&group)).map_err(|e| Error::file(format!("儲存模板檔案失敗: {e}")))
    }

    fn add_to_version_history(&mut self, content_type: &str, llm_type: &str, prompt: &str) -> Result<()> {
        let group = self.version_history.entry(content_type.to_string()).or_insert_with(|| json!({}));
        if !group.is_object() {
            *group = json!({});
        }
        let list =
            group.as_object_mut().expect("剛確認為物件").entry(llm_type.to_string()).or_insert_with(|| json!([]));
        if !list.is_array() {
            *list = json!([]);
        }
        let history = list.as_array_mut().expect("剛確認為陣列");
        history.push(json!({"prompt": prompt, "timestamp": now_isoformat(), "version": history.len() + 1}));
        if history.len() > 10 {
            let keep = history.split_off(history.len() - 10);
            *history = keep;
        }
        self.config.set_and_save("version_history", Value::Object(self.version_history.clone()))
    }

    /// 設定自訂 prompt（舊值進版本歷史，並寫入模板檔）。
    pub fn set_prompt(&mut self, new_prompt: &str, llm_type: &str, content_type: Option<&str>) -> Result<()> {
        let content_type = or_current(content_type, &self.current_content_type).to_string();
        let old = self.custom_group_mut(&content_type).get(llm_type).cloned();
        if truthy(old.as_ref()) {
            self.add_to_version_history(&content_type, llm_type, &value_to_prompt(&old.unwrap()))?;
        }
        self.custom_group_mut(&content_type).insert(llm_type.to_string(), py::strip(new_prompt).into());
        self.config.set_and_save("custom_prompts", Value::Object(self.custom_prompts.clone()))?;
        self.save_prompt_template(&content_type)
    }

    /// 重置為預設 prompt；`llm_type` 為 `None` 時重置該內容類型的所有 provider。
    pub fn reset_to_default(&mut self, llm_type: Option<&str>, content_type: Option<&str>) -> Result<bool> {
        let content_type = or_current(content_type, &self.current_content_type).to_string();
        if !DEFAULT_PROMPTS.contains_key(&content_type) {
            return Ok(false);
        }
        match llm_type.filter(|l| !l.is_empty()) {
            Some(llm) => {
                self.custom_group_mut(&content_type).shift_remove(llm);
            }
            None => {
                self.custom_prompts.insert(content_type.clone(), json!({}));
            }
        }
        self.config.set_and_save("custom_prompts", Value::Object(self.custom_prompts.clone()))?;
        self.save_prompt_template(&content_type)?;
        Ok(true)
    }

    pub fn set_content_type(&mut self, content_type: &str) -> Result<bool> {
        if !CONTENT_TYPES.contains(&content_type) {
            return Ok(false);
        }
        self.current_content_type = content_type.into();
        self.config.set_and_save("current_content_type", content_type.into())?;
        Ok(true)
    }

    pub fn set_translation_style(&mut self, style: &str) -> Result<bool> {
        if !TRANSLATION_STYLES.iter().any(|(s, _)| *s == style) {
            return Ok(false);
        }
        self.current_style = style.into();
        self.config.set_and_save("current_style", style.into())?;
        Ok(true)
    }

    pub fn set_language_pair(&mut self, pair: &str) -> Result<bool> {
        if language_pair(pair).is_none() {
            return Ok(false);
        }
        self.current_language_pair = pair.into();
        self.config.set_and_save("current_language_pair", pair.into())?;
        Ok(true)
    }

    /// 匯出 prompt（格式同 Python `export_prompt`）；`llm_type` 為 `None` 時匯出全部 provider。
    pub fn export_prompt(
        &self,
        content_type: Option<&str>,
        llm_type: Option<&str>,
        file_path: Option<&Path>,
    ) -> Result<PathBuf> {
        let content_type = or_current(content_type, &self.current_content_type);
        let llms: Vec<&str> = match llm_type.filter(|l| !l.is_empty()) {
            Some(l) => vec![l],
            None => SUPPORTED_LLM_TYPES.to_vec(),
        };
        let mut prompts = Map::new();
        for llm in llms {
            let text =
                self.custom_prompt(content_type, llm).unwrap_or_else(|| Self::default_prompt_text(content_type, llm));
            prompts.insert(llm.into(), text.into());
        }
        let data = json!({
            "metadata": {"exported_at": now_isoformat(), "content_type": content_type, "version": "1.0"},
            "prompts": prompts,
        });
        let path = file_path.map_or_else(
            || {
                let stamp = chrono::Local::now().format("%Y%m%d_%H%M%S");
                self.templates_dir.join(format!("prompt_export_{content_type}_{stamp}.json"))
            },
            Path::to_path_buf,
        );
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent).map_err(|e| Error::file(format!("無法建立輸出目錄: {e}")))?;
        }
        std::fs::write(&path, to_json_indent4(&data)).map_err(|e| Error::file(format!("匯出提示詞失敗: {e}")))?;
        Ok(path)
    }

    /// 匯入 `export_prompt` 格式的檔案，略過不支援的 provider。
    pub fn import_prompt(&mut self, input_path: &Path) -> Result<()> {
        let text = std::fs::read_to_string(input_path)
            .map_err(|e| Error::file(format!("匯入檔案不存在: {} ({e})", input_path.display())))?;
        let data: Value = serde_json::from_str(&text).map_err(|e| Error::file(format!("匯入檔案格式錯誤: {e}")))?;
        let (Some(metadata), Some(prompts)) = (data.get("metadata"), data.get("prompts").and_then(Value::as_object))
        else {
            return Err(Error::file(format!("無效的提示詞匯入格式: {}", input_path.display())));
        };
        let content_type = metadata.get("content_type").and_then(Value::as_str).unwrap_or("general").to_string();
        for (llm, prompt) in prompts {
            if SUPPORTED_LLM_TYPES.contains(&llm.as_str()) {
                self.set_prompt(&value_to_prompt(prompt), llm, Some(&content_type))?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn model_detection() {
        assert!(is_hunyuan_mt_model(Some("Hy-MT2-7B-Q4_K_M.gguf")));
        assert!(is_hunyuan_mt_model(Some("hunyuan_mt-1.8b")));
        assert!(is_qwen_ud_model(Some("Qwen3.6-27B-UD-Q4_K_XL")));
        assert!(!is_qwen_ud_model(Some("qwen3.5-9b")));
        assert!(!is_qwen_ud_model(Some("qwen3-ud")));
        assert_eq!(normalize_model_name(Some(" Model@Q4 ")), "model");
    }

    #[test]
    fn context_index_prefers_center_then_lower() {
        let ctx: Vec<String> = ["a", "x", "a", "y", "a"].iter().map(|s| s.to_string()).collect();
        assert_eq!(PromptManager::resolve_context_index("a", &ctx, None), Some(2));
        let ctx: Vec<String> = ["a", "a"].iter().map(|s| s.to_string()).collect();
        assert_eq!(PromptManager::resolve_context_index("a", &ctx, None), Some(0));
        assert_eq!(PromptManager::resolve_context_index("a", &ctx, Some(1)), Some(1));
    }

    #[test]
    fn default_prompts_are_embedded() {
        for ct in CONTENT_TYPES {
            assert!(!PromptManager::default_prompt_text(ct, "llamacpp").is_empty());
            assert!(!PromptManager::default_prompt_text(ct, "google").is_empty());
        }
    }
}
