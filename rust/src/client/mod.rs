//! 翻譯 client（對等 Python `translation/client.py` 的 `TranslationClient`）。
//!
//! - llama.cpp 與 OpenAI 共用 OpenAI 相容的 `/v1/chat/completions` 路徑
//! - Google Gemini 使用 REST `generateContent`
//! - 流水線：快取 → 日文名字保護 → 組訊息 → 請求 → 未翻譯日文重試 → 還原名字 →
//!   台灣詞彙正規化 → 單行清理 → Netflix 後處理 → 寫快取
//!
//! 與 Python 的差異（皆不影響翻譯內容）：
//! - 連線/逾時錯誤依來源分類為 connection/timeout（Python 的 SDK 例外字串落入 unknown，重試前不等待）
//! - OpenAI token 以估算法計算（Python 用 tiktoken），只影響速率限制判斷
//! - SDK 內建重試以相同規則自行實作（llama.cpp 1 次、OpenAI 2 次；408/409/429/5xx/連線錯誤）

pub mod concurrency;
pub mod error;
pub mod profiles;
pub mod rate_limit;

use std::sync::{Arc, LazyLock, Mutex};
use std::time::{Duration, Instant};

use fancy_regex::Regex;
use futures::future::join_all;
use serde::Serialize;
use serde_json::{json, Map, Value};
use tokio::sync::Semaphore;

use crate::cache::{CacheKey, CacheManager};
use crate::prompt::{Message, PromptManager};
use crate::py;
use crate::text::japanese;
use crate::text::normalize;
use crate::text::NetflixStylePostProcessor;
use crate::tools::srt_tools::{decode_text_record, encode_text_record};

pub use concurrency::AdaptiveConcurrencyController;
pub use error::{ApiError, ApiErrorKind};
use profiles::{detect_model_family, llamacpp_profile, LlamacppProfile, SKIP_JSON_SCHEMA_FAMILIES};
use rate_limit::{estimate_tokens, RateLimiter};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LlmType {
    Llamacpp,
    OpenAi,
    Google,
}

impl LlmType {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "llamacpp" => Some(Self::Llamacpp),
            "openai" => Some(Self::OpenAi),
            "google" => Some(Self::Google),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Llamacpp => "llamacpp",
            Self::OpenAi => "openai",
            Self::Google => "google",
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Llamacpp => "llama.cpp",
            Self::OpenAi => "OpenAI",
            Self::Google => "Google Gemini",
        }
    }
}

/// Netflix 風格後處理設定（對應 Python `netflix_style_config`）。
#[derive(Debug, Clone)]
pub struct NetflixStyleConfig {
    pub enabled: bool,
    pub auto_fix: bool,
    pub strict_mode: bool,
    pub max_chars_per_line: usize,
    pub max_lines: usize,
}

impl Default for NetflixStyleConfig {
    fn default() -> Self {
        Self { enabled: false, auto_fix: true, strict_mode: false, max_chars_per_line: 16, max_lines: 2 }
    }
}

#[derive(Debug, Clone)]
pub struct ClientOptions {
    pub llm_type: LlmType,
    /// llama.cpp server 根 URL；OpenAI/Google 若指定則覆寫官方 API base（測試用）
    pub base_url: Option<String>,
    pub api_key: Option<String>,
    pub netflix_style: NetflixStyleConfig,
    pub openai_max_requests_per_minute: u64,
    pub openai_max_tokens_per_minute: u64,
}

