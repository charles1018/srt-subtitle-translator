//! 設定檔管理（對等 Python `core/config.py`），與 Python 版共用 `config/*.json`。
//!
//! 行為對齊重點：
//! - 載入時以預設值為底遞迴合併檔案內容；檔案不存在時寫出預設值
//! - 以點號路徑讀寫（`translation.batch_size`）
//! - 寫出格式為 `json.dump(indent=4, ensure_ascii=False)`
//!
//! 未移植：備份/匯出/匯入/listener（Python 版在正式流程中沒有呼叫端）。

use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use fancy_regex::Regex;
use indexmap::IndexMap;
use serde::Serialize;
use serde_json::{json, Map, Value};

use crate::error::{Details, Error, Result};
use crate::py;

/// 與 Python 版 `version.py` 的 `APP_VERSION` 一致，讓兩版寫出的 app_config 相同。
pub const APP_VERSION: &str = "1.3.0";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ConfigKind {
    App,
    User,
    Model,
    Prompt,
    File,
    Cache,
    Theme,
}

impl ConfigKind {
    pub const ALL: [Self; 7] = [Self::App, Self::User, Self::Model, Self::Prompt, Self::File, Self::Cache, Self::Theme];

    pub fn name(self) -> &'static str {
        match self {
            Self::App => "app",
            Self::User => "user",
            Self::Model => "model",
            Self::Prompt => "prompt",
            Self::File => "file",
            Self::Cache => "cache",
            Self::Theme => "theme",
        }
    }

    pub fn file_name(self) -> &'static str {
        match self {
            Self::App => "app_config.json",
            Self::User => "user_settings.json",
            Self::Model => "model_config.json",
            Self::Prompt => "prompt_config.json",
            Self::File => "file_handler_config.json",
            Self::Cache => "cache_config.json",
            Self::Theme => "theme_settings.json",
        }
    }

    pub fn parse(name: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|k| k.name() == name)
    }

    /// 預設設定值，內容與順序逐項對齊 Python `_get_default_configs`。
    pub fn defaults(self) -> Map<String, Value> {
        let value = match self {
            Self::App => json!({
                "version": APP_VERSION,
                "debug_mode": false,
                "data_dir": "data",
                "logs_dir": "logs",
                "cache_expiry": 30,
                "last_update": now_isoformat(),
            }),
            Self::User => json!({
                "source_lang": "英文",
                "target_lang": "繁體中文",
                "llm_type": "llamacpp",
                "model_name": "",
                "parallel_requests": 3,
                "display_mode": "僅顯示翻譯",
                "theme": "default",
                "play_sound": true,
                "auto_save": true,
                "last_directory": "",
                "translation": {
                    "batch_size": 10,
                    "max_context_items": 3,
                    "smart_context_enabled": true,
                    "compact_prompt_enabled": true,
                    "terminology_enabled": true,
                },
            }),
            Self::Model => json!({
                "llamacpp_url": "http://localhost:8080",
                "cache_expiry": 600,
                "connect_timeout": 5,
                "request_timeout": 10,
                "model_patterns": [
                    "llama", "qwen", "gemma", "mistral", "mixtral", "deepseek", "phi", "aya", "yi", "solar",
                    "openchat", "neural", "stable", "dolphin", "vicuna", "zephyr", "command-r", "glm",
                ],
                "default_providers": ["llamacpp", "openai"],
                "translation_capability_weight": {"translation": 0.7, "multilingual": 0.2, "context_handling": 0.1},
            }),
            Self::Prompt => json!({
                "current_content_type": "general",
                "current_style": "standard",
                "current_language_pair": "日文→繁體中文",
                "custom_prompts": {},
                "version_history": {},
            }),
            Self::File => json!({
                "lang_suffix": {
                    "繁體中文": ".zh_tw",
                    "簡體中文": ".zh_cn",
                    "英文": ".en",
                    "日文": ".jp",
                    "韓文": ".kr",
                    "法文": ".fr",
                    "德文": ".de",
                    "西班牙文": ".es",
                    "俄文": ".ru",
                },
                "supported_formats": [
                    [".srt", "SRT字幕檔"],
                    [".vtt", "WebVTT字幕檔"],
                    [".ass", "ASS字幕檔"],
                    [".ssa", "SSA字幕檔"],
                    [".sub", "SUB字幕檔"],
                ],
                "batch_settings": {
                    "name_pattern": "{filename}_{language}{ext}",
                    "overwrite_mode": "ask",
                    "output_directory": "",
                    "preserve_folder_structure": true,
                },
            }),
            Self::Cache => {
                json!({"db_path": "data/translation_cache.db", "max_memory_cache": 1000, "auto_cleanup_days": 30})
            }
            Self::Theme => json!({
                "colors": {
                    "primary": "#7DCFFF",
                    "secondary": "#89DDFF",
                    "background": "#1A1B26",
                    "surface": "#24283B",
                    "surface_elevated": "#2A2E42",
                    "text": "#C0CAF5",
                    "text_muted": "#565F89",
                    "accent": "#BB9AF7",
                    "border": "#3B4261",
                    "success": "#9ECE6A",
                    "success_hover": "#73C936",
                    "danger": "#F7768E",
                    "danger_hover": "#FF6B81",
                    "warning": "#E0AF68",
                    "button": "#7AA2F7",
                    "button_hover": "#5D8BF7",
                    "muted": "#565F89",
                    "highlight": "#414868",
                },
                "font_size": "medium",
                "font_family": "Default",
                "theme": "arctic_night",
            }),
        };
        match value {
            Value::Object(map) => map,
            _ => unreachable!("預設值必定為物件"),
        }
    }
}

