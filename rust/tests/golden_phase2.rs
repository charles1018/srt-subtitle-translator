//! 階段 2 golden parity：config / cache / prompt 與 Python 版逐項比對。

use std::io::Read;
use std::path::PathBuf;

use serde_json::Value;
use srt_translator::cache::{compute_context_hash, md5_hex, CacheKey, CacheManager};
use srt_translator::config::{to_json_indent4, ConfigFile, ConfigKind};
use srt_translator::prompt::PromptManager;

fn golden_path(rel: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden").join(rel)
}

fn load(rel: &str) -> Value {
    let raw = std::fs::read(golden_path(rel)).unwrap_or_else(|e| panic!("讀取 {rel} 失敗: {e}"));
    let text = if rel.ends_with(".gz") {
        let mut s = String::new();
        flate2::read::GzDecoder::new(&raw[..]).read_to_string(&mut s).unwrap();
        s
    } else {
        String::from_utf8(raw).unwrap()
    };
    serde_json::from_str(&text).unwrap()
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or_else(|| panic!("預期字串: {v}"))
}

fn strings(v: &Value) -> Vec<String> {
    serde_json::from_value(v.clone()).unwrap()
}

struct Mismatches(Vec<String>);

impl Mismatches {
    fn check<T: PartialEq + std::fmt::Debug>(&mut self, label: impl std::fmt::Display, actual: T, expected: T) {
        if actual != expected {
            self.0.push(format!("{label}\n    rust:   {actual:?}\n    python: {expected:?}"));
        }
    }

    fn assert_empty(self, what: &str) {
        if !self.0.is_empty() {
            let shown: Vec<_> = self.0.iter().take(10).cloned().collect();
            panic!("{what}: {} 項不一致\n{}", self.0.len(), shown.join("\n"));
        }
    }
}

#[test]
fn config_defaults_match_python_files() {
    let golden = load("config.json");
    let dir = tempfile::tempdir().unwrap();
    let mut m = Mismatches(Vec::new());
    for kind in ConfigKind::ALL {
        let mut file = ConfigFile::load(dir.path(), kind).unwrap();
        let text = if kind == ConfigKind::App {
            file.data.insert("last_update".into(), "FIXED".into());
            to_json_indent4(&file.data)
        } else {
            std::fs::read_to_string(dir.path().join(kind.file_name())).unwrap()
        };
        m.check(kind.file_name(), text.as_str(), s(&golden[kind.file_name()]));
    }
    let mut user = ConfigFile::load(dir.path(), ConfigKind::User).unwrap();
    user.set_and_save("translation.batch_size", 5.into()).unwrap();
    user.set_and_save("llm_type.nested", 1.into()).unwrap();
    m.check(
        "user_after_set",
        std::fs::read_to_string(dir.path().join("user_settings.json")).unwrap().as_str(),
        s(&golden["user_after_set"]),
    );
    m.assert_empty("config");
}

#[test]
fn cache_is_compatible_with_python() {
    let golden = load("cache.json");
    let mut m = Mismatches(Vec::new());
    for case in golden["hashes"].as_array().unwrap() {
        let ctx = strings(&case["context"]);
        m.check(format!("hash {ctx:?}"), compute_context_hash(&ctx).as_str(), s(&case["hash"]));
    }

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("c.db");
    let cache = CacheManager::open(&path, 1000, 30).unwrap();
    let context = strings(&golden["hashes"][2]["context"]);
    cache.store(CacheKey::new("こんにちは", "model-x", "standard", "abcd1234"), "你好", &context);
    drop(cache);

    let conn = rusqlite::Connection::open(&path).unwrap();
    let mut stmt = conn.prepare("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL").unwrap();
    let mut schema: Vec<String> = stmt.query_map([], |r| r.get(0)).unwrap().map(Result::unwrap).collect();
    schema.sort();
    m.check("schema", schema, strings(&golden["schema"]));
    let row: Vec<Value> = conn
        .query_row(
            "SELECT source_text, target_text, context_hash, model_name, style, prompt_version, usage_count FROM translations",
            [],
            |r| {
                Ok((0..6)
                    .map(|i| Value::from(r.get::<_, String>(i).unwrap()))
                    .chain(std::iter::once(Value::from(r.get::<_, i64>(6).unwrap())))
                    .collect())
            },
        )
        .unwrap();
    m.check("row", Value::from(row), golden["rows"][0].clone());
    m.assert_empty("cache");
}

fn manager(dir: &std::path::Path, language_pair: &str, compact: bool) -> PromptManager {
    let mut pm = PromptManager::open(dir).unwrap();
    pm.user_config_mut().set_and_save("translation.compact_prompt_enabled", compact.into()).unwrap();
    pm.set_language_pair(language_pair).unwrap();
    pm
}

