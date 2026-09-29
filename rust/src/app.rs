//! 翻譯工作階段組裝與 GUI 共用邏輯（CLI `translate` 與桌面 GUI 共用，與畫面無關）。
//!
//! 對應 Python `cli.py` 的 `cmd_translate` 服務建立流程，以及 `__main__.py` / `gui/components.py`
//! 中與畫面無關的規則（模型下拉選擇、開始前預檢、完成訊息、狀態文字）。

use std::path::{Path, PathBuf};
use std::sync::Arc;

use log::{info, warn};

use crate::cache::CacheManager;
use crate::client::{ClientOptions, LlmType, NetflixStyleConfig, TranslationClient};
use crate::config::{ConfigFile, ConfigKind};
use crate::error::{Error, Result};
use crate::glossary::GlossaryManager;
use crate::models;
use crate::output::OutputSettings;
use crate::prompt::{PromptManager, LANGUAGE_PAIRS};
use crate::service::{DisplayMode, FileJob, FileOutcome, ServiceSettings, TranslationService};

pub const GLOSSARY_DIR: &str = "data/glossaries";

pub fn ensure_runtime_dirs() {
    for dir in ["data", "config", "logs"] {
        let _ = std::fs::create_dir_all(dir);
    }
}

pub fn open_cache(config_dir: &Path) -> Result<CacheManager> {
    let config = ConfigFile::load(config_dir, ConfigKind::Cache)?;
    let db_path = config.get_str("db_path").unwrap_or("data/translation_cache.db").to_string();
    let max_memory = config.get_i64("max_memory_cache").filter(|v| *v > 0).unwrap_or(1000) as usize;
    let cleanup_days = config.get_i64("auto_cleanup_days").filter(|v| *v > 0).unwrap_or(30);
    CacheManager::open(db_path, max_memory, cleanup_days)
}

/// 遞迴收集目錄內指定副檔名（小寫、不含點）的檔案，依路徑排序、回傳絕對路徑。
///
/// 與 Python `os.walk`（followlinks=False）相同：不進入指向目錄的符號連結，但保留指向檔案的連結。
pub fn walk_subtitles(dir: &Path, extensions: &[String]) -> Vec<PathBuf> {
    let mut out = Vec::new();
    walk(dir, extensions, &mut out);
    out
}

fn walk(dir: &Path, extensions: &[String], out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    let mut paths: Vec<PathBuf> = entries.filter_map(|e| e.ok().map(|e| e.path())).collect();
    paths.sort();
    for p in paths {
        if p.is_symlink() && p.is_dir() {
            continue;
        }
        if p.is_dir() {
            walk(&p, extensions, out);
        } else if has_extension(&p, extensions) {
            out.push(std::path::absolute(&p).unwrap_or(p));
        }
    }
}

/// 副檔名比對（不分大小寫；`extensions` 為小寫、不含點）。
pub fn has_extension(path: &Path, extensions: &[String]) -> bool {
    path.extension().is_some_and(|e| extensions.iter().any(|x| *x == e.to_string_lossy().to_lowercase()))
}

/// 展開選取/拖放的路徑（Python `handle_drop` / `scan_directory`）：資料夾遞迴掃描，檔案依副檔名過濾；
/// 回傳 (字幕檔絕對路徑, 不支援格式的檔案)，不存在的路徑略過。
pub fn expand_paths(paths: &[PathBuf], extensions: &[String]) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let (mut files, mut unsupported) = (Vec::new(), Vec::new());
    for path in paths {
        if path.is_dir() {
            files.extend(walk_subtitles(path, extensions));
        } else if path.is_file() {
            if has_extension(path, extensions) {
                files.push(std::path::absolute(path).unwrap_or_else(|_| path.clone()));
            } else {
                unsupported.push(path.clone());
            }
        }
    }
    (files, unsupported)
}

/// `file_handler_config.json` 的 `supported_formats`（GUI 選檔/拖放/掃描資料夾使用）。
pub fn supported_extensions(file_config: &ConfigFile) -> Vec<String> {
    file_config
        .get("supported_formats")
        .and_then(|v| v.as_array())
        .map(|formats| {
            formats
                .iter()
                .filter_map(|f| f.get(0).and_then(|e| e.as_str()))
                .map(|e| e.trim_start_matches('.').to_lowercase())
                .collect()
        })
        .unwrap_or_default()
}