/// Python `datetime.now().isoformat()`（本地時間、無時區、微秒）。
pub fn now_isoformat() -> String {
    chrono::Local::now().naive_local().format("%Y-%m-%dT%H:%M:%S%.6f").to_string()
}

/// 設定目錄：明確指定 > 環境變數 `CONFIG_DIR` > `config`。
pub fn resolve_config_dir(explicit: Option<&Path>) -> PathBuf {
    if let Some(dir) = explicit {
        return dir.to_path_buf();
    }
    match std::env::var("CONFIG_DIR") {
        Ok(v) if !py::strip(&v).is_empty() => PathBuf::from(py::strip(&v)),
        _ => PathBuf::from("config"),
    }
}

/// 遞迴合併：兩邊都是物件時往下合併，否則以 override 覆蓋（新鍵附加在後）。
pub fn merge_into(base: &mut Map<String, Value>, overrides: &Map<String, Value>) {
    for (key, value) in overrides {
        match (base.get_mut(key), value) {
            (Some(Value::Object(b)), Value::Object(o)) => merge_into(b, o),
            _ => {
                base.insert(key.clone(), value.clone());
            }
        }
    }
}

/// 以 4 空白縮排序列化（對等 `json.dump(indent=4, ensure_ascii=False)`）。
pub fn to_json_indent4<T: Serialize>(value: &T) -> String {
    let mut buf = Vec::new();
    let formatter = serde_json::ser::PrettyFormatter::with_indent(b"    ");
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, formatter);
    value.serialize(&mut ser).expect("JSON 序列化不會失敗");
    String::from_utf8(buf).expect("serde_json 輸出必為 UTF-8")
}

/// 單一設定檔。
#[derive(Debug, Clone)]
pub struct ConfigFile {
    pub kind: ConfigKind,
    pub path: PathBuf,
    pub data: Map<String, Value>,
}

impl ConfigFile {
    /// 載入設定；檔案不存在時寫出預設值，格式錯誤時退回預設值（不覆寫原檔）。
    pub fn load(dir: &Path, kind: ConfigKind) -> Result<Self> {
        Self::load_from(dir.join(kind.file_name()), kind)
    }

