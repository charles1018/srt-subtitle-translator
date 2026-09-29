//! GUI 多檔翻譯排程（`app::run_files`）行為測試：事件順序、完成訊息、檔名衝突詢問、停止。

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use srt_translator::app::{run_files, RunEvents, RunSummary, Session};
use srt_translator::client::{ClientOptions, LlmType, TranslationClient};
use srt_translator::config::{ConfigFile, ConfigKind};
use srt_translator::output::{ConflictChoice, OutputSettings, OverwriteMode};
use srt_translator::prompt::PromptManager;
use srt_translator::service::heuristics::RuntimeSettings;
use srt_translator::service::{DisplayMode, FileJob, ServiceSettings, TaskControl, TranslationService};
use wiremock::matchers::{method, path_regex};
use wiremock::{Mock, MockServer, ResponseTemplate};

#[derive(Default)]
struct Recorder {
    log: Mutex<Vec<String>>,
    conflict_choice: Mutex<Option<ConflictChoice>>,
    stop_on_progress: Mutex<Option<(usize, TaskControl)>>,
    stop_on_conflict: Mutex<Option<TaskControl>>,
}

impl RunEvents for Recorder {
    fn file_started(&self, index: usize, total_files: usize, path: &Path) {
        let name = path.file_name().unwrap().to_string_lossy();
        self.log.lock().unwrap().push(format!("start {index}/{total_files} {name}"));
    }

    fn progress(&self, current: usize, total: usize) {
        if let Some((at, control)) = &*self.stop_on_progress.lock().unwrap() {
            if current == *at {
                control.stop();
            }
        }
        let _ = total;
    }

    fn file_finished(&self, message: String, completed: usize, total_files: usize) {
        self.log.lock().unwrap().push(format!("done {completed}/{total_files} {message}"));
    }

    fn ask_conflict(&self, path: &Path) -> ConflictChoice {
        let name = path.file_name().unwrap().to_string_lossy();
        self.log.lock().unwrap().push(format!("ask {name}"));
        // 模擬使用者在衝突對話框開著時按停止：GUI 的 stop 以「略過」解除等待
        if let Some(control) = &*self.stop_on_conflict.lock().unwrap() {
            control.stop();
            return ConflictChoice::Skip;
        }
        self.conflict_choice.lock().unwrap().expect("未預期的衝突詢問")
    }
}

struct Fixture {
    _server: MockServer,
    dir: tempfile::TempDir,
    session: Session,
}

impl Fixture {
    async fn new(status: u16) -> Self {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path_regex("chat/completions$"))
            .respond_with(ResponseTemplate::new(status).set_body_json(serde_json::json!({
                "choices": [{"finish_reason": "stop", "message": {"content": "好的"}}],
            })))
            .mount(&server)
            .await;
        let dir = tempfile::tempdir().unwrap();
        let cfg = dir.path().join("config");
        let mut pm = PromptManager::open(&cfg).unwrap();
        pm.current_language_pair = "英文→繁體中文".into();
        let pm = Arc::new(pm);
        let mut options = ClientOptions::new(LlmType::OpenAi);
        options.base_url = Some(format!("{}/v1", server.uri()));
        options.api_key = Some("sk-test".into());
        let client = TranslationClient::new(options, pm.clone(), None);
        let settings = ServiceSettings {
            runtime: RuntimeSettings { batch_size: 1, ..Default::default() },
            preserve_punctuation: true,
        };
        let service = TranslationService::new(client, pm, None, None, settings);
        let job = FileJob {
            source_lang: "英文".into(),
            target_lang: "繁體中文".into(),
            model_name: "gpt-4.1-mini".into(),
            parallel_requests: 1,
            display_mode: DisplayMode::parse("僅顯示翻譯"),
            use_structure_text: false,
            use_cache: false,
        };
        let mut output = OutputSettings::from_config(&ConfigFile::load(&cfg, ConfigKind::File).unwrap());
        output.overwrite_mode = OverwriteMode::Ask;
        Self { _server: server, dir, session: Session { service, job, output } }
    }

    fn input(&self, name: &str, lines: usize) -> PathBuf {
        let path = self.dir.path().join(name);
        let srt: String =
            (1..=lines).map(|i| format!("{i}\n00:00:0{i},000 --> 00:00:0{i},900\nLine {i} here.\n\n")).collect();
        std::fs::write(&path, srt).unwrap();
        path
    }

    fn output_of(&self, input: &Path) -> PathBuf {
        let stem = input.file_stem().unwrap().to_string_lossy();
        self.dir.path().join(format!("{stem}_繁體中文.srt"))
    }
}