impl ClientOptions {
    pub fn new(llm_type: LlmType) -> Self {
        Self {
            llm_type,
            base_url: None,
            api_key: None,
            netflix_style: NetflixStyleConfig::default(),
            openai_max_requests_per_minute: 500,
            openai_max_tokens_per_minute: 200_000,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct ApiMetrics {
    pub total_requests: u64,
    pub successful_requests: u64,
    pub failed_requests: u64,
    pub total_tokens: u64,
    pub total_cost: f64,
    pub cache_hits: u64,
    pub total_response_time: f64,
}

impl ApiMetrics {
    pub fn average_response_time(&self) -> f64 {
        if self.successful_requests == 0 {
            0.0
        } else {
            self.total_response_time / self.successful_requests as f64
        }
    }

    pub fn success_rate(&self) -> f64 {
        if self.total_requests == 0 {
            0.0
        } else {
            self.successful_requests as f64 / self.total_requests as f64 * 100.0
        }
    }

    pub fn cache_hit_rate(&self) -> f64 {
        if self.total_requests == 0 {
            0.0
        } else {
            self.cache_hits as f64 / self.total_requests as f64 * 100.0
        }
    }
}

/// llama.cpp server 診斷資訊（`/health`、`/props`、`/slots`）。
#[derive(Debug, Clone, Default, Serialize)]
pub struct ServerDiagnostics {
    pub available: bool,
    pub total_slots: Option<i64>,
    pub slot_n_ctx: Option<i64>,
    pub model_path: String,
    pub is_sleeping: bool,
    pub slots_endpoint_available: Option<bool>,
    pub build_info: String,
    pub speculative_decoding: bool,
}

const DIAGNOSTICS_TTL: Duration = Duration::from_secs(30);
/// 診斷未取得 total_slots 時的安全並行上限
const LLAMACPP_FALLBACK_SLOTS: usize = 2;

const LLAMACPP_RESPONSE_FORMAT: &str = r#"{
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {"translation": {"type": "string", "description": "Translated subtitle text only."}},
        "required": ["translation"],
        "additionalProperties": false
    }
}"#;

static BATCH_LINE_COUNT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)\[BATCH:\s*(\d+)\s+lines").unwrap());
static OPENAI_KEY_CHARS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-zA-Z0-9\-_]+$").unwrap());

/// 從訊息中取出 `[BATCH: N lines` 的行數。
pub fn extract_batch_line_count(messages: &[Message]) -> Option<i64> {
    messages.iter().find_map(|m| {
        BATCH_LINE_COUNT.captures(&m.content).ok().flatten().and_then(|c| c.get(1)?.as_str().parse().ok())
    })
}

/// 建立日文未翻譯時的單次強化重試訊息（附加在 system 訊息之後，沒有 system 時插入）。
fn build_untranslated_retry_messages(messages: &[Message]) -> Vec<Message> {
    let mut retry = messages.to_vec();
    if let Some(system) = retry.iter_mut().find(|m| m.role == "system") {
        system.content = format!("{}\n\n{}", py::rstrip(&system.content), japanese::UNTRANSLATED_RETRY_INSTRUCTION);
    } else {
        retry.insert(0, Message::system(japanese::UNTRANSLATED_RETRY_INSTRUCTION));
    }
    retry
}

/// `translate_with_retry` 的重試策略（Python 預設 max_tries=3、use_fallback=True）。
#[derive(Debug, Clone, Copy)]
pub struct RetryPolicy {
    pub max_tries: u32,
    pub use_fallback: bool,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self { max_tries: 3, use_fallback: true }
    }
}

pub struct TranslationClient {
    pub llm_type: LlmType,
    base_url: String,
    api_key: Option<String>,
    http: reqwest::Client,
    prompt: Arc<PromptManager>,
    cache: Option<Arc<CacheManager>>,
    post_processor: Option<NetflixStylePostProcessor>,
    pub concurrency: AdaptiveConcurrencyController,
    rate_limiter: Option<RateLimiter>,
    metrics: Mutex<ApiMetrics>,
    diagnostics: Mutex<Option<(Instant, ServerDiagnostics)>>,
    resolved_model_name: Mutex<Option<String>>,
    request_timeout: Duration,
    max_sdk_retries: u32,
}