/// 一次翻譯工作的參數（CLI 旗標 / GUI 表單）。
#[derive(Debug, Clone)]
pub struct TranslateOptions {
    pub source: String,
    pub target: String,
    pub provider: String,
    /// 未指定時使用推薦模型。
    pub model: Option<String>,
    /// 覆寫 prompt 設定的內容類型/風格（只作用於本次，不寫回設定檔）。
    pub content_type: Option<String>,
    pub style: Option<String>,
    pub display_mode: String,
    pub concurrency: usize,
    pub output_dir: Option<PathBuf>,
    pub use_cache: bool,
    /// 未指定時沿用 `user_settings.json` 的 `netflix_style_enabled`。
    pub netflix_style: Option<bool>,
    pub glossaries: Vec<String>,
    pub structure_text: bool,
}

/// 組裝完成、可直接翻譯檔案的工作階段。
pub struct Session {
    pub service: TranslationService,
    pub job: FileJob,
    pub output: OutputSettings,
}

/// 依設定目錄與參數建立翻譯服務（對等 Python `cmd_translate` 的建立流程）。
///
/// 與 Python 的差異：`output_dir` 只作用於本次執行，不會寫回 `file_handler_config.json`。
pub fn prepare_session(config_dir: &Path, opts: &TranslateOptions) -> Result<Session> {
    let user = ConfigFile::load(config_dir, ConfigKind::User)?;
    let model_config = ConfigFile::load(config_dir, ConfigKind::Model)?;
    let file_config = ConfigFile::load(config_dir, ConfigKind::File)?;

    // 本次執行的覆寫（不寫回設定檔）
    let mut prompt = PromptManager::open(config_dir)?;
    if let Some(ct) = &opts.content_type {
        prompt.current_content_type = ct.clone();
    }
    if let Some(style) = &opts.style {
        prompt.current_style = style.clone();
    }
    let pair = format!("{}→{}", opts.source, opts.target);
    if LANGUAGE_PAIRS.iter().any(|(name, _, _)| *name == pair) {
        prompt.current_language_pair = pair;
    } else {
        warn!("未支援的語言對 {pair}，沿用 {}", prompt.current_language_pair);
    }
    let prompt = Arc::new(prompt);

    let llm_type = LlmType::parse(&opts.provider)
        .ok_or_else(|| Error::validation(format!("不支援的 LLM 提供者: {}", opts.provider), Default::default()))?;
    let model_name = opts.model.clone().unwrap_or_else(|| {
        let m = models::recommended_model(&opts.provider).to_string();
        info!("使用推薦模型: {m}");
        m
    });

    let mut output = OutputSettings::from_config(&file_config);
    if let Some(dir) = &opts.output_dir {
        output.output_directory = dir.to_string_lossy().into_owned();
    }

    let mut glossary = GlossaryManager::open(GLOSSARY_DIR)?;
    for name in &opts.glossaries {
        if glossary.activate(name) {
            info!("已啟用術語表: {name}");
        } else {
            warn!("找不到術語表: {name}");
        }
    }

    let cache = Arc::new(open_cache(config_dir)?);
    let mut options = ClientOptions::new(llm_type);
    if llm_type == LlmType::Llamacpp {
        options.base_url = model_config.get_str("llamacpp_url").map(str::to_string);
    }
    options.api_key = models::load_api_key(&opts.provider);
    options.openai_max_requests_per_minute =
        model_config.get_i64("openai_max_requests_per_minute").filter(|v| *v > 0).unwrap_or(500) as u64;
    options.openai_max_tokens_per_minute =
        model_config.get_i64("openai_max_tokens_per_minute").filter(|v| *v > 0).unwrap_or(200_000) as u64;
    options.netflix_style = NetflixStyleConfig {
        enabled: opts.netflix_style.unwrap_or_else(|| user.get_bool("netflix_style_enabled", false)),
        ..Default::default()
    };
    let client = TranslationClient::new(options, prompt.clone(), Some(cache.clone()));
    let service =
        TranslationService::new(client, prompt, Some(cache), Some(glossary), ServiceSettings::from_user_config(&user));

    let job = FileJob {
        source_lang: opts.source.clone(),
        target_lang: opts.target.clone(),
        model_name,
        parallel_requests: opts.concurrency,
        display_mode: DisplayMode::parse(&opts.display_mode),
        use_structure_text: opts.structure_text,
        use_cache: opts.use_cache,
    };
    Ok(Session { service, job, output })
}

// ---------------------------------------------------------------------------
// GUI 規則（對應 Python `__main__.py` / `gui/components.py`）
// ---------------------------------------------------------------------------

pub const NO_MODELS: &str = "無可用模型";

