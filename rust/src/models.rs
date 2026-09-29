//! 模型選擇與列表（對等 Python `core/models.py` 中 CLI 會用到的部分）。
//!
//! 與 Python 的差異：Google 模型列表在有金鑰時直接回傳靜態清單，不額外送一次 generate_content 驗證金鑰。

use std::time::Duration;

use serde_json::Value;

/// 載入 API 金鑰：環境變數優先，其次為目前目錄的 `.env`（不覆寫既有環境變數）。
pub fn load_api_key(provider: &str) -> Option<String> {
    let _ = dotenvy::dotenv();
    let vars: &[&str] = match provider {
        "openai" => &["OPENAI_API_KEY"],
        "google" => &["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        _ => &[],
    };
    vars.iter().find_map(|v| std::env::var(v).ok().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()))
}

/// 翻譯任務的推薦模型（Python 以靜態模型資料庫計分，結果固定）。
pub fn recommended_model(provider: &str) -> &'static str {
    match provider {
        "openai" => "gpt-4.1",
        "google" => "gemini-3-pro",
        _ => "Hy-MT2-7B-Q4_K_M",
    }
}

const OPENAI_PRIORITY: [(&str, u32); 9] = [
    ("gpt-4.1-mini", 1),
    ("gpt-4.1", 2),
    ("gpt-4.1-nano", 3),
    ("gpt-4o", 4),
    ("gpt-4-turbo", 5),
    ("gpt-4", 6),
    ("gpt-3.5-turbo-16k", 7),
    ("gpt-3.5-turbo", 8),
    ("gpt-4-vision-preview", 999),
];

const GOOGLE_MODELS: [&str; 6] = [
    "gemini-3-pro",
    "gemini-3-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
];

/// 過濾並排序 OpenAI 模型：只留 GPT 系列、排除日期版本（-dddd 結尾），確保包含常用模型。
pub fn filter_openai_models(ids: &[String]) -> Vec<String> {
    let dated = |id: &str| {
        let tail: Vec<char> = id.chars().rev().take(5).collect();
        tail.len() == 5 && tail[..4].iter().all(char::is_ascii_digit) && tail[4] == '-'
    };
    let mut models: Vec<String> = ids.iter().filter(|id| id.contains("gpt") && !dated(id)).cloned().collect();
    let priority = |id: &str| OPENAI_PRIORITY.iter().find(|(m, _)| *m == id).map_or(900, |(_, p)| *p);
    models.sort_by_key(|id| priority(id));
    for essential in ["gpt-4.1-mini", "gpt-4.1"] {
        if !models.iter().any(|m| m == essential) {
            models.push(essential.to_string());
        }
    }
    models
}

async fn get_json(http: &reqwest::Client, url: &str, bearer: Option<&str>) -> Option<Value> {
    let mut req = http.get(url).timeout(Duration::from_secs(5));
    if let Some(key) = bearer {
        req = req.bearer_auth(key);
    }
    let resp = req.send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.json().await.ok()
}

/// 列出 provider 可用模型 id；llama-server 未連線時回傳 `llama-server-offline`。
pub async fn list_models(provider: &str, llamacpp_url: &str, api_key: Option<&str>) -> Vec<String> {
    let http = reqwest::Client::new();
    match provider {
        "llamacpp" => {
            let base = llamacpp_url.trim_end_matches('/');
            let base = base.strip_suffix("/v1").unwrap_or(base);
            let models = get_json(&http, &format!("{base}/v1/models"), None).await;
            let mut ids: Vec<String> = models
                .as_ref()
                .and_then(|m| m["data"].as_array())
                .map(|data| data.iter().filter_map(|d| d["id"].as_str().map(str::to_string)).collect())
                .unwrap_or_default();
            if ids.is_empty() {
                if let Some(path) = get_json(&http, &format!("{base}/props"), None)
                    .await
                    .and_then(|p| p["model_path"].as_str().map(str::to_string))
                    .filter(|p| !p.is_empty())
                {
                    ids.push(path.rsplit('/').next().unwrap_or(&path).to_string());
                }
            }
            if ids.is_empty() {
                vec!["llama-server-offline".into()]
            } else {
                ids
            }
        }
        "openai" => {
            let Some(key) = api_key else { return vec!["gpt-4.1-mini".into()] };
            match get_json(&http, "https://api.openai.com/v1/models", Some(key)).await {
                Some(v) => {
                    let ids: Vec<String> = v["data"]
                        .as_array()
                        .map(|d| d.iter().filter_map(|m| m["id"].as_str().map(str::to_string)).collect())
                        .unwrap_or_default();
                    filter_openai_models(&ids)
                }
                None => vec!["gpt-4.1-mini".into()],
            }
        }
        "google" if api_key.is_some() => GOOGLE_MODELS.iter().map(|s| s.to_string()).collect(),
        _ => Vec::new(),
    }
}

/// 網路連線檢查（Python `check_internet_connection`：3 秒內能否連上 8.8.8.8:53）。
pub async fn check_internet_connection() -> bool {
    tokio::task::spawn_blocking(|| {
        std::net::TcpStream::connect_timeout(&([8, 8, 8, 8], 53).into(), Duration::from_secs(3)).is_ok()
    })
    .await
    .unwrap_or(false)
}

pub const OPENAI_API_BASE: &str = "https://api.openai.com/v1";
pub const GOOGLE_API_BASE: &str = "https://generativelanguage.googleapis.com";