impl TranslationClient {
    pub fn new(options: ClientOptions, prompt: Arc<PromptManager>, cache: Option<Arc<CacheManager>>) -> Self {
        let llm_type = options.llm_type;
        let base_url = match (llm_type, options.base_url) {
            (LlmType::Llamacpp, url) => {
                let url = url.unwrap_or_else(|| "http://localhost:8080".into());
                let url = url.trim_end_matches('/');
                url.strip_suffix("/v1").unwrap_or(url).to_string()
            }
            (LlmType::OpenAi, url) => url.unwrap_or_else(|| "https://api.openai.com/v1".into()),
            (LlmType::Google, url) => url.unwrap_or_else(|| "https://generativelanguage.googleapis.com".into()),
        };
        // 本地推理可能較慢（首次載入、CPU-only），llama.cpp 逾時 10 分鐘
        let (request_timeout, max_sdk_retries) = match llm_type {
            LlmType::Llamacpp => (Duration::from_secs(600), 1),
            LlmType::OpenAi => (Duration::from_secs(30), 2),
            LlmType::Google => (Duration::from_secs(120), 0),
        };
        let netflix = &options.netflix_style;
        let post_processor = netflix.enabled.then(|| {
            NetflixStylePostProcessor::new(
                netflix.auto_fix,
                netflix.strict_mode,
                netflix.max_chars_per_line,
                netflix.max_lines,
            )
        });
        let rate_limiter = (llm_type == LlmType::OpenAi)
            .then(|| RateLimiter::new(options.openai_max_requests_per_minute, options.openai_max_tokens_per_minute));
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .pool_max_idle_per_host(10)
            .build()
            .expect("reqwest client 建立失敗");
        Self {
            llm_type,
            base_url,
            api_key: options.api_key,
            http,
            prompt,
            cache,
            post_processor,
            concurrency: AdaptiveConcurrencyController::default(),
            rate_limiter,
            metrics: Mutex::new(ApiMetrics::default()),
            diagnostics: Mutex::new(None),
            resolved_model_name: Mutex::new(None),
            request_timeout,
            max_sdk_retries,
        }
    }

    pub fn metrics(&self) -> ApiMetrics {
        self.metrics.lock().unwrap().clone()
    }

    pub fn reset_metrics(&self) {
        *self.metrics.lock().unwrap() = ApiMetrics::default();
    }

    pub fn prompt_manager(&self) -> &PromptManager {
        &self.prompt
    }

    /// 若為 llama.cpp 且 server 回報了實際模型檔名，家族無法從設定名稱判斷時改用實際名稱。
    fn resolve_llamacpp_model_name(&self, model_name: &str) -> String {
        if self.llm_type == LlmType::Llamacpp {
            if let Some(resolved) = self.resolved_model_name.lock().unwrap().as_ref() {
                if detect_model_family(model_name) == "default" {
                    return resolved.clone();
                }
            }
        }
        model_name.to_string()
    }

    fn llamacpp_profile(&self, model_name: &str) -> LlamacppProfile {
        llamacpp_profile(&self.resolve_llamacpp_model_name(model_name))
    }

    /// Hunyuan-MT 所有內容類型都保護日文名字；Qwen UD 只在成人字幕保護。
    fn should_protect_japanese_names(&self, model_name: &str) -> bool {
        if self.llm_type != LlmType::Llamacpp {
            return false;
        }
        let effective = self.resolve_llamacpp_model_name(model_name);
        detect_model_family(&effective) == "hunyuan-mt"
            || (profiles::is_qwen_ud_model(&effective) && self.prompt.current_content_type == "adult")
    }

    // ─── 請求組裝 ─────────────────────────────────────────────

    /// 組出 `/v1/chat/completions` 的 JSON body（與 Python 經 OpenAI SDK 送出的內容相同）。
    pub fn build_chat_body(&self, messages: &[Message], model_name: &str) -> Value {
        let mut body = Map::new();
        body.insert("model".into(), model_name.into());
        body.insert("messages".into(), serde_json::to_value(messages).expect("訊息序列化不會失敗"));
        let batch_line_count = extract_batch_line_count(messages);

        if self.llm_type == LlmType::Llamacpp {
            let profile = self.llamacpp_profile(model_name);
            body.insert("temperature".into(), profile.options.get("temperature").cloned().unwrap_or(json!(0.1)));
            body.insert("max_tokens".into(), profile.options.get("max_tokens").cloned().unwrap_or(json!(256)));
            if !SKIP_JSON_SCHEMA_FAMILIES.contains(&profile.family) {
                body.insert("response_format".into(), serde_json::from_str(LLAMACPP_RESPONSE_FORMAT).unwrap());
            }
            if let Some(top_p) = profile.options.get("top_p") {
                body.insert("top_p".into(), top_p.clone());
            }
            body.extend(profile.extra_body);
        } else {
            let tokens_key = if profiles::openai_uses_completion_tokens(model_name) {
                "max_completion_tokens"
            } else {
                "max_tokens"
            };
            body.insert("temperature".into(), json!(0.1));
            body.insert(tokens_key.into(), json!(150));
            if let Some(lines) = batch_line_count.filter(|n| *n > 1) {
                let current = body[tokens_key].as_i64().unwrap_or(150);
                body.insert(tokens_key.into(), json!(current.max(profiles::openai_batch_max_tokens(lines))));
                body.insert("temperature".into(), json!(0.0));
            }
            if model_name.contains("gpt-4") || model_name.contains("gpt-3.5-turbo") {
                body.insert("response_format".into(), json!({"type": "text"}));
            }
        }
        Value::Object(body)
    }