/// GUI 主視窗的使用者設定（Python `App._apply_user_settings` 讀取、`_save_user_settings` 寫回）。
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct GuiSettings {
    pub source_lang: String,
    pub target_lang: String,
    pub llm_type: String,
    pub model_name: String,
    /// GUI 下拉值為字串，寫回時轉成整數（與 Python 相同）。
    pub parallel_requests: String,
    pub display_mode: String,
    pub netflix_style_enabled: bool,
    pub structure_text_enabled: bool,
}

impl GuiSettings {
    pub fn load(config_dir: &Path) -> Result<Self> {
        let user = ConfigFile::load(config_dir, ConfigKind::User)?;
        let text = |key: &str, default: &str| match user.get(key) {
            Some(serde_json::Value::String(s)) => s.clone(),
            Some(serde_json::Value::Null) | None => default.to_string(),
            Some(v) => v.to_string(),
        };
        Ok(Self {
            source_lang: text("source_lang", "日文"),
            target_lang: text("target_lang", "繁體中文"),
            llm_type: text("llm_type", "llamacpp"),
            model_name: user.get_str("model_name").unwrap_or_default().to_string(),
            parallel_requests: text("parallel_requests", "3"),
            display_mode: text("display_mode", "雙語對照"),
            netflix_style_enabled: user.get_bool("netflix_style_enabled", false),
            structure_text_enabled: user.get_bool("structure_text_enabled", false),
        })
    }

    /// 開始翻譯與關閉視窗時寫回的 6 個欄位（Netflix / 批次翻譯勾選框在切換當下即已寫入）。
    pub fn save(&self, config_dir: &Path) -> Result<()> {
        let parallel: i64 = self.parallel_requests.trim().parse().map_err(|_| {
            Error::validation(format!("並行請求數必須是整數: {}", self.parallel_requests), Default::default())
        })?;
        let mut user = ConfigFile::load(config_dir, ConfigKind::User)?;
        user.set("source_lang", self.source_lang.clone().into());
        user.set("target_lang", self.target_lang.clone().into());
        user.set("llm_type", self.llm_type.clone().into());
        user.set("model_name", self.model_name.clone().into());
        user.set("parallel_requests", parallel.into());
        user.set("display_mode", self.display_mode.clone().into());
        user.save()
    }
}

/// 立即寫入單一使用者設定（顯示模式、Netflix、批次翻譯勾選框、最後使用目錄）。
pub fn set_user_value(config_dir: &Path, key: &str, value: serde_json::Value) -> Result<()> {
    ConfigFile::load(config_dir, ConfigKind::User)?.set_and_save(key, value)
}

/// 來源/目標語言變更時同步到 prompt 設定；不支援的組合回傳 false 且不寫入
/// （Python `on_source_target_lang_changed`）。
pub fn sync_language_pair(config_dir: &Path, source: &str, target: &str) -> Result<bool> {
    PromptManager::open(config_dir)?.set_language_pair(&format!("{source}→{target}"))
}

/// 模型下拉清單與預設選取（Python `_update_model_dropdown` + `set_model_list`）：
/// 沿用上次的模型；不在清單內則用推薦模型；推薦模型也不在清單內則選第一個。
pub fn choose_model(models: &[String], saved: Option<&str>, provider: &str) -> (Vec<String>, String) {
    if models.is_empty() {
        return (vec![NO_MODELS.into()], NO_MODELS.into());
    }
    let preferred = match saved.filter(|m| !m.is_empty() && models.iter().any(|x| x == m)) {
        Some(m) => m.to_string(),
        None => models::recommended_model(provider).to_string(),
    };
    let selected = if models.contains(&preferred) { preferred } else { models[0].clone() };
    (models.to_vec(), selected)
}