#[tokio::test]
async fn translates_files_in_order_with_python_messages() {
    let f = Fixture::new(200).await;
    let files = vec![f.input("a.srt", 2), f.input("b.srt", 1)];
    let events = Recorder::default();
    let summary = run_files(&f.session, &files, &TaskControl::new(), &events).await;

    assert_eq!(summary, RunSummary { completed: 2, stopped: false });
    let (out_a, out_b) = (f.output_of(&files[0]), f.output_of(&files[1]));
    assert_eq!(
        *events.log.lock().unwrap(),
        [
            "start 1/2 a.srt".to_string(),
            format!("done 1/2 翻譯完成 | 檔案已成功儲存為: {} | 總進度: 1/2", out_a.display()),
            "start 2/2 b.srt".to_string(),
            format!("done 2/2 翻譯完成 | 檔案已成功儲存為: {} | 總進度: 2/2", out_b.display()),
        ]
    );
    assert!(out_a.exists() && out_b.exists());
}

#[tokio::test]
async fn conflict_is_asked_and_skip_reports_error() {
    let f = Fixture::new(200).await;
    let files = vec![f.input("a.srt", 1)];
    std::fs::write(f.output_of(&files[0]), "OLD").unwrap();

    let events = Recorder::default();
    *events.conflict_choice.lock().unwrap() = Some(ConflictChoice::Skip);
    run_files(&f.session, &files, &TaskControl::new(), &events).await;
    let log = events.log.lock().unwrap().clone();
    assert_eq!(log[1], "ask a_繁體中文.srt");
    assert!(log[2].starts_with("done 1/1 翻譯過程中發生錯誤: [1400] "), "{log:?}");
    assert_eq!(std::fs::read_to_string(f.output_of(&files[0])).unwrap(), "OLD");

    let events = Recorder::default();
    *events.conflict_choice.lock().unwrap() = Some(ConflictChoice::Overwrite);
    run_files(&f.session, &files, &TaskControl::new(), &events).await;
    assert_ne!(std::fs::read_to_string(f.output_of(&files[0])).unwrap(), "OLD");
}

#[tokio::test]
async fn stop_ends_run_without_reporting_or_writing() {
    let f = Fixture::new(200).await;
    let files = vec![f.input("a.srt", 3), f.input("b.srt", 1)];
    let control = TaskControl::new();
    let events = Recorder::default();
    *events.stop_on_progress.lock().unwrap() = Some((1, control.clone()));
    let summary = run_files(&f.session, &files, &control, &events).await;

    assert_eq!(summary, RunSummary { completed: 0, stopped: true });
    assert_eq!(*events.log.lock().unwrap(), ["start 1/2 a.srt"]);
    assert!(!f.output_of(&files[0]).exists());
    assert!(!f.output_of(&files[1]).exists());
}

#[tokio::test]
async fn stop_while_asking_conflict_is_reported_as_stopped() {
    let f = Fixture::new(200).await;
    let files = vec![f.input("a.srt", 1), f.input("b.srt", 1)];
    std::fs::write(f.output_of(&files[0]), "OLD").unwrap();
    let control = TaskControl::new();
    let events = Recorder::default();
    *events.stop_on_conflict.lock().unwrap() = Some(control.clone());
    let summary = run_files(&f.session, &files, &control, &events).await;

    assert_eq!(summary, RunSummary { completed: 0, stopped: true });
    assert_eq!(*events.log.lock().unwrap(), ["start 1/2 a.srt", "ask a_繁體中文.srt"]);
    assert_eq!(std::fs::read_to_string(f.output_of(&files[0])).unwrap(), "OLD");
    assert!(!f.output_of(&files[1]).exists());
}

#[tokio::test]
async fn all_failed_file_uses_python_failure_message() {
    let f = Fixture::new(401).await;
    let files = vec![f.input("a.srt", 1)];
    let events = Recorder::default();
    let summary = run_files(&f.session, &files, &TaskControl::new(), &events).await;

    assert_eq!(summary, RunSummary { completed: 1, stopped: false });
    let log = events.log.lock().unwrap().clone();
    assert!(log[1].starts_with("done 1/1 翻譯失敗 | 0/1 句字幕成功，未輸出檔案。最後錯誤: [翻譯錯誤"), "{log:?}");
    assert!(log[1].ends_with(" | 總進度: 1/1"), "{log:?}");
    assert!(!f.output_of(&files[0]).exists());
}