    fn auth_key(&self) -> &str {
        match self.llm_type {
            // llama-server 預設無需認證
            LlmType::Llamacpp => "sk-no-key-required",
            _ => self.api_key.as_deref().unwrap_or_default(),
        }
    }

    fn chat_completions_url(&self) -> String {
        match self.llm_type {
            LlmType::Llamacpp => format!("{}/v1/chat/completions", self.base_url),
            _ => format!("{}/chat/completions", self.base_url.trim_end_matches('/')),
        }
    }

    /// 發送 POST，並以 OpenAI SDK 相同規則重試（408/409/429/5xx/連線錯誤；遵守 ≤60 秒的 retry-after）。
    async fn post_json(&self, request: reqwest::RequestBuilder) -> Result<Value, ApiError> {
        let mut attempt = 0;
        loop {
            let req = request.try_clone().expect("JSON 請求可複製").timeout(self.request_timeout);
            let (err, retryable) = match req.send().await {
                Ok(resp) => {
                    let status = resp.status();
                    let retry_after = error::parse_retry_after(resp.headers());
                    let text = resp.text().await.map_err(|e| ApiError::from_reqwest(&e))?;
                    if status.is_success() {
                        return serde_json::from_str(&text)
                            .map_err(|e| ApiError::new(format!("回應不是合法 JSON: {e}")));
                    }
                    let code = status.as_u16();
                    (ApiError::http(code, &text, retry_after), matches!(code, 408 | 409 | 429) || code >= 500)
                }
                Err(e) => (ApiError::from_reqwest(&e), true),
            };
            if !retryable || attempt >= self.max_sdk_retries {
                return Err(err);
            }
            let delay = match err.retry_after {
                Some(s) if s > 0.0 && s <= 60.0 => s,
                _ => (0.5 * 2f64.powi(attempt as i32)).min(8.0) * (1.0 - 0.25 * rand::random::<f64>()),
            };
            tokio::time::sleep(Duration::from_secs_f64(delay)).await;
            attempt += 1;
        }
    }

    async fn translate_openai_compatible(&self, messages: &[Message], model_name: &str) -> Result<String, ApiError> {
        let is_llamacpp = self.llm_type == LlmType::Llamacpp;
        let started = Instant::now();
        if let Some(limiter) = &self.rate_limiter {
            let _estimated = estimate_tokens(messages);
            let wait = limiter.required_wait();
            if !wait.is_zero() {
                tokio::time::sleep(wait).await;
            }
            limiter.record_request(started);
        }
        let body = self.build_chat_body(messages, model_name);
        let request = self.http.post(self.chat_completions_url()).bearer_auth(self.auth_key()).json(&body);
        let response = self.post_json(request).await?;

        let choice = &response["choices"][0];
        if choice["finish_reason"].as_str() == Some("length") {
            return Err(ApiError::new(format!("[1300] {} response truncated by max_tokens", self.llm_type.label())));
        }
        let content = choice["message"]["content"].as_str().unwrap_or_default();
        let mut translation = py::strip(content).to_string();
        if is_llamacpp && !translation.is_empty() {
            translation = normalize::extract_llamacpp_structured_translation(&translation);
        }
        if is_llamacpp && translation.is_empty() {
            // 思考模型可能把結果放在 reasoning_content
            if let Some(reasoning) = choice["message"]["reasoning_content"].as_str().filter(|r| !r.is_empty()) {
                let extracted = normalize::extract_llamacpp_structured_translation(reasoning);
                translation =
                    if extracted.is_empty() { normalize::sanitize_local_translation(reasoning) } else { extracted };
            }
        }
        if is_llamacpp && !translation.is_empty() {
            translation = normalize::sanitize_local_translation(&translation);
        }

        if let Some(usage) = response.get("usage").filter(|u| u.is_object()) {
            let input = usage["prompt_tokens"].as_u64().unwrap_or(0);
            let output = usage["completion_tokens"].as_u64().unwrap_or(0);
            if let Some(limiter) = &self.rate_limiter {
                limiter.record_tokens(started, input + output);
            }
            let mut m = self.metrics.lock().unwrap();
            m.total_tokens += input + output;
            if !is_llamacpp {
                if let Some((pi, po)) = profiles::pricing(self.llm_type.as_str(), model_name) {
                    m.total_cost += input as f64 * pi + output as f64 * po;
                }
            }
        }
        Ok(translation)
    }

