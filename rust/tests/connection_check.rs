//! 開始翻譯前的連線預檢（Python `test_model_connection` / `_validate_translation_request`）行為測試。

use srt_translator::app::validate_request;
use srt_translator::models::test_model_connection_at;
use wiremock::matchers::{body_json, header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

async fn check(provider: &str, server: &MockServer, key: Option<&str>) -> (bool, String) {
    test_model_connection_at(provider, "m1", &server.uri(), key, &format!("{}/v1", server.uri()), &server.uri()).await
}

#[tokio::test]
async fn llamacpp_probe_request_and_messages() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .and(body_json(serde_json::json!({
            "model": "m1", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 5, "temperature": 0,
        })))
        .respond_with(ResponseTemplate::new(200).set_body_string("{}"))
        .up_to_n_times(1)
        .mount(&server)
        .await;
    assert_eq!(check("llamacpp", &server, None).await, (true, "模型回應正常".into()));

    // 設定中的 URL 帶 /v1 也要打到同一個端點
    let with_v1 = test_model_connection_at("llamacpp", "m1", &format!("{}/v1/", server.uri()), None, "", "").await;
    assert_eq!(with_v1, (false, "模型回應失敗: 404".into()));

    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(503).set_body_string("  Loading model \n"))
        .mount(&server)
        .await;
    assert_eq!(check("llamacpp", &server, None).await, (false, "模型回應失敗: 503 - Loading model".into()));

    let (ok, msg) = test_model_connection_at("llamacpp", "m1", "http://127.0.0.1:1", None, "", "").await;
    assert!(!ok && msg.starts_with("連線失敗: "), "{msg}");
}

#[tokio::test]
async fn openai_status_mapping() {
    let cases = [
        (200, r#"{"choices":[{"message":{"content":"Hi"}}]}"#, (true, "模型回應正常")),
        (200, r#"{"choices":[]}"#, (false, "模型回應格式異常")),
        (429, "{}", (false, "達到 API 速率限制，請稍後再試")),
        (401, "{}", (false, "API 金鑰無效或認證失敗")),
        (400, r#"{"error":{"message":"The model `m1` does not exist"}}"#, (false, "模型 m1 不存在或不可用")),
    ];
    for (status, body, expected) in cases {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .and(header("authorization", "Bearer sk-x"))
            .respond_with(ResponseTemplate::new(status).set_body_string(body))
            .mount(&server)
            .await;
        let (ok, msg) = check("openai", &server, Some("sk-x")).await;
        assert_eq!((ok, msg.as_str()), expected, "status {status}");
    }
    let server = MockServer::start().await;
    assert_eq!(check("openai", &server, None).await, (false, "未提供 API 金鑰".into()));
}

#[tokio::test]
async fn google_error_classification() {
    let cases = [
        (200, r#"{"candidates":[{"content":{"parts":[{"text":"Hi"}]}}]}"#, (true, "模型回應正常".to_string())),
        (
            400,
            r#"{"error":{"status":"INVALID_ARGUMENT","details":[{"reason":"API_KEY_INVALID"}]}}"#,
            (false, "API 金鑰無效或認證失敗".into()),
        ),
        (
            429,
            r#"{"error":{"message":"You exceeded your current quota"}}"#,
            (false, "達到 API 速率限制，請稍後再試".into()),
        ),
        (404, r#"{"error":{"message":"models/m1 is not found"}}"#, (false, "模型 m1 不存在或不可用".into())),
    ];
    for (status, body, expected) in cases {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/v1beta/models/m1:generateContent"))
            .and(header("x-goog-api-key", "g-key"))
            .respond_with(ResponseTemplate::new(status).set_body_string(body))
            .mount(&server)
            .await;
        assert_eq!(check("google", &server, Some("g-key")).await, expected, "status {status}");
    }
}

#[tokio::test]
async fn validate_request_messages() {
    for placeholder in ["", "載入中...", "無可用模型", "無法載入模型"] {
        let err = validate_request("llamacpp", placeholder, "http://127.0.0.1:1", None).await.unwrap_err();
        assert_eq!(err, "目前沒有可用模型，請先確認模型列表是否已成功載入。");
    }

    let server = MockServer::start().await;
    Mock::given(method("POST")).respond_with(ResponseTemplate::new(500)).mount(&server).await;
    let err = validate_request("llamacpp", "m1", &server.uri(), None).await.unwrap_err();
    assert_eq!(
        err,
        format!(
            "llama.cpp 連線失敗，目前設定的服務位址為 {}。請確認 llama-server 已啟動且模型已載入。詳細原因: 模型回應失敗: 500",
            server.uri()
        )
    );

    let server = MockServer::start().await;
    Mock::given(method("POST")).respond_with(ResponseTemplate::new(200)).mount(&server).await;
    assert_eq!(validate_request("llamacpp", "m1", &server.uri(), None).await, Ok(()));
}