    pub fn load_from(path: PathBuf, kind: ConfigKind) -> Result<Self> {
        let mut data = kind.defaults();
        if path.exists() {
            let parsed = std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok());
            if let Some(Value::Object(loaded)) = parsed {
                merge_into(&mut data, &loaded);
            }
            Ok(Self { kind, path, data })
        } else {
            let mut file = Self { kind, path, data };
            file.save()?;
            Ok(file)
        }
    }

    /// 點號路徑取值；中途不是物件或鍵不存在時回傳 `None`。
    pub fn get(&self, key: &str) -> Option<&Value> {
        let mut parts = key.split('.');
        let mut current = self.data.get(parts.next()?)?;
        for part in parts {
            current = current.as_object()?.get(part)?;
        }
        Some(current)
    }

    pub fn get_str(&self, key: &str) -> Option<&str> {
        self.get(key).and_then(Value::as_str)
    }

    /// 只接受 JSON 布林值，其餘回傳預設值（對等 `value if isinstance(value, bool) else default`）。
    pub fn get_bool(&self, key: &str, default: bool) -> bool {
        self.get(key).and_then(Value::as_bool).unwrap_or(default)
    }

    pub fn get_i64(&self, key: &str) -> Option<i64> {
        self.get(key).and_then(py_int)
    }

    /// 點號路徑設值，中間節點不存在或不是物件時以空物件取代。
    pub fn set(&mut self, key: &str, value: Value) {
        let parts: Vec<&str> = key.split('.').collect();
        let (last, parents) = parts.split_last().expect("split 至少回傳一段");
        let mut node = &mut self.data;
        for part in parents {
            let entry = node.entry(part.to_string()).or_insert_with(|| Value::Object(Map::new()));
            if !entry.is_object() {
                *entry = Value::Object(Map::new());
            }
            node = entry.as_object_mut().expect("剛確認為物件");
        }
        node.insert(last.to_string(), value);
    }

    pub fn set_and_save(&mut self, key: &str, value: Value) -> Result<()> {
        self.set(key, value);
        self.save()
    }

    /// 寫出檔案；含 `last_update` 鍵時更新為現在時間。
    pub fn save(&mut self) -> Result<()> {
        if self.data.contains_key("last_update") {
            self.data.insert("last_update".into(), now_isoformat().into());
        }
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| config_error(&self.path, e))?;
        }
        std::fs::write(&self.path, to_json_indent4(&self.data)).map_err(|e| config_error(&self.path, e))
    }

    pub fn reset_to_default(&mut self) -> Result<()> {
        self.data = self.kind.defaults();
        self.save()
    }

    /// 驗證設定，回傳 `{設定路徑: [錯誤訊息]}`，空表示通過。
    pub fn validate(&self) -> IndexMap<String, Vec<String>> {
        validate(self.kind, &self.data)
    }
}

fn config_error(path: &Path, e: std::io::Error) -> Error {
    let mut details = Details::new();
    details.insert("error".into(), e.to_string().into());
    Error::Config { message: format!("儲存配置失敗 {}", path.display()), details }
}

/// Python `isinstance(v, int)`：整數或布林值。
fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64(),
        Value::Bool(b) => Some(i64::from(*b)),
        _ => None,
    }
}

fn get<'a>(config: &'a Map<String, Value>, key: &str) -> &'a Value {
    config.get(key).unwrap_or(&Value::Null)
}

fn str_in(v: &Value, options: &[&str]) -> bool {
    v.as_str().is_some_and(|s| options.contains(&s))
}

static VERSION_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\d+\.\d+\.\d+$").unwrap());
static COLOR_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^#[0-9A-Fa-f]{6}$").unwrap());