    async fn translate_google(&self, messages: &[Message], model_name: &str) -> Result<String, ApiError> {
        let prompt = messages
            .iter()
            .filter_map(|m| match m.role.as_str() {
                "system" => Some(format!("Instructions: {}", m.content)),
                "user" => Some(m.content.clone()),
                _ => None,
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        let body = json!({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 150},
        });
        let url = format!("{}/v1beta/models/{model_name}:generateContent", self.base_url.trim_end_matches('/'));
        let request = self.http.post(url).header("x-goog-api-key", self.auth_key()).json(&body);
        let response = self.post_json(request).await?;
        // 對等 SDK 的 response.text：串接第一個 candidate 的非 thought 文字 parts
        let text: String = response["candidates"][0]["content"]["parts"]
            .as_array()
            .map(|parts| {
                parts
                    .iter()
                    .filter(|p| !p["thought"].as_bool().unwrap_or(false))
                    .filter_map(|p| p["text"].as_str())
                    .collect()
            })
            .unwrap_or_default();
        if let Some(usage) = response.get("usageMetadata") {
            let input = usage["promptTokenCount"].as_u64().unwrap_or(0);
            let output = usage["candidatesTokenCount"].as_u64().unwrap_or(0);
            let mut m = self.metrics.lock().unwrap();
            m.total_tokens += input + output;
            if let Some((pi, po)) = profiles::pricing("google", model_name) {
                m.total_cost += input as f64 * pi + output as f64 * po;
            }
        }
        Ok(py::strip(&text).to_string())
    }

    /// 依 provider 執行單次翻譯請求。
    pub async fn execute_request(&self, messages: &[Message], model_name: &str) -> Result<String, ApiError> {
        match self.llm_type {
            LlmType::Llamacpp | LlmType::OpenAi => self.translate_openai_compatible(messages, model_name).await,
            LlmType::Google => self.translate_google(messages, model_name).await,
        }
    }

    // ─── 翻譯流水線 ───────────────────────────────────────────

    /// 對批次回應逐行套用 Netflix 後處理，保持行數 1:1。
    fn apply_netflix_style_to_batch_response(&self, batch_text: &str) -> String {
        let Some(processor) = &self.post_processor else { return batch_text.to_string() };
        batch_text
            .split('\n')
            .map(|line| {
                if py::strip(line).is_empty() {
                    line.to_string()
                } else {
                    encode_text_record(&processor.process(&decode_text_record(line)).text)
                }
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// 翻譯單一字幕（含快取、名字保護、未翻譯重試與後處理）。
    pub async fn translate_text(
        &self,
        text: &str,
        context: &[String],
        model_name: &str,
        current_index: Option<usize>,
        use_cache: bool,
    ) -> Result<String, ApiError> {
        if py::strip(text).is_empty() {
            return Ok(String::new());
        }
        let started = Instant::now();
        self.metrics.lock().unwrap().total_requests += 1;

        let llm = self.llm_type.as_str();
        let style = if self.prompt.current_style.is_empty() { "standard" } else { &self.prompt.current_style };
        let prompt_version = self.prompt.get_prompt_version(llm, None, None, Some(model_name), false);
        let effective_context =
            self.prompt.get_effective_cache_context_texts(text, context, llm, model_name, current_index);
        let cache_key = CacheKey::new(text, model_name, style, &prompt_version);

        if use_cache {
            if let Some(cached) = self.cache.as_ref().and_then(|c| c.get(cache_key, &effective_context)) {
                if !cached.is_empty() && japanese::cache_rejection_reason(text, &cached).is_none() {
                    self.metrics.lock().unwrap().cache_hits += 1;
                    return Ok(cached);
                }
            }
        }

        let (protected_text, protected_context, restore_map) = if self.should_protect_japanese_names(model_name) {
            japanese::protect_names(text, context)
        } else {
            (text.to_string(), context.to_vec(), Vec::new())
        };
        let messages =
            self.prompt.get_optimized_message(&protected_text, &protected_context, llm, model_name, current_index);

        let outcome = async {
            let mut result = self.execute_request(&messages, model_name).await?;
            if japanese::should_retry_untranslated_japanese(text, &result) {
                let retry = self.execute_request(&build_untranslated_retry_messages(&messages), model_name).await?;
                if !retry.is_empty() {
                    result = retry;
                }
            }
            Ok::<String, ApiError>(result)
        }
        .await;
        let mut result = match outcome {
            Ok(r) => r,
            Err(e) => {
                self.metrics.lock().unwrap().failed_requests += 1;
                return Err(e);
            }
        };

        if !restore_map.is_empty() {
            result = japanese::restore_names(&result, &restore_map);
        }
        result = normalize::normalize_taiwan_subtitle_terminology(&result);
        // 在 Netflix 自動斷行之前清掉模型誤插的換行，保留刻意的斷行
        result = normalize::clean_single_line_translation(text, &result);
        if let Some(processor) = &self.post_processor {
            let batch_lines = extract_batch_line_count(&[Message::user(text)]);
            result = if batch_lines.is_some_and(|n| n > 1) {
                // 批次回應每行對應一個字幕，整串處理會被智慧斷行插入真實換行
                self.apply_netflix_style_to_batch_response(&result)
            } else {
                processor.process(&result).text
            };
        }

        let elapsed = started.elapsed().as_secs_f64();
        {
            let mut m = self.metrics.lock().unwrap();
            m.successful_requests += 1;
            m.total_response_time += elapsed;
        }
        self.concurrency.update(elapsed);

        if use_cache && japanese::cache_rejection_reason(text, &result).is_none() {
            if let Some(cache) = &self.cache {
                cache.store(cache_key, &result, &effective_context);
            }
        }
        Ok(result)
    }

    /// 帶重試與回退的翻譯；全部失敗時回傳 `[翻譯錯誤: ...]`（與 Python 相同，不拋錯）。
    pub async fn translate_with_retry(
        &self,
        text: &str,
        context: &[String],
        model_name: &str,
        current_index: Option<usize>,
        use_cache: bool,
        policy: RetryPolicy,
    ) -> String {
        let RetryPolicy { max_tries, use_fallback } = policy;
        let mut model = model_name.to_string();
        let mut errors: Vec<(ApiErrorKind, String)> = Vec::new();
        let mut tries = 0;
        while tries < max_tries {
            tries += 1;
            match self.translate_text(text, context, &model, current_index, use_cache).await {
                Ok(result) => return result,
                Err(e) => {
                    let kind = e.kind();
                    errors.push((kind, e.to_string()));
                    if use_fallback && tries == 1 {
                        if let Some(fallback) = profiles::fallback_models(self.llm_type.as_str(), &model).first() {
                            model = fallback.to_string();
                            continue;
                        }
                    }
                    let wait = match kind {
                        ApiErrorKind::RateLimit => {
                            self.concurrency.penalize();
                            error::rate_limit_wait_time(&e, tries)
                        }
                        ApiErrorKind::Timeout | ApiErrorKind::Connection => (1.0 * tries as f64).min(5.0),
                        ApiErrorKind::Server => (2.0 * tries as f64).min(10.0),
                        ApiErrorKind::Authentication | ApiErrorKind::ContentFilter => break,
                        ApiErrorKind::Unknown => 0.0,
                    };
                    if tries >= max_tries {
                        break;
                    }
                    if wait > 0.0 {
                        tokio::time::sleep(Duration::from_secs_f64(wait)).await;
                    }
                }
            }
        }
        let summary: Vec<String> = errors.iter().take(3).map(|(k, m)| format!("{}: {m}", k.as_str())).collect();
        format!("[翻譯錯誤: {}]", summary.join("; "))
    }

    /// 批量翻譯（先查快取，其餘以自適應並行數發送）。
    pub async fn translate_batch(
        &self,
        items: &[(String, Vec<String>)],
        model_name: &str,
        concurrent_limit: usize,
        current_indices: Option<&[Option<usize>]>,
        use_cache: bool,
    ) -> Vec<String> {
        let mut results = vec![String::new(); items.len()];
        let llm = self.llm_type.as_str();
        let style = if self.prompt.current_style.is_empty() { "standard" } else { &self.prompt.current_style };
        let prompt_version = self.prompt.get_prompt_version(llm, None, None, Some(model_name), false);

        let mut pending = Vec::new();
        for (i, (text, context)) in items.iter().enumerate() {
            let index = current_indices.and_then(|c| c.get(i).copied().flatten());
            if use_cache {
                let effective = self.prompt.get_effective_cache_context_texts(text, context, llm, model_name, index);
                let cached = self
                    .cache
                    .as_ref()
                    .and_then(|c| c.get(CacheKey::new(text, model_name, style, &prompt_version), &effective));
                if let Some(cached) = cached.filter(|c| !c.is_empty()) {
                    if japanese::cache_rejection_reason(text, &cached).is_none() {
                        results[i] = cached;
                        self.metrics.lock().unwrap().cache_hits += 1;
                        continue;
                    }
                }
            }
            pending.push((i, index));
        }
        if pending.is_empty() {
            return results;
        }

        let adaptive = self.concurrency.current();
        let batch_size = self.effective_batch_size(model_name, concurrent_limit, adaptive, pending.len()).await;
        let semaphore = Semaphore::new(batch_size);
        let tasks = pending.iter().map(|&(i, index)| {
            let semaphore = &semaphore;
            async move {
                let _permit = semaphore.acquire().await.expect("semaphore 不會關閉");
                let (text, context) = &items[i];
                (
                    i,
                    self.translate_with_retry(text, context, model_name, index, use_cache, RetryPolicy::default())
                        .await,
                )
            }
        });
        for (i, translation) in join_all(tasks).await {
            results[i] = translation;
        }
        results
    }

    /// 實際批次並行數：min(上限, 自適應, 待處理)，llama.cpp 再受模型 profile 與 server slots 限制。
    pub async fn effective_batch_size(
        &self,
        model_name: &str,
        concurrent_limit: usize,
        adaptive: usize,
        pending: usize,
    ) -> usize {
        let mut size = concurrent_limit.min(adaptive).min(pending);
        if self.llm_type != LlmType::Llamacpp {
            return size.max(1);
        }
        let model_limit = self.llamacpp_profile(model_name).batch_concurrency_limit;
        if let Some(limit) = model_limit {
            size = size.min(limit.max(0) as usize);
        }
        match self.server_diagnostics(false).await.total_slots {
            Some(slots) if slots > 0 => size = size.min(slots as usize),
            _ if model_limit.is_none() => size = size.min(LLAMACPP_FALLBACK_SLOTS),
            _ => {}
        }
        size.max(1)
    }

    // ─── llama.cpp 診斷與可用性 ───────────────────────────────

    async fn get_json(&self, path: &str) -> Result<(u16, Option<Value>), reqwest::Error> {
        let resp = self.http.get(format!("{}{path}", self.base_url)).timeout(Duration::from_secs(5)).send().await?;
        let status = resp.status().as_u16();
        let body = if status == 200 { resp.json::<Value>().await.ok() } else { None };
        Ok((status, body))
    }

    /// 查詢 llama.cpp server 健康狀態、slots 與實際模型（結果快取 30 秒）。
    pub async fn server_diagnostics(&self, force_refresh: bool) -> ServerDiagnostics {
        if self.llm_type != LlmType::Llamacpp {
            return ServerDiagnostics::default();
        }
        if !force_refresh {
            if let Some((at, d)) = self.diagnostics.lock().unwrap().as_ref() {
                if at.elapsed() < DIAGNOSTICS_TTL {
                    return d.clone();
                }
            }
        }
        let mut d = ServerDiagnostics::default();
        if let Ok((200, _)) = self.get_json("/health").await {
            d.available = true;
            if let Ok((200, Some(props))) = self.get_json("/props").await {
                d.total_slots = props["total_slots"].as_i64().filter(|n| *n > 0);
                d.slot_n_ctx = props["default_generation_settings"]["n_ctx"].as_i64().filter(|n| *n > 0);
                if let Some(path) = props["model_path"].as_str() {
                    d.model_path = path.to_string();
                    if !path.is_empty() {
                        let resolved = path.rsplit('/').next().unwrap_or(path).to_string();
                        *self.resolved_model_name.lock().unwrap() = Some(resolved);
                    }
                }
                d.is_sleeping = props["is_sleeping"].as_bool().unwrap_or(false);
                d.build_info = props["build_info"].as_str().unwrap_or_default().to_string();
            }
            match self.get_json("/slots").await {
                Ok((200, Some(Value::Array(slots)))) => {
                    d.slots_endpoint_available = Some(true);
                    if d.total_slots.is_none() && !slots.is_empty() {
                        d.total_slots = Some(slots.len() as i64);
                    }
                    if let Some(first) = slots.first() {
                        if d.slot_n_ctx.is_none() {
                            d.slot_n_ctx = first["n_ctx"].as_i64().filter(|n| *n > 0);
                        }
                        d.speculative_decoding = first.get("speculative").is_some_and(|v| {
                            !(v.is_null() || v == &json!(false) || v == &json!(0) || v == &json!("") || v == &json!({}))
                        });
                    }
                }
                Ok((200, Some(_))) => d.slots_endpoint_available = Some(true),
                Ok((501, _)) => d.slots_endpoint_available = Some(false),
                _ => {}
            }
        }
        *self.diagnostics.lock().unwrap() = Some((Instant::now(), d.clone()));
        d
    }

    /// server 回報的實際模型檔名（需先呼叫 `server_diagnostics`）。
    pub fn resolved_model_name(&self) -> Option<String> {
        self.resolved_model_name.lock().unwrap().clone()
    }

    /// 驗證 OpenAI API 金鑰格式（sk- / sk-proj- / sk-svcacct-）。
    pub fn validate_openai_api_key(api_key: &str) -> bool {
        let key = py::strip(api_key);
        if key.is_empty() || !OPENAI_KEY_CHARS.is_match(key).unwrap_or(false) {
            return false;
        }
        let len = key.len();
        if key.starts_with("sk-proj-") {
            len >= 50
        } else if key.starts_with("sk-svcacct-") {
            len >= 40
        } else if key.starts_with("sk-") {
            (40..=60).contains(&len)
        } else {
            false
        }
    }

    /// 檢查 API 是否可用（Google 與 Python 版相同回傳 false）。
    pub async fn is_api_available(&self) -> bool {
        match self.llm_type {
            LlmType::OpenAi => {
                let Some(key) = self.api_key.as_deref().filter(|k| Self::validate_openai_api_key(k)) else {
                    return false;
                };
                let url = format!("{}/models", self.base_url.trim_end_matches('/'));
                matches!(
                    self.http.get(url).bearer_auth(key).timeout(self.request_timeout).send().await,
                    Ok(r) if r.status().is_success()
                )
            }
            LlmType::Llamacpp => self.server_diagnostics(true).await.available,
            LlmType::Google => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn batch_line_count_detection() {
        assert_eq!(extract_batch_line_count(&[Message::user("[batch: 12 lines]\na")]), Some(12));
        assert_eq!(extract_batch_line_count(&[Message::user("no batch")]), None);
    }

    #[test]
    fn retry_messages_append_instruction() {
        let msgs = build_untranslated_retry_messages(&[Message::system("SYS  "), Message::user("u")]);
        assert!(msgs[0].content.starts_with("SYS\n\nCRITICAL RETRY INSTRUCTION:"));
        let msgs = build_untranslated_retry_messages(&[Message::user("u")]);
        assert_eq!(msgs[0].role, "system");
    }

    #[test]
    fn openai_key_validation() {
        assert!(TranslationClient::validate_openai_api_key(&format!("sk-{}", "a".repeat(48))));
        assert!(!TranslationClient::validate_openai_api_key("sk-short"));
        assert!(TranslationClient::validate_openai_api_key(&format!("sk-proj-{}", "b".repeat(60))));
        assert!(!TranslationClient::validate_openai_api_key("xx-123"));
    }
}
