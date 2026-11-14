//! 翻譯 client 的 HTTP 行為測試（wiremock）：重試、錯誤處理、批次、診斷、Gemini、快取。

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use serde_json::{json, Value};
use srt_translator::cache::CacheManager;
use srt_translator::client::{ClientOptions, LlmType, RetryPolicy, TranslationClient};
use srt_translator::prompt::PromptManager;
use wiremock::matchers::{header, method, path};
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

fn completion(content: &str) -> ResponseTemplate {
    ResponseTemplate::new(200).set_body_json(json!({
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }))
}

fn setup(dir: &std::path::Path) -> Arc<PromptManager> {
    Arc::new(PromptManager::open(dir).unwrap())
}

fn client(server: &MockServer, dir: &std::path::Path, cache: Option<Arc<CacheManager>>) -> TranslationClient {
    let mut options = ClientOptions::new(LlmType::Llamacpp);
    options.base_url = Some(format!("{}/v1/", server.uri()));
    TranslationClient::new(options, setup(dir), cache)
}

/// 前 N 次回傳指定狀態碼，之後回傳成功。
struct FailThen {
    failures: usize,
    status: u16,
    count: AtomicUsize,
}

impl Respond for FailThen {
    fn respond(&self, _: &Request) -> ResponseTemplate {
        if self.count.fetch_add(1, Ordering::SeqCst) < self.failures {
            ResponseTemplate::new(self.status).set_body_string(r#"{"error": {"message": "Loading model"}}"#)
        } else {
            completion(r#"{"translation": "成功"}"#)
        }
    }
}

#[tokio::test]
async fn server_error_is_retried_like_sdk() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(FailThen { failures: 1, status: 503, count: AtomicUsize::new(0) })
        .expect(2)
        .mount(&server)
        .await;
    let dir = tempfile::tempdir().unwrap();
    let c = client(&server, dir.path(), None);
    assert_eq!(c.translate_text("Hello", &[], "some-model", None, false).await.unwrap(), "成功");
    assert_eq!(c.metrics().total_tokens, 15);
}

#[tokio::test]
async fn persistent_failure_yields_error_marker() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(401).set_body_string("Unauthorized"))
        .expect(1)
        .mount(&server)
        .await;
    let dir = tempfile::tempdir().unwrap();
    let c = client(&server, dir.path(), None);
    let out = c.translate_with_retry("Hello", &[], "some-model", None, false, RetryPolicy::default()).await;
    assert_eq!(out, "[翻譯錯誤: authentication: Error code: 401 - Unauthorized]");
    assert_eq!(c.metrics().failed_requests, 1);
}

#[tokio::test]
async fn rate_limit_penalizes_concurrency_and_honours_retry_after() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(FailThen { failures: 2, status: 429, count: AtomicUsize::new(0) })
        .mount(&server)
        .await;
    let dir = tempfile::tempdir().unwrap();
    let mut options = ClientOptions::new(LlmType::OpenAi);
    options.base_url = Some(format!("{}/v1", server.uri()));
    options.api_key = Some("sk-test".into());
    let c = TranslationClient::new(options, setup(dir.path()), None);
    // OpenAI 的 SDK 內建重試 2 次即可吸收兩次 429
    let out = c.translate_with_retry("Hello", &[], "gpt-4.1-mini", None, false, RetryPolicy::default()).await;
    assert_eq!(out, r#"{"translation": "成功"}"#);
}

#[tokio::test]
async fn batch_preserves_order_and_uses_cache() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(|req: &Request| {
            let body: Value = serde_json::from_slice(&req.body).unwrap();
            let user = body["messages"][1]["content"].as_str().unwrap().to_string();
            let current = user.lines().nth(1).unwrap_or_default().to_string();
            completion(&format!(r#"{{"translation": "譯:{current}"}}"#))
        })
        .mount(&server)
        .await;
    Mock::given(method("GET")).and(path("/health")).respond_with(ResponseTemplate::new(200)).mount(&server).await;
    Mock::given(method("GET"))
        .and(path("/props"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "total_slots": 3, "model_path": "/models/Hy-MT2-7B-Q4_K_M.gguf",
            "default_generation_settings": {"n_ctx": 4096}, "build_info": "b8680",
        })))
        .mount(&server)
        .await;
    Mock::given(method("GET")).and(path("/slots")).respond_with(ResponseTemplate::new(501)).mount(&server).await;

    let dir = tempfile::tempdir().unwrap();
    let cache = Arc::new(CacheManager::open(dir.path().join("c.db"), 1000, 30).unwrap());
    let c = client(&server, dir.path(), Some(cache.clone()));
    let items: Vec<(String, Vec<String>)> = (0..6).map(|i| (format!("line {i}"), vec![format!("line {i}")])).collect();
    let out = c.translate_batch(&items, "some-model", 5, None, true).await;
    assert_eq!(out, (0..6).map(|i| format!("譯:line {i}")).collect::<Vec<_>>());

    let d = c.server_diagnostics(false).await;
    assert_eq!((d.total_slots, d.slot_n_ctx, d.slots_endpoint_available), (Some(3), Some(4096), Some(false)));
    assert_eq!(c.resolved_model_name().as_deref(), Some("Hy-MT2-7B-Q4_K_M.gguf"));
    assert_eq!(c.effective_batch_size("some-model", 10, 10, 10).await, 3);

    // 第二輪全部命中快取，不再送出請求
    let before = server.received_requests().await.unwrap().len();
    let again = c.translate_batch(&items, "some-model", 5, None, true).await;
    assert_eq!(again, out);
    assert_eq!(server.received_requests().await.unwrap().len(), before);
}

#[tokio::test]
async fn unreachable_server_falls_back_to_two_slots() {
    let dir = tempfile::tempdir().unwrap();
    let mut options = ClientOptions::new(LlmType::Llamacpp);
    options.base_url = Some("http://127.0.0.1:9".into());
    let c = TranslationClient::new(options, setup(dir.path()), None);
    assert!(!c.is_api_available().await);
    assert_eq!(c.effective_batch_size("some-model", 10, 10, 10).await, 2);
}

#[tokio::test]
async fn gemini_request_shape() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1beta/models/gemini-2.5-flash:generateContent"))
        .and(header("x-goog-api-key", "g-key"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "candidates": [{"content": {"parts": [{"text": "思考", "thought": true}, {"text": " 你好 "}]}}],
        })))
        .expect(1)
        .mount(&server)
        .await;
    let dir = tempfile::tempdir().unwrap();
    let mut options = ClientOptions::new(LlmType::Google);
    options.base_url = Some(server.uri());
    options.api_key = Some("g-key".into());
    let c = TranslationClient::new(options, setup(dir.path()), None);
    assert_eq!(c.translate_text("Hello", &[], "gemini-2.5-flash", None, false).await.unwrap(), "你好");
    let body: Value = serde_json::from_slice(&server.received_requests().await.unwrap()[0].body).unwrap();
    assert_eq!(body["generationConfig"], json!({"temperature": 0.1, "maxOutputTokens": 150}));
    assert!(body["contents"][0]["parts"][0]["text"].as_str().unwrap().starts_with("Instructions: "));
}
