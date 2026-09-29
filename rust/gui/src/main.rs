//! SRT 字幕翻譯器桌面 GUI（Tauri v2，前端為 `ui/` 的純 HTML/JS）。
//!
//! 對應 Python `__main__.py` + `gui/components.py`。與畫面無關的規則（設定讀寫、模型選擇、預檢、
//! 完成訊息、多檔排程）都在 `srt_translator::app`，這裡只負責把它們接到前端的 command 與事件。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::sync::{mpsc, Mutex};

use serde::Serialize;
use serde_json::Value;
use srt_translator::app::{
    self, choose_model, run_files, set_user_value, sync_language_pair, validate_request, GuiSettings, RunEvents,
    TranslateOptions,
};
use srt_translator::config::{resolve_config_dir, ConfigFile, ConfigKind, APP_VERSION};
use srt_translator::models;
use srt_translator::output::ConflictChoice;
use srt_translator::prompt::{PromptManager, CONTENT_TYPES, SUPPORTED_LLM_TYPES, TRANSLATION_STYLES};
use srt_translator::service::TaskControl;
use tauri::{AppHandle, DragDropEvent, Emitter, Manager, State, WindowEvent};
use tauri_plugin_dialog::DialogExt;

const SOURCE_LANGS: [&str; 4] = ["日文", "英文", "韓文", "繁體中文"];
const TARGET_LANGS: [&str; 4] = ["繁體中文", "英文", "日文", "韓文"];
const PARALLEL_OPTIONS: [&str; 8] = ["1", "2", "3", "4", "5", "10", "15", "20"];
const DISPLAY_MODES: [&str; 4] = ["雙語對照", "僅顯示翻譯", "翻譯在上", "原文在上"];
/// 前端可直接寫入的使用者設定（切換當下即存檔，與 Python 相同）。
const INSTANT_OPTIONS: [&str; 3] = ["display_mode", "netflix_style_enabled", "structure_text_enabled"];

struct AppState {
    /// 資料基準目錄（絕對路徑，見 `app::gui_workdir`）
    base_dir: PathBuf,
    config_dir: PathBuf,
    run: Mutex<Option<TaskControl>>,
    conflict: Mutex<Option<mpsc::Sender<ConflictChoice>>>,
}

type CmdResult<T> = Result<T, String>;