/// 驗證規則逐項對齊 Python `_validate_*_config`。
pub fn validate(kind: ConfigKind, c: &Map<String, Value>) -> IndexMap<String, Vec<String>> {
    let mut errors: IndexMap<String, Vec<String>> = IndexMap::new();
    let mut err = |key: &str, msg: String| {
        errors.insert(key.to_string(), vec![msg]);
    };
    let positive_int = |v: &Value| py_int(v).is_some_and(|i| i > 0);

    match kind {
        ConfigKind::App => {
            if !get(c, "version").as_str().is_some_and(|v| VERSION_RE.is_match(v).unwrap_or(false)) {
                err("version", "版本號必須符合 'x.y.z' 格式".into());
            }
            for key in ["data_dir", "logs_dir"] {
                if get(c, key).as_str().is_none_or(str::is_empty) {
                    err(key, "必須為有效的目錄路徑".into());
                }
            }
            if !positive_int(get(c, "cache_expiry")) {
                err("cache_expiry", "快取過期時間必須為正整數".into());
            }
        }
        ConfigKind::User => {
            const LANGS: [&str; 8] = ["日文", "英文", "韓文", "繁體中文", "法文", "德文", "西班牙文", "俄文"];
            if !str_in(get(c, "source_lang"), &LANGS) {
                err("source_lang", format!("無效的來源語言，有效選項: {}", LANGS.join(", ")));
            }
            if !str_in(get(c, "target_lang"), &LANGS) {
                err("target_lang", format!("無效的目標語言，有效選項: {}", LANGS.join(", ")));
            }
            if !str_in(get(c, "llm_type"), &["openai", "google", "llamacpp"]) {
                err("llm_type", "無效的 LLM 類型，有效選項: openai, google, llamacpp".into());
            }
            if !py_int(get(c, "parallel_requests")).is_some_and(|p| (1..=50).contains(&p)) {
                err("parallel_requests", "並行請求數必須為 1-50 的整數".into());
            }
            const MODES: [&str; 4] = ["雙語對照", "僅顯示翻譯", "翻譯在上", "原文在上"];
            if !str_in(get(c, "display_mode"), &MODES) {
                err("display_mode", format!("無效的顯示模式，有效選項: {}", MODES.join(", ")));
            }
        }
        ConfigKind::Model => {
            if !get(c, "llamacpp_url").as_str().is_some_and(|u| u.starts_with("http://") || u.starts_with("https://")) {
                err("llamacpp_url", "必須為有效的 HTTP/HTTPS URL".into());
            }
            for key in ["connect_timeout", "request_timeout"] {
                if !py_int(get(c, key)).is_some_and(|t| (1..=300).contains(&t)) {
                    err(key, "逾時設定必須為 1-300 的整數（秒）".into());
                }
            }
            let patterns = c.get("model_patterns").cloned().unwrap_or(json!([]));
            if !patterns.as_array().is_some_and(|a| a.iter().all(Value::is_string)) {
                err("model_patterns", "必須為字串列表".into());
            }
            match c.get("translation_capability_weight").cloned().unwrap_or(json!({})) {
                Value::Object(weights) => {
                    let all_int = weights.values().all(|v| py_int(v).is_some());
                    let total: f64 = weights.values().filter_map(Value::as_f64).sum();
                    if (total - 1.0).abs() > 0.01 {
                        let shown = if all_int { format!("{}", total as i64) } else { py::float_repr(total) };
                        err("translation_capability_weight", format!("權重總和必須為 1.0，目前為 {shown}"));
                    }
                }
                _ => err("translation_capability_weight", "必須為字典格式".into()),
            }
        }
        ConfigKind::Prompt => {
            if !str_in(get(c, "current_content_type"), &["general", "adult", "anime", "movie", "english_drama"]) {
                err(
                    "current_content_type",
                    "無效的內容類型，有效選項: general, adult, anime, movie, english_drama".into(),
                );
            }
            if !str_in(get(c, "current_style"), &["standard", "literal", "localized", "specialized"]) {
                err("current_style", "無效的翻譯風格，有效選項: standard, literal, localized, specialized".into());
            }
            const PAIRS: [&str; 8] = [
                "日文→繁體中文",
                "英文→繁體中文",
                "繁體中文→英文",
                "韓文→繁體中文",
                "法文→繁體中文",
                "德文→繁體中文",
                "西班牙文→繁體中文",
                "俄文→繁體中文",
            ];
            if !str_in(get(c, "current_language_pair"), &PAIRS) {
                err("current_language_pair", format!("無效的語言對，有效選項: {}", PAIRS.join(", ")));
            }
            match c.get("custom_prompts").cloned().unwrap_or(json!({})) {
                Value::Object(prompts) => {
                    for (content_type, p) in &prompts {
                        if !p.is_object() {
                            err(&format!("custom_prompts.{content_type}"), "必須為字典格式".into());
                        }
                    }
                }
                _ => err("custom_prompts", "必須為字典格式".into()),
            }
        }
        ConfigKind::File => {
            match c.get("lang_suffix").cloned().unwrap_or(json!({})) {
                Value::Object(suffixes) => {
                    for (lang, suffix) in &suffixes {
                        if !suffix.as_str().is_some_and(|s| s.starts_with('.')) {
                            err(&format!("lang_suffix.{lang}"), "後綴必須為字串並以 '.' 開頭".into());
                        }
                    }
                }
                _ => err("lang_suffix", "必須為字典格式".into()),
            }
            match c.get("supported_formats").cloned().unwrap_or(json!([])) {
                Value::Array(formats) => {
                    for (i, fmt) in formats.iter().enumerate() {
                        let ok = fmt.as_array().is_some_and(|f| f.len() == 2 && f.iter().all(Value::is_string));
                        if !ok {
                            err(&format!("supported_formats[{i}]"), "必須為 (副檔名, 描述) 的二元組".into());
                        }
                    }
                }
                _ => err("supported_formats", "必須為列表格式".into()),
            }
            match c.get("batch_settings").cloned().unwrap_or(json!({})) {
                Value::Object(batch) => {
                    if let Some(pattern) = batch.get("name_pattern") {
                        let ok = pattern
                            .as_str()
                            .is_some_and(|p| ["{filename}", "{language}", "{ext}"].iter().any(|x| p.contains(x)));
                        if !ok {
                            err(
                                "batch_settings.name_pattern",
                                "必須包含至少一個 {filename}, {language}, {ext} 預留位置".into(),
                            );
                        }
                    }
                    if let Some(mode) = batch.get("overwrite_mode") {
                        if !str_in(mode, &["ask", "overwrite", "rename", "skip"]) {
                            err("batch_settings.overwrite_mode", "必須為 ask, overwrite, rename, skip 其中之一".into());
                        }
                    }
                }
                _ => err("batch_settings", "必須為字典格式".into()),
            }
        }
        ConfigKind::Cache => {
            if get(c, "db_path").as_str().is_none_or(str::is_empty) {
                err("db_path", "必須為有效的檔案路徑".into());
            }
            if !positive_int(get(c, "max_memory_cache")) {
                err("max_memory_cache", "必須為正整數".into());
            }
            if !positive_int(get(c, "auto_cleanup_days")) {
                err("auto_cleanup_days", "必須為正整數".into());
            }
        }
        ConfigKind::Theme => {
            match c.get("colors").cloned().unwrap_or(json!({})) {
                Value::Object(colors) => {
                    for (key, color) in &colors {
                        if !color.as_str().is_some_and(|s| COLOR_RE.is_match(s).unwrap_or(false)) {
                            err(&format!("colors.{key}"), "必須為有效的十六進位色碼 (#RRGGBB)".into());
                        }
                    }
                }
                _ => err("colors", "必須為字典格式".into()),
            }
            if !str_in(get(c, "font_size"), &["small", "medium", "large"]) {
                err("font_size", "必須為 small, medium, large 其中之一".into());
            }
        }
    }
    errors
}