/// 開始翻譯前的預檢（Python `_validate_translation_request`）；失敗時回傳要顯示的錯誤訊息。
pub async fn validate_request(
    provider: &str,
    model: &str,
    llamacpp_url: &str,
    api_key: Option<&str>,
) -> std::result::Result<(), String> {
    if ["", "載入中...", NO_MODELS, "無法載入模型"].contains(&model) {
        return Err("目前沒有可用模型，請先確認模型列表是否已成功載入。".into());
    }
    match provider {
        "openai" | "google" => {
            if !models::check_internet_connection().await {
                return Err("網路連線異常，請檢查網路後重試。".into());
            }
            let label = if provider == "openai" { "OpenAI" } else { "Google Gemini" };
            let Some(key) = api_key.filter(|k| !k.is_empty()) else {
                let hint = if provider == "openai" { "OPENAI_API_KEY" } else { "GOOGLE_API_KEY / GEMINI_API_KEY" };
                return Err(format!("未設定 {label} API 金鑰，請先在 `.env` 或環境變數設定 {hint}。"));
            };
            let (ok, detail) = models::test_model_connection(provider, model, llamacpp_url, Some(key)).await;
            if ok {
                Ok(())
            } else {
                Err(format!("{label} 連線失敗。請確認網路、API 金鑰與模型名稱設定是否正確。詳細原因: {detail}"))
            }
        }
        "llamacpp" => {
            let (ok, detail) = models::test_model_connection(provider, model, llamacpp_url, None).await;
            if ok {
                Ok(())
            } else {
                Err(format!(
                    "llama.cpp 連線失敗，目前設定的服務位址為 {llamacpp_url}。請確認 llama-server 已啟動且模型已載入。詳細原因: {detail}"
                ))
            }
        }
        _ => Ok(()),
    }
}

/// 單一檔案翻譯結束後顯示的訊息（Python `translate_subtitle_file` 的 complete_callback 訊息）。
pub fn completion_message(result: &Result<FileOutcome>) -> String {
    match result {
        Ok(o) if o.failed > 0 => format!(
            "翻譯部分完成 | 檔案已成功儲存為: {} | 成功 {}/{}，失敗 {}",
            o.output_path.display(),
            o.successful,
            o.total,
            o.failed
        ),
        Ok(o) => format!("翻譯完成 | 檔案已成功儲存為: {}", o.output_path.display()),
        Err(Error::Translation { details, .. }) if details.contains_key("all_failed_total") => {
            let total = details["all_failed_total"].as_u64().unwrap_or(0);
            let mut message = format!("翻譯失敗 | 0/{total} 句字幕成功，未輸出檔案");
            if let Some(last) = details.get("last_error").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
                message = format!("{message}。最後錯誤: {last}");
            }
            message
        }
        Err(Error::Cancelled) => "翻譯已停止".into(),
        Err(e) => format!("翻譯過程中發生錯誤: {e}"),
    }
}

/// 多檔翻譯過程中送給畫面的事件（GUI 實作；方法可能在背景執行緒呼叫）。
pub trait RunEvents: Send + Sync {
    /// 開始翻譯第 `index`（從 1 起算）個檔案。
    fn file_started(&self, index: usize, total_files: usize, path: &Path);
    fn progress(&self, current: usize, total: usize);
    /// 一個檔案結束（成功、部分成功或失敗）；`message` 已附總進度。
    fn file_finished(&self, message: String, completed: usize, total_files: usize);
    /// 輸出檔已存在且設定為詢問時呼叫；可阻塞等待使用者選擇。
    fn ask_conflict(&self, path: &Path) -> crate::output::ConflictChoice;
}

/// 多檔翻譯的結果摘要。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RunSummary {
    pub completed: usize,
    pub stopped: bool,
}

/// 依序翻譯多個檔案（GUI 的「開始翻譯」）。
///
/// 與 Python 的差異：Python GUI 每個檔案各開一個執行緒同時翻譯（進度互相覆蓋）；這裡逐檔進行，
/// 與 CLI 相同。停止後不再處理剩下的檔案，被停止的檔案不寫出、也不回報完成。
pub async fn run_files(
    session: &Session,
    files: &[PathBuf],
    control: &crate::service::TaskControl,
    events: &dyn RunEvents,
) -> RunSummary {
    let total_files = files.len();
    let mut completed = 0;
    let progress = |current: usize, total: usize| events.progress(current, total);
    let ask = |path: &Path| events.ask_conflict(path);
    for (i, file) in files.iter().enumerate() {
        if control.is_stopped() {
            return RunSummary { completed, stopped: true };
        }
        events.file_started(i + 1, total_files, file);
        let result = session
            .service
            .translate_subtitle_file_with_control(
                file,
                &session.job,
                &session.output,
                &progress,
                Some(&ask),
                Some(control),
            )
            .await;
        if matches!(result, Err(Error::Cancelled)) {
            return RunSummary { completed, stopped: true };
        }
        completed += 1;
        events.file_finished(
            with_total_progress(&completion_message(&result), completed, total_files),
            completed,
            total_files,
        );
    }
    RunSummary { completed, stopped: false }
}

/// 多檔翻譯時附加總進度（Python `TranslationTaskManager._complete_wrapper`）。
pub fn with_total_progress(message: &str, completed: usize, total: usize) -> String {
    format!("{message} | 總進度: {completed}/{total}")
}