fn err(e: impl std::fmt::Display) -> String {
    e.to_string()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct InitData {
    settings: GuiSettings,
    content_type: String,
    style: String,
    source_langs: Vec<&'static str>,
    target_langs: Vec<&'static str>,
    llm_types: Vec<&'static str>,
    parallel_options: Vec<&'static str>,
    display_modes: Vec<&'static str>,
    content_types: Vec<&'static str>,
    styles: Vec<(&'static str, &'static str)>,
    extensions: Vec<String>,
    version: &'static str,
}

/// 載入設定並把儲存的語言對同步到 prompt 設定（Python `_apply_user_settings`）。
#[tauri::command]
fn init(state: State<'_, AppState>) -> CmdResult<InitData> {
    app::ensure_runtime_dirs_in(&state.base_dir);
    let dir = &state.config_dir;
    let settings = GuiSettings::load(dir).map_err(err)?;
    if !sync_language_pair(dir, &settings.source_lang, &settings.target_lang).map_err(err)? {
        log::warn!("不支援的語言對組合: {}→{}", settings.source_lang, settings.target_lang);
    }
    let prompt = PromptManager::open(dir).map_err(err)?;
    let file_config = ConfigFile::load(dir, ConfigKind::File).map_err(err)?;
    Ok(InitData {
        settings,
        content_type: prompt.current_content_type.clone(),
        style: prompt.current_style.clone(),
        source_langs: SOURCE_LANGS.to_vec(),
        target_langs: TARGET_LANGS.to_vec(),
        llm_types: SUPPORTED_LLM_TYPES.to_vec(),
        parallel_options: PARALLEL_OPTIONS.to_vec(),
        display_modes: DISPLAY_MODES.to_vec(),
        content_types: CONTENT_TYPES.to_vec(),
        styles: TRANSLATION_STYLES.to_vec(),
        extensions: app::supported_extensions(&file_config),
        version: APP_VERSION,
    })
}

fn llamacpp_url(dir: &Path) -> CmdResult<String> {
    let model_config = ConfigFile::load(dir, ConfigKind::Model).map_err(err)?;
    Ok(model_config.get_str("llamacpp_url").unwrap_or("http://localhost:8080").to_string())
}

#[derive(Serialize)]
struct ModelList {
    models: Vec<String>,
    selected: String,
}

#[tauri::command]
async fn list_models(state: State<'_, AppState>, llm_type: String) -> CmdResult<ModelList> {
    let url = llamacpp_url(&state.config_dir)?;
    let key = models::load_api_key(&llm_type);
    let found = models::list_models(&llm_type, &url, key.as_deref()).await;
    let saved = GuiSettings::load(&state.config_dir).map_err(err)?.model_name;
    let (models, selected) = choose_model(&found, Some(&saved), &llm_type);
    Ok(ModelList { models, selected })
}

#[tauri::command]
fn set_language(state: State<'_, AppState>, source: String, target: String) -> CmdResult<bool> {
    sync_language_pair(&state.config_dir, &source, &target).map_err(err)
}

#[tauri::command]
fn set_content_type(state: State<'_, AppState>, value: String) -> CmdResult<bool> {
    PromptManager::open(&state.config_dir).map_err(err)?.set_content_type(&value).map_err(err)
}

#[tauri::command]
fn set_style(state: State<'_, AppState>, value: String) -> CmdResult<bool> {
    PromptManager::open(&state.config_dir).map_err(err)?.set_translation_style(&value).map_err(err)
}

#[tauri::command]
fn set_option(state: State<'_, AppState>, key: String, value: Value) -> CmdResult<()> {
    if !INSTANT_OPTIONS.contains(&key.as_str()) {
        return Err(format!("不支援的設定: {key}"));
    }
    set_user_value(&state.config_dir, &key, value).map_err(err)
}

#[derive(Serialize)]
struct AddResult {
    files: Vec<String>,
    unsupported: Vec<String>,
}

/// 展開拖放/選取的路徑：資料夾遞迴掃描、檔案依副檔名過濾（Python `handle_drop` / `scan_directory`），
/// 並記住最後使用的目錄（`from_folder`：來自「選擇資料夾」）。
#[tauri::command]
fn add_paths(state: State<'_, AppState>, paths: Vec<String>, from_folder: bool) -> CmdResult<AddResult> {
    let dir = &state.config_dir;
    let extensions = app::supported_extensions(&ConfigFile::load(dir, ConfigKind::File).map_err(err)?);
    let inputs: Vec<PathBuf> = paths.iter().map(PathBuf::from).collect();
    let (files, unsupported) = app::expand_paths(&inputs, &extensions);
    app::remember_added_files(dir, &files, from_folder).map_err(err)?;
    let text = |v: &[PathBuf]| v.iter().map(|p| p.to_string_lossy().into_owned()).collect();
    Ok(AddResult { files: text(&files), unsupported: text(&unsupported) })
}

fn last_directory(dir: &Path) -> Option<PathBuf> {
    let config = ConfigFile::load(dir, ConfigKind::File).ok()?;
    config.get_str("last_directory").filter(|d| Path::new(d).is_dir()).map(PathBuf::from)
}

#[tauri::command]
async fn pick_files(app: AppHandle, state: State<'_, AppState>) -> CmdResult<Vec<String>> {
    let extensions = app::supported_extensions(&ConfigFile::load(&state.config_dir, ConfigKind::File).map_err(err)?);
    let ext_refs: Vec<&str> = extensions.iter().map(String::as_str).collect();
    let mut dialog = app.dialog().file().set_title("選擇字幕檔案").add_filter("所有支援的字幕檔", &ext_refs);
    for ext in &ext_refs {
        dialog = dialog.add_filter(format!("{} 字幕檔", ext.to_uppercase()), &[ext]);
    }
    if let Some(dir) = last_directory(&state.config_dir) {
        dialog = dialog.set_directory(dir);
    }
    let picked = dialog.blocking_pick_files().unwrap_or_default();
    Ok(picked.into_iter().filter_map(|p| p.into_path().ok()).map(|p| p.to_string_lossy().into_owned()).collect())
}

#[tauri::command]
async fn pick_folder(app: AppHandle, state: State<'_, AppState>) -> CmdResult<Option<String>> {
    let mut dialog = app.dialog().file().set_title("選擇字幕資料夾（同時作為輸出目錄）");
    if let Some(dir) = app::folder_dialog_start(&state.config_dir) {
        dialog = dialog.set_directory(dir);
    }
    let Some(folder) = dialog.blocking_pick_folder().and_then(|p| p.into_path().ok()) else { return Ok(None) };
    app::remember_selected_folder(&state.config_dir, &folder).map_err(err)?;
    Ok(Some(folder.to_string_lossy().into_owned()))
}

// ---------------------------------------------------------------------------
// 翻譯執行
// ---------------------------------------------------------------------------

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RunFinished {
    completed: usize,
    total: usize,
    stopped: bool,
    error: Option<String>,
    play_sound: bool,
}

struct TauriEvents {
    app: AppHandle,
}

impl RunEvents for TauriEvents {
    fn file_started(&self, index: usize, total_files: usize, path: &Path) {
        let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let _ = self.app.emit("file-started", serde_json::json!({"index": index, "total": total_files, "name": name}));
    }

    fn progress(&self, current: usize, total: usize) {
        let (status, percent) = app::progress_status(current, total);
        let _ = self.app.emit(
            "progress",
            serde_json::json!({"current": current, "total": total, "status": status, "percent": percent}),
        );
    }

    fn file_finished(&self, message: String, completed: usize, total_files: usize) {
        let _ = self.app.emit(
            "file-finished",
            serde_json::json!({"message": message, "completed": completed, "total": total_files}),
        );
    }

    /// 通知前端並阻塞等待使用者選擇（翻譯在專用執行緒的 runtime 上執行）。
    fn ask_conflict(&self, path: &Path) -> ConflictChoice {
        let (tx, rx) = mpsc::channel();
        *self.app.state::<AppState>().conflict.lock().unwrap() = Some(tx);
        let _ = self.app.emit("conflict", serde_json::json!({"path": path.to_string_lossy()}));
        tokio::task::block_in_place(|| rx.recv()).unwrap_or(ConflictChoice::Skip)
    }
}

/// 預檢後開始翻譯（Python `App.start_translation`）；預檢失敗回傳要顯示的錯誤訊息。
#[tauri::command]
async fn start_translation(
    app: AppHandle,
    state: State<'_, AppState>,
    files: Vec<String>,
    settings: GuiSettings,
) -> CmdResult<()> {
    if state.run.lock().unwrap().is_some() {
        return Err("翻譯正在進行中".into());
    }
    if files.is_empty() {
        return Err("請先選擇要翻譯的檔案".into());
    }
    let dir = state.config_dir.clone();
    let key = models::load_api_key(&settings.llm_type);
    validate_request(&settings.llm_type, &settings.model_name, &llamacpp_url(&dir)?, key.as_deref()).await?;
    let concurrency: usize = settings.parallel_requests.trim().parse().map_err(err)?;
    let user = ConfigFile::load(&dir, ConfigKind::User).map_err(err)?;
    if user.get_bool("auto_save", true) {
        settings.save(&dir).map_err(err)?;
    }
    let play_sound = user.get_bool("play_sound", true);

    let control = TaskControl::new();
    *state.run.lock().unwrap() = Some(control.clone());
    let options = TranslateOptions {
        source: settings.source_lang.clone(),
        target: settings.target_lang.clone(),
        provider: settings.llm_type.clone(),
        model: Some(settings.model_name.clone()),
        content_type: None,
        style: None,
        display_mode: settings.display_mode.clone(),
        concurrency,
        output_dir: None,
        use_cache: true,
        netflix_style: Some(settings.netflix_style_enabled),
        glossaries: Vec::new(),
        structure_text: settings.structure_text_enabled,
        base_dir: state.base_dir.clone(),
    };
    let files: Vec<PathBuf> = files.into_iter().map(PathBuf::from).collect();
    std::thread::spawn(move || {
        let total = files.len();
        let outcome = tokio::runtime::Builder::new_multi_thread().enable_all().build().map_err(err).and_then(|rt| {
            rt.block_on(async {
                let session = app::prepare_session(&dir, &options).map_err(err)?;
                Ok(run_files(&session, &files, &control, &TauriEvents { app: app.clone() }).await)
            })
        });
        *app.state::<AppState>().run.lock().unwrap() = None;
        let finished = match outcome {
            Ok(s) => RunFinished { completed: s.completed, total, stopped: s.stopped, error: None, play_sound },
            Err(e) => RunFinished { completed: 0, total, stopped: false, error: Some(e), play_sound: false },
        };
        let _ = app.emit("run-finished", finished);
    });
    Ok(())
}

#[tauri::command]
fn pause(state: State<'_, AppState>) {
    if let Some(c) = &*state.run.lock().unwrap() {
        c.pause();
    }
}

#[tauri::command]
fn resume(state: State<'_, AppState>) {
    if let Some(c) = &*state.run.lock().unwrap() {
        c.resume();
    }
}

#[tauri::command]
fn stop(state: State<'_, AppState>) {
    if let Some(c) = &*state.run.lock().unwrap() {
        c.stop();
    }
    // 若正在等待檔名衝突的選擇，視為略過以解除阻塞
    if let Some(tx) = state.conflict.lock().unwrap().take() {
        let _ = tx.send(ConflictChoice::Skip);
    }
}

#[tauri::command]
fn resolve_conflict(state: State<'_, AppState>, choice: String) -> CmdResult<()> {
    let choice = match choice.as_str() {
        "overwrite" => ConflictChoice::Overwrite,
        "rename" => ConflictChoice::Rename,
        _ => ConflictChoice::Skip,
    };
    if let Some(tx) = state.conflict.lock().unwrap().take() {
        let _ = tx.send(choice);
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 提示詞編輯器（Python `PromptEditorWindow`）
// ---------------------------------------------------------------------------

#[tauri::command]
fn prompt_get(state: State<'_, AppState>, llm_type: String, content_type: String) -> CmdResult<String> {
    let prompt = PromptManager::open(&state.config_dir).map_err(err)?;
    Ok(prompt.get_prompt(&llm_type, Some(&content_type), None, None))
}

#[tauri::command]
fn prompt_save(state: State<'_, AppState>, llm_type: String, content_type: String, text: String) -> CmdResult<()> {
    let mut prompt = PromptManager::open(&state.config_dir).map_err(err)?;
    prompt.set_prompt(&text, &llm_type, Some(&content_type)).map_err(err)
}

#[tauri::command]
fn prompt_reset(state: State<'_, AppState>, llm_type: String, content_type: String) -> CmdResult<bool> {
    let mut prompt = PromptManager::open(&state.config_dir).map_err(err)?;
    prompt.reset_to_default(Some(&llm_type), Some(&content_type)).map_err(err)
}

/// 關閉視窗前儲存設定（Python `on_closing`）後結束程式；初始化失敗時不存設定。
#[tauri::command]
fn save_and_quit(app: AppHandle, state: State<'_, AppState>, settings: Option<GuiSettings>) -> CmdResult<()> {
    if let Some(c) = &*state.run.lock().unwrap() {
        c.stop();
    }
    let saved = settings.map_or(Ok(()), |s| s.save(&state.config_dir).map_err(err));
    app.exit(0);
    saved
}

/// 決定資料基準目錄與設定目錄（絕對路徑；不切換工作目錄，原因見 `app::gui_workdir`），並載入其中的 `.env`。
fn resolve_dirs() -> AppState {
    // AppImage 啟動腳本會 cd 到掛載目錄，使用者原本的目錄在 OWD
    let cwd = std::env::var_os("OWD").map(PathBuf::from).or_else(|| std::env::current_dir().ok()).unwrap_or_default();
    let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(Path::to_path_buf));
    let has_env = std::env::var("CONFIG_DIR").is_ok_and(|v| !v.trim().is_empty());
    let base = app::gui_workdir(&cwd, exe_dir.as_deref(), dirs::data_dir().as_deref(), has_env);
    let base = std::path::absolute(&base).unwrap_or(base);
    let config_dir = if has_env { resolve_config_dir(None) } else { base.join("config") };
    models::load_dotenv_in(&base);
    AppState { base_dir: base, config_dir, run: Mutex::new(None), conflict: Mutex::new(None) }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(resolve_dirs())
        .on_window_event(|window, event| match event {
            // 交給前端確認（翻譯中需確認）並儲存設定後再結束
            WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let _ = window.emit("close-requested", ());
            }
            WindowEvent::DragDrop(DragDropEvent::Enter { .. }) => {
                let _ = window.emit("drag-hover", true);
            }
            WindowEvent::DragDrop(DragDropEvent::Leave) => {
                let _ = window.emit("drag-hover", false);
            }
            WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. }) => {
                let _ = window.emit("drag-hover", false);
                let paths: Vec<String> = paths.iter().map(|p| p.to_string_lossy().into_owned()).collect();
                let _ = window.emit("paths-dropped", paths);
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            init,
            list_models,
            set_language,
            set_content_type,
            set_style,
            set_option,
            add_paths,
            pick_files,
            pick_folder,
            start_translation,
            pause,
            resume,
            stop,
            resolve_conflict,
            prompt_get,
            prompt_save,
            prompt_reset,
            save_and_quit,
        ])
        .run(tauri::generate_context!())
        .expect("啟動 GUI 失敗");
}
