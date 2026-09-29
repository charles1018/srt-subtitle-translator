//! TaskControl（暫停 / 繼續 / 停止）接入 TranslationService 的行為測試。

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use srt_translator::client::{ClientOptions, LlmType, TranslationClient};
use srt_translator::config::{ConfigFile, ConfigKind};
use srt_translator::error::Error;
use srt_translator::output::OutputSettings;
use srt_translator::prompt::PromptManager;
use srt_translator::service::heuristics::RuntimeSettings;
use srt_translator::service::{DisplayMode, FileJob, ServiceSettings, TaskControl, TranslationService};
use wiremock::matchers::{method, path_regex};
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

const LINES: usize = 6;

/// 收到請求即計數（回應延遲在計數之後才生效）。
struct CountingModel {
    count: Arc<AtomicUsize>,
    delay: Duration,
}

impl Respond for CountingModel {
    fn respond(&self, _: &Request) -> ResponseTemplate {
        self.count.fetch_add(1, Ordering::SeqCst);
        ResponseTemplate::new(200)
            .set_body_json(serde_json::json!({
                "choices": [{"finish_reason": "stop", "message": {"content": "好的"}}],
            }))
            .set_delay(self.delay)
    }
}

struct Fixture {
    _server: MockServer,
    _dir: tempfile::TempDir,
    count: Arc<AtomicUsize>,
    service: TranslationService,
    input: PathBuf,
    job: FileJob,
    output: OutputSettings,
}

impl Fixture {
    /// OpenAI 路徑、並行 1、batch_size 1：每句恰好一個請求、一句一個批次。
    async fn new(delay: Duration) -> Self {
        let server = MockServer::start().await;
        let count = Arc::new(AtomicUsize::new(0));
        Mock::given(method("POST"))
            .and(path_regex("chat/completions$"))
            .respond_with(CountingModel { count: count.clone(), delay })
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

        let input = dir.path().join("input.srt");
        let srt: String = (1..=LINES)
            .map(|i| format!("{i}\n00:00:0{i},000 --> 00:00:0{i},900\nThis is line number {i}.\n\n"))
            .collect();
        std::fs::write(&input, srt).unwrap();
        let job = FileJob {
            source_lang: "英文".into(),
            target_lang: "繁體中文".into(),
            model_name: "gpt-4.1-mini".into(),
            parallel_requests: 1,
            display_mode: DisplayMode::parse("僅顯示翻譯"),
            use_structure_text: false,
            use_cache: false,
        };
        let output = OutputSettings::from_config(&ConfigFile::load(&cfg, ConfigKind::File).unwrap());
        Self { _server: server, _dir: dir, count, service, input, job, output }
    }

    fn requests(&self) -> usize {
        self.count.load(Ordering::SeqCst)
    }

    fn output_files(&self) -> Vec<PathBuf> {
        std::fs::read_dir(self.input.parent().unwrap())
            .unwrap()
            .map(|e| e.unwrap().path())
            .filter(|p| p.extension().is_some_and(|e| e == "srt") && *p != self.input)
            .collect()
    }
}

#[tokio::test]
async fn pause_stops_new_requests_until_resume() {
    let f = Fixture::new(Duration::ZERO).await;
    let baseline = {
        let g = Fixture::new(Duration::ZERO).await;
        let out = g.service.translate_subtitle_file(&g.input, &g.job, &g.output, &|_, _| {}, None).await.unwrap();
        std::fs::read_to_string(out.output_path).unwrap()
    };

    let control = TaskControl::new();
    let pauser = control.clone();
    let progress = move |done: usize, _: usize| {
        if done == 2 {
            pauser.pause();
        }
    };
    let translate =
        f.service.translate_subtitle_file_with_control(&f.input, &f.job, &f.output, &progress, None, Some(&control));
    let drive = async {
        tokio::time::sleep(Duration::from_millis(300)).await;
        let while_paused = f.requests();
        assert!(control.is_paused());
        control.resume();
        while_paused
    };
    let (result, while_paused) = tokio::join!(translate, drive);

    assert_eq!(while_paused, 2, "暫停期間不應送出新請求");
    let outcome = result.unwrap();
    assert_eq!((outcome.successful, outcome.failed), (LINES, 0));
    assert_eq!(f.requests(), LINES);
    assert_eq!(std::fs::read_to_string(outcome.output_path).unwrap(), baseline, "暫停後繼續的輸出應與未暫停相同");
}

#[tokio::test]
async fn stop_between_batches_writes_nothing() {
    let f = Fixture::new(Duration::ZERO).await;
    let control = TaskControl::new();
    let stopper = control.clone();
    let progress = move |done: usize, _: usize| {
        if done == 2 {
            stopper.stop();
        }
    };
    let result = f
        .service
        .translate_subtitle_file_with_control(&f.input, &f.job, &f.output, &progress, None, Some(&control))
        .await;
    assert!(matches!(result, Err(Error::Cancelled)), "{result:?}");
    assert_eq!(f.requests(), 2);
    assert!(f.output_files().is_empty());
}

#[tokio::test]
async fn stop_after_last_line_writes_nothing() {
    let f = Fixture::new(Duration::ZERO).await;
    let control = TaskControl::new();
    let stopper = control.clone();
    let progress = move |done: usize, total: usize| {
        if done == total {
            stopper.stop();
        }
    };
    let result = f
        .service
        .translate_subtitle_file_with_control(&f.input, &f.job, &f.output, &progress, None, Some(&control))
        .await;
    assert!(matches!(result, Err(Error::Cancelled)), "{result:?}");
    assert_eq!(f.requests(), LINES);
    assert!(f.output_files().is_empty());
}

#[tokio::test]
async fn stop_aborts_in_flight_request() {
    assert_stop_aborts_in_flight(false).await;
}

#[tokio::test]
async fn stop_aborts_in_flight_structure_text_batch() {
    assert_stop_aborts_in_flight(true).await;
}

async fn assert_stop_aborts_in_flight(use_structure_text: bool) {
    let mut f = Fixture::new(Duration::from_secs(5)).await;
    f.job.use_structure_text = use_structure_text;
    let control = TaskControl::new();
    let started = Instant::now();
    let translate =
        f.service.translate_subtitle_file_with_control(&f.input, &f.job, &f.output, &|_, _| {}, None, Some(&control));
    let drive = async {
        tokio::time::sleep(Duration::from_millis(200)).await;
        control.stop();
    };
    let (result, ()) = tokio::join!(translate, drive);
    assert!(matches!(result, Err(Error::Cancelled)), "{result:?}");
    assert!(started.elapsed() < Duration::from_secs(2), "應立即中止，實際 {:?}", started.elapsed());
    assert_eq!(f.requests(), 1);
    assert!(f.output_files().is_empty());
}

#[tokio::test]
async fn stop_while_paused_cancels() {
    let f = Fixture::new(Duration::ZERO).await;
    let control = TaskControl::new();
    control.pause();
    let translate =
        f.service.translate_subtitle_file_with_control(&f.input, &f.job, &f.output, &|_, _| {}, None, Some(&control));
    let drive = async {
        tokio::time::sleep(Duration::from_millis(100)).await;
        control.stop();
    };
    let (result, ()) = tokio::join!(translate, drive);
    assert!(matches!(result, Err(Error::Cancelled)), "{result:?}");
    assert_eq!(f.requests(), 0);
}
