//! 階段 3 golden parity：翻譯 client 的 profile、錯誤分類與完整 translate_text 流水線。
//!
//! 流水線案例以 wiremock 依 Python 記錄的順序回應模型輸出，比對 Rust 送出的每個請求 body
//! 與最終翻譯結果。

use std::collections::VecDeque;
use std::io::Read;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use srt_translator::client::error::{classify_message, rate_limit_wait_time, ApiError};
use srt_translator::client::profiles::{
    detect_model_family, is_qwen_ud_model, llamacpp_profile, openai_batch_max_tokens, openai_uses_completion_tokens,
};
use srt_translator::client::{ClientOptions, LlmType, NetflixStyleConfig, TranslationClient};
use srt_translator::prompt::PromptManager;
use wiremock::matchers::{method, path_regex};
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

fn load() -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden/client.json.gz");
    let raw = std::fs::read(path).unwrap();
    let mut text = String::new();
    flate2::read::GzDecoder::new(&raw[..]).read_to_string(&mut text).unwrap();
    serde_json::from_str(&text).unwrap()
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
            let shown: Vec<_> = self.0.iter().take(8).cloned().collect();
            panic!("{what}: {} 項不一致\n{}", self.0.len(), shown.join("\n"));
        }
    }
}

#[test]
fn model_profiles_match_python() {
    let g = load();
    let mut m = Mismatches(Vec::new());
    for (name, expected) in g["families"].as_object().unwrap() {
        m.check(format!("family {name:?}"), detect_model_family(name), expected.as_str().unwrap());
    }
    for (name, expected) in g["qwen_ud"].as_object().unwrap() {
        m.check(format!("qwen_ud {name:?}"), is_qwen_ud_model(name), expected.as_bool().unwrap());
    }
    for (name, expected) in g["profiles"].as_object().unwrap() {
        m.check(format!("profile {name:?}"), serde_json::to_value(llamacpp_profile(name)).unwrap(), expected.clone());
    }
    for (name, expected) in g["completion_tokens"].as_object().unwrap() {
        m.check(format!("completion_tokens {name}"), openai_uses_completion_tokens(name), expected.as_bool().unwrap());
    }
    for (n, expected) in g["batch_tokens"].as_object().unwrap() {
        m.check(format!("batch_tokens {n}"), openai_batch_max_tokens(n.parse().unwrap()), expected.as_i64().unwrap());
    }
    for (msg, expected) in g["rate_waits"].as_object().unwrap() {
        m.check(
            format!("rate_wait {msg:?}"),
            rate_limit_wait_time(&ApiError::new(msg.clone()), 1),
            expected.as_f64().unwrap(),
        );
    }
    for (msg, expected) in g["errors"].as_object().unwrap() {
        m.check(format!("classify {msg:?}"), classify_message(msg).as_str(), expected.as_str().unwrap());
    }
    m.assert_empty("client profiles");
}

/// 依序回傳預設回應並記錄收到的請求 body。
struct Scripted {
    responses: Mutex<VecDeque<Value>>,
    calls: Arc<Mutex<Vec<Value>>>,
}

impl Respond for Scripted {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        self.calls.lock().unwrap().push(serde_json::from_slice(&request.body).unwrap());
        let r = self.responses.lock().unwrap().pop_front().unwrap_or_else(|| json!({"content": ""}));
        ResponseTemplate::new(200).set_body_json(json!({
            "choices": [{
                "finish_reason": r.get("finish_reason").cloned().unwrap_or(json!("stop")),
                "message": {"content": r.get("content").cloned().unwrap_or(Value::Null),
                            "reasoning_content": r.get("reasoning_content").cloned().unwrap_or(Value::Null)},
            }],
        }))
    }
}

fn prompt_manager(dir: &std::path::Path, content_type: &str) -> Arc<PromptManager> {
    let mut pm = PromptManager::open(dir).unwrap();
    pm.user_config_mut().set_and_save("translation.compact_prompt_enabled", true.into()).unwrap();
    pm.set_language_pair("日文→繁體中文").unwrap();
    pm.set_content_type(content_type).unwrap();
    Arc::new(pm)
}

#[tokio::test]
async fn translate_text_pipeline_matches_python() {
    let g = load();
    let server = MockServer::start().await;
    let mut m = Mismatches(Vec::new());
    let config_dirs: Vec<_> = (0..2).map(|_| tempfile::tempdir().unwrap()).collect();
    let managers = [prompt_manager(config_dirs[0].path(), "general"), prompt_manager(config_dirs[1].path(), "adult")];

    for case in g["pipelines"].as_array().unwrap() {
        server.reset().await;
        let calls = Arc::new(Mutex::new(Vec::new()));
        let responses: VecDeque<Value> = case["responses"].as_array().unwrap().iter().cloned().collect();
        Mock::given(method("POST"))
            .and(path_regex(r"chat/completions$"))
            .respond_with(Scripted { responses: Mutex::new(responses), calls: calls.clone() })
            .mount(&server)
            .await;

        let llm_type = LlmType::parse(case["llm_type"].as_str().unwrap()).unwrap();
        let mut options = ClientOptions::new(llm_type);
        options.base_url = Some(match llm_type {
            LlmType::Llamacpp => server.uri(),
            _ => format!("{}/v1", server.uri()),
        });
        options.api_key = Some("sk-test".into());
        options.netflix_style =
            NetflixStyleConfig { enabled: case["netflix"].as_bool().unwrap(), ..Default::default() };
        let pm = if case["content_type"] == "adult" { &managers[1] } else { &managers[0] };
        let client = TranslationClient::new(options, pm.clone(), None);

        let (model, text) = (case["model"].as_str().unwrap(), case["text"].as_str().unwrap());
        let context: Vec<String> = serde_json::from_value(case["context"].clone()).unwrap();
        let label =
            format!("{} {model} {} netflix={} {text:?}", case["llm_type"], case["content_type"], case["netflix"]);

        match client.translate_text(text, &context, model, None, false).await {
            Ok(result) => m.check(format!("result {label}"), Some(result.as_str()), case["result"].as_str()),
            Err(e) => m.check(format!("error {label}"), Some(e.to_string().as_str()), case["error"].as_str()),
        }
        let actual_calls = calls.lock().unwrap().clone();
        m.check(format!("calls {label}"), Value::from(actual_calls), case["calls"].clone());
    }
    m.assert_empty("translate_text pipeline");
}