#[test]
fn prompts_and_versions_match_python() {
    let golden = load("prompt.json.gz");
    let texts = golden["texts"].as_object().unwrap();
    let mut m = Mismatches(Vec::new());
    let mut current: Option<(String, bool, tempfile::TempDir, PromptManager)> = None;

    for case in golden["cases"].as_array().unwrap() {
        let (pair, compact) = (s(&case["language_pair"]), case["compact"].as_bool().unwrap());
        if current.as_ref().is_none_or(|(p, c, _, _)| p != pair || *c != compact) {
            let dir = tempfile::tempdir().unwrap();
            let pm = manager(dir.path(), pair, compact);
            current = Some((pair.to_string(), compact, dir, pm));
        }
        let pm = &mut current.as_mut().unwrap().3;
        pm.set_content_type(s(&case["content_type"])).unwrap();
        pm.set_translation_style(s(&case["style"])).unwrap();
        let (llm, model) = (s(&case["llm_type"]), s(&case["model"]));
        let label = format!("{pair} compact={compact} {} {} {llm} {model:?}", case["content_type"], case["style"]);

        let prompt = pm.get_prompt(llm, None, None, Some(model));
        if md5_hex(&prompt) != s(&case["prompt"]) {
            m.check(format!("prompt {label}"), prompt.as_str(), s(&texts[s(&case["prompt"])]));
        }
        let batch = pm.get_batch_translation_prompt(llm, None, None, Some(model));
        if md5_hex(&batch) != s(&case["batch_prompt"]) {
            m.check(format!("batch_prompt {label}"), batch.as_str(), s(&texts[s(&case["batch_prompt"])]));
        }
        m.check(
            format!("version {label}"),
            pm.get_prompt_version(llm, None, None, Some(model), false).as_str(),
            s(&case["version"]),
        );
        m.check(
            format!("batch_version {label}"),
            pm.get_prompt_version(llm, None, None, Some(model), true).as_str(),
            s(&case["batch_version"]),
        );
    }
    m.assert_empty("prompt cases");
}

#[test]
fn optimized_messages_match_python() {
    let golden = load("prompt.json.gz");
    let texts = golden["texts"].as_object().unwrap();
    let mut m = Mismatches(Vec::new());
    let mut current: Option<(String, bool, tempfile::TempDir, PromptManager)> = None;

    for case in golden["messages"].as_array().unwrap() {
        let (pair, compact) = (s(&case["language_pair"]), case["compact"].as_bool().unwrap());
        if current.as_ref().is_none_or(|(p, c, _, _)| p != pair || *c != compact) {
            let dir = tempfile::tempdir().unwrap();
            let pm = manager(dir.path(), pair, compact);
            current = Some((pair.to_string(), compact, dir, pm));
        }
        let pm = &mut current.as_mut().unwrap().3;
        pm.set_content_type(s(&case["content_type"])).unwrap();
        let (llm, model, text) = (s(&case["llm_type"]), s(&case["model"]), s(&case["text"]));
        let context = strings(&case["context"]);
        let index = case["current_index"].as_u64().map(|i| i as usize);
        let label = format!("{pair} compact={compact} {} {llm} {model:?} {text:?} idx={index:?}", case["content_type"]);

        let messages = pm.get_optimized_message(text, &context, llm, model, index);
        let roles: Vec<String> = messages.iter().map(|m| m.role.clone()).collect();
        m.check(format!("roles {label}"), roles, strings(&case["roles"]));
        if md5_hex(&messages[0].content) != s(&case["system"]) {
            m.check(format!("system {label}"), messages[0].content.as_str(), s(&texts[s(&case["system"])]));
        }
        m.check(format!("user {label}"), messages[1].content.as_str(), s(&case["user"]));
        m.check(
            format!("effective_context {label}"),
            pm.get_effective_context_texts(text, &context, llm, model, index),
            strings(&case["effective_context"]),
        );
        m.check(
            format!("cache_context {label}"),
            pm.get_effective_cache_context_texts(text, &context, llm, model, index),
            strings(&case["cache_context"]),
        );
    }
    m.assert_empty("optimized messages");
}

#[test]
fn custom_prompts_match_python() {
    let golden = &load("prompt.json.gz")["custom"];
    let dir = tempfile::tempdir().unwrap();
    let templates = dir.path().join("prompt_templates");
    std::fs::create_dir_all(&templates).unwrap();
    std::fs::write(templates.join("anime_template.json"), r#"{"openai": "ANIME TEMPLATE"}"#).unwrap();

    let mut m = Mismatches(Vec::new());
    let mut pm = PromptManager::open(dir.path()).unwrap();
    m.check(
        "after_load anime_openai",
        pm.get_prompt("openai", Some("anime"), Some("standard"), None).as_str(),
        s(&golden["after_load"]["anime_openai"]),
    );
    pm.set_prompt("CUSTOM ONE\n", "openai", Some("adult")).unwrap();
    pm.set_prompt("CUSTOM TWO", "openai", Some("adult")).unwrap();
    let after = &golden["after_set"];
    m.check(
        "adult_openai",
        pm.get_prompt("openai", Some("adult"), Some("literal"), None).as_str(),
        s(&after["adult_openai"]),
    );
    m.check(
        "adult_google",
        pm.get_prompt("google", Some("adult"), Some("standard"), None).as_str(),
        s(&after["adult_google"]),
    );
    m.check(
        "custom version",
        pm.get_prompt_version("openai", Some("adult"), Some("standard"), None, false).as_str(),
        s(&after["version"]),
    );
    pm.reset_to_default(Some("openai"), Some("adult")).unwrap();
    m.check(
        "after_reset",
        md5_hex(&pm.get_prompt("openai", Some("adult"), Some("standard"), None)).as_str(),
        s(&golden["after_reset"]["adult_openai"]),
    );

    let mut config: Value =
        serde_json::from_str(&std::fs::read_to_string(dir.path().join("prompt_config.json")).unwrap()).unwrap();
    let obj = config.as_object_mut().unwrap();
    obj.shift_remove("last_updated");
    for history in obj["version_history"].as_object_mut().unwrap().values_mut() {
        for entries in history.as_object_mut().unwrap().values_mut() {
            for entry in entries.as_array_mut().unwrap() {
                entry.as_object_mut().unwrap().shift_remove("timestamp");
            }
        }
    }
    m.check("prompt_config.json", config, golden["config"].clone());
    m.check(
        "adult_template.json",
        std::fs::read_to_string(templates.join("adult_template.json")).unwrap().as_str(),
        s(&golden["adult_template"]),
    );
    m.assert_empty("custom prompts");
}