/// 翻譯中的狀態列文字與百分比（Python `_update_progress`）。
pub fn progress_status(current: usize, total: usize) -> (String, usize) {
    let percentage = if total > 0 { current * 100 / total } else { 0 };
    (format!("正在翻譯第 {current}/{total} 句字幕 ({percentage}%)"), percentage)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strings(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn model_choice_prefers_saved_then_recommended_then_first() {
        // openai 推薦模型為 gpt-4.1
        let list = strings(&["a", "gpt-4.1", "b"]);
        assert_eq!(choose_model(&list, Some("b"), "openai").1, "b");
        assert_eq!(choose_model(&list, Some("missing"), "openai").1, "gpt-4.1");
        assert_eq!(choose_model(&list, None, "openai").1, "gpt-4.1");
        assert_eq!(choose_model(&strings(&["x", "y"]), Some(""), "openai").1, "x");
        assert_eq!(choose_model(&[], Some("b"), "openai"), (strings(&[NO_MODELS]), NO_MODELS.to_string()));
    }

    #[test]
    fn messages_match_python_format() {
        let ok = FileOutcome {
            output_path: PathBuf::from("/tmp/a_繁體中文.srt"),
            total: 10,
            successful: 10,
            failed: 0,
            elapsed: "1 秒".into(),
        };
        assert_eq!(completion_message(&Ok(ok.clone())), "翻譯完成 | 檔案已成功儲存為: /tmp/a_繁體中文.srt");
        let partial = FileOutcome { successful: 8, failed: 2, ..ok };
        assert_eq!(
            completion_message(&Ok(partial)),
            "翻譯部分完成 | 檔案已成功儲存為: /tmp/a_繁體中文.srt | 成功 8/10，失敗 2"
        );
        assert_eq!(completion_message(&Err(Error::file("讀取失敗"))), "翻譯過程中發生錯誤: [1400] 讀取失敗");
        assert_eq!(with_total_progress("翻譯完成", 1, 3), "翻譯完成 | 總進度: 1/3");
        assert_eq!(progress_status(1, 3), ("正在翻譯第 1/3 句字幕 (33%)".to_string(), 33));
        assert_eq!(progress_status(0, 0).1, 0);
    }

    /// 與 Python `os.walk` 相同：不進入指向目錄的符號連結，但保留指向檔案的連結。
    #[cfg(unix)]
    #[test]
    fn walk_skips_directory_symlinks() {
        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let input = root.path().join("subs");
        std::fs::create_dir_all(input.join("season1")).unwrap();
        std::fs::write(input.join("season1/ep01.srt"), "").unwrap();
        std::fs::write(input.join("season1/notes.txt"), "").unwrap();
        std::fs::write(outside.path().join("secret.srt"), "").unwrap();
        std::os::unix::fs::symlink(root.path(), input.join("loop")).unwrap();
        std::os::unix::fs::symlink(outside.path(), input.join("elsewhere")).unwrap();
        std::os::unix::fs::symlink(outside.path().join("secret.srt"), input.join("linked.SRT")).unwrap();

        let names: Vec<String> = walk_subtitles(&input, &strings(&["srt", "vtt"]))
            .iter()
            .map(|p| p.strip_prefix(&input).unwrap().to_string_lossy().into_owned())
            .collect();
        assert_eq!(names, ["linked.SRT", "season1/ep01.srt"]);
    }

    #[test]
    fn expand_paths_scans_dirs_and_filters_files() {
        let dir = tempfile::tempdir().unwrap();
        let sub = dir.path().join("sub");
        std::fs::create_dir(&sub).unwrap();
        for name in ["a.srt", "b.txt", "sub/c.vtt", "sub/d.mkv"] {
            std::fs::write(dir.path().join(name), "").unwrap();
        }
        let exts = strings(&["srt", "vtt"]);
        let inputs = [dir.path().join("a.srt"), dir.path().join("b.txt"), sub.clone(), dir.path().join("missing.srt")];
        let (files, unsupported) = expand_paths(&inputs, &exts);
        assert_eq!(files, [dir.path().join("a.srt"), sub.join("c.vtt")]);
        assert_eq!(unsupported, [dir.path().join("b.txt")]);
    }

    #[test]
    fn supported_extensions_from_config() {
        let dir = tempfile::tempdir().unwrap();
        let file = ConfigFile::load(dir.path(), ConfigKind::File).unwrap();
        assert_eq!(supported_extensions(&file), strings(&["srt", "vtt", "ass", "ssa", "sub"]));
    }
}