/// 以一個極短請求測試模型可用性，回傳 (是否成功, 訊息)（Python `ModelManager.test_model_connection`）。
pub async fn test_model_connection(
    provider: &str,
    model: &str,
    llamacpp_url: &str,
    api_key: Option<&str>,
) -> (bool, String) {
    test_model_connection_at(provider, model, llamacpp_url, api_key, OPENAI_API_BASE, GOOGLE_API_BASE).await
}

/// 同 [`test_model_connection`]，可指定 OpenAI / Google 端點（測試用）。
///
/// 與 Python 的差異：錯誤細節文字來自 HTTP 回應本文（Python 為 SDK 例外字串）；OpenAI 不做 SDK 的自動重試。
pub async fn test_model_connection_at(
    provider: &str,
    model: &str,
    llamacpp_url: &str,
    api_key: Option<&str>,
    openai_base: &str,
    google_base: &str,
) -> (bool, String) {
    let http = reqwest::Client::new();
    let hello = serde_json::json!([{"role": "user", "content": "Hello"}]);
    match provider {
        "llamacpp" => {
            let base = llamacpp_url.trim_end_matches('/');
            let base = base.strip_suffix("/v1").unwrap_or(base);
            let body = serde_json::json!({"model": model, "messages": hello, "max_tokens": 5, "temperature": 0});
            let sent = http
                .post(format!("{base}/v1/chat/completions"))
                .json(&body)
                .timeout(Duration::from_secs(15))
                .send()
                .await;
            match sent {
                Ok(r) if r.status().is_success() => (true, "模型回應正常".into()),
                Ok(r) => {
                    let status = r.status().as_u16();
                    let detail = r.text().await.unwrap_or_default().trim().to_string();
                    if detail.is_empty() {
                        (false, format!("模型回應失敗: {status}"))
                    } else {
                        (false, format!("模型回應失敗: {status} - {detail}"))
                    }
                }
                Err(e) if e.is_timeout() => {
                    (false, "連線逾時，請確認 llama-server 已啟動、模型已載入完成，或提高 request_timeout".into())
                }
                Err(e) => (false, format!("連線失敗: {e}")),
            }
        }
        "openai" => {
            let Some(key) = api_key.filter(|k| !k.is_empty()) else { return (false, "未提供 API 金鑰".into()) };
            let body = serde_json::json!({"model": model, "messages": hello, "max_tokens": 5});
            let sent = http
                .post(format!("{}/chat/completions", openai_base.trim_end_matches('/')))
                .bearer_auth(key)
                .json(&body)
                .timeout(Duration::from_secs(60))
                .send()
                .await;
            let r = match sent {
                Ok(r) => r,
                Err(e) => return (false, format!("測試連線時發生錯誤: {e}")),
            };
            let status = r.status().as_u16();
            let text = r.text().await.unwrap_or_default();
            match status {
                200..=299 => {
                    let has_choice = serde_json::from_str::<Value>(&text)
                        .ok()
                        .and_then(|v| v["choices"].as_array().map(|c| !c.is_empty()))
                        .unwrap_or(false);
                    if has_choice {
                        (true, "模型回應正常".into())
                    } else {
                        (false, "模型回應格式異常".into())
                    }
                }
                429 => (false, "達到 API 速率限制，請稍後再試".into()),
                401 => (false, "API 金鑰無效或認證失敗".into()),
                400 if text.contains("does not exist") => (false, format!("模型 {model} 不存在或不可用")),
                400 => (false, format!("請求錯誤: Error code: {status} - {text}")),
                _ => (false, format!("測試連線時發生錯誤: Error code: {status} - {text}")),
            }
        }
        "google" => {
            let Some(key) = api_key.filter(|k| !k.is_empty()) else { return (false, "未提供 API 金鑰".into()) };
            let body = serde_json::json!({"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]});
            let sent = http
                .post(format!("{}/v1beta/models/{model}:generateContent", google_base.trim_end_matches('/')))
                .header("x-goog-api-key", key)
                .json(&body)
                .timeout(Duration::from_secs(60))
                .send()
                .await;
            let (status, text) = match sent {
                Ok(r) => (r.status().as_u16(), r.text().await.unwrap_or_default()),
                Err(e) => return (false, format!("測試連線時發生錯誤: {e}")),
            };
            if (200..300).contains(&status) {
                let has_text = serde_json::from_str::<Value>(&text)
                    .ok()
                    .and_then(|v| v["candidates"][0]["content"]["parts"][0]["text"].as_str().map(|t| !t.is_empty()))
                    .unwrap_or(false);
                return if has_text {
                    (true, "模型回應正常".into())
                } else {
                    (false, "模型回應格式異常".into())
                };
            }
            let error = format!("{status} {text}");
            let lower = error.to_lowercase();
            if ["authentication", "invalid api key", "api_key"].iter().any(|n| lower.contains(n)) {
                (false, "API 金鑰無效或認證失敗".into())
            } else if ["rate limit", "quota"].iter().any(|n| lower.contains(n)) {
                (false, "達到 API 速率限制，請稍後再試".into())
            } else if ["not found", "no such model"].iter().any(|n| lower.contains(n)) {
                (false, format!("模型 {model} 不存在或不可用"))
            } else {
                (false, format!("測試連線時發生錯誤: {error}"))
            }
        }
        _ => (false, format!("不支援的提供者: {provider}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn openai_filtering() {
        let ids: Vec<String> = ["gpt-4o", "gpt-3.5-turbo-0301", "whisper-1", "gpt-4.1-mini", "gpt-5"]
            .iter()
            .map(|s| s.to_string())
            .collect();
        assert_eq!(filter_openai_models(&ids), vec!["gpt-4.1-mini", "gpt-4o", "gpt-5", "gpt-4.1"]);
    }
}