/// 全部設定檔的集合。
#[derive(Debug, Clone)]
pub struct ConfigStore {
    pub dir: PathBuf,
    files: Vec<ConfigFile>,
}

impl ConfigStore {
    /// 載入目錄下全部 7 種設定（不存在者以預設值建立）。
    pub fn open(dir: impl Into<PathBuf>) -> Result<Self> {
        let dir = dir.into();
        let files = ConfigKind::ALL.into_iter().map(|k| ConfigFile::load(&dir, k)).collect::<Result<Vec<_>>>()?;
        Ok(Self { dir, files })
    }

    pub fn file(&self, kind: ConfigKind) -> &ConfigFile {
        self.files.iter().find(|f| f.kind == kind).expect("ALL 涵蓋所有種類")
    }

    pub fn file_mut(&mut self, kind: ConfigKind) -> &mut ConfigFile {
        self.files.iter_mut().find(|f| f.kind == kind).expect("ALL 涵蓋所有種類")
    }

    pub fn get(&self, kind: ConfigKind, key: &str) -> Option<&Value> {
        self.file(kind).get(key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_file_is_created_with_defaults() {
        let dir = tempfile::tempdir().unwrap();
        let f = ConfigFile::load(dir.path(), ConfigKind::User).unwrap();
        assert!(dir.path().join("user_settings.json").exists());
        assert_eq!(f.get_i64("translation.batch_size"), Some(10));
        assert!(f.validate().is_empty());
    }

    #[test]
    fn merge_keeps_defaults_and_overrides() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(
            dir.path().join("user_settings.json"),
            r#"{"llm_type": "openai", "translation": {"batch_size": 5}, "extra": 1}"#,
        )
        .unwrap();
        let f = ConfigFile::load(dir.path(), ConfigKind::User).unwrap();
        assert_eq!(f.get_str("llm_type"), Some("openai"));
        assert_eq!(f.get_i64("translation.batch_size"), Some(5));
        assert_eq!(f.get_i64("translation.max_context_items"), Some(3));
        assert_eq!(f.data.keys().next_back().unwrap(), "extra");
    }

    #[test]
    fn invalid_json_falls_back_without_overwriting() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("cache_config.json");
        std::fs::write(&path, "[1, 2").unwrap();
        let f = ConfigFile::load(dir.path(), ConfigKind::Cache).unwrap();
        assert_eq!(f.get_str("db_path"), Some("data/translation_cache.db"));
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "[1, 2");
    }

    #[test]
    fn set_creates_intermediate_objects() {
        let dir = tempfile::tempdir().unwrap();
        let mut f = ConfigFile::load(dir.path(), ConfigKind::User).unwrap();
        f.set("llm_type.nested", json!(1));
        assert_eq!(f.get_i64("llm_type.nested"), Some(1));
        assert!(f.get("theme.colors").is_none());
    }

    #[test]
    fn validation_messages() {
        let mut c = ConfigKind::User.defaults();
        c.insert("parallel_requests".into(), json!(0));
        c.insert("llm_type".into(), json!("ollama"));
        let e = validate(ConfigKind::User, &c);
        assert_eq!(e.keys().collect::<Vec<_>>(), vec!["llm_type", "parallel_requests"]);
    }
}
