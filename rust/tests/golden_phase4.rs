//! 階段 4 golden parity：OpenCC s2twp 與 TranslationService。

use std::io::Read;
use std::path::PathBuf;

use serde_json::Value;
use srt_translator::text::opencc::s2twp;

fn load(rel: &str) -> Value {
    let raw = std::fs::read(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden").join(rel)).unwrap();
    let mut text = String::new();
    flate2::read::GzDecoder::new(&raw[..]).read_to_string(&mut text).unwrap();
    serde_json::from_str(&text).unwrap()
}

#[test]
fn opencc_s2twp_matches_python() {
    let mut mismatches = Vec::new();
    for case in load("opencc.json.gz").as_array().unwrap() {
        let input = case["input"].as_str().unwrap();
        let actual = s2twp(input);
        if actual != case["output"].as_str().unwrap() {
            mismatches.push(format!("{input:?}\n    rust:   {actual:?}\n    python: {:?}", case["output"]));
        }
    }
    assert!(
        mismatches.is_empty(),
        "{} 項不一致\n{}",
        mismatches.len(),
        mismatches[..mismatches.len().min(8)].join("\n")
    );
}

use std::sync::{Arc, Mutex};

use srt_translator::cache::md5_hex;
use srt_translator::client::{ClientOptions, LlmType, NetflixStyleConfig, TranslationClient};
use srt_translator::config::{ConfigFile, ConfigKind};
use srt_translator::glossary::GlossaryManager;
use srt_translator::output::OutputSettings;
use srt_translator::prompt::PromptManager;
use srt_translator::service::heuristics::{self, RuntimeSettings};
use srt_translator::service::{DisplayMode, FileJob, ServiceSettings, TranslationService};
use wiremock::matchers::{method, path_regex};
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

struct Mismatches(Vec<String>);

impl Mismatches {
    fn check<T: PartialEq + std::fmt::Debug>(&mut self, label: impl std::fmt::Display, actual: T, expected: T) {
        if actual != expected {
            self.0.push(format!("{label}\n    rust:   {actual:?}\n    python: {expected:?}"));
        }
    }

    fn assert_empty(self, what: &str) {
        assert!(self.0.is_empty(), "{what}: {} 項不一致\n{}", self.0.len(), self.0[..self.0.len().min(8)].join("\n"));
    }
}

#[test]
fn heuristics_match_python() {
    let g = load("service.json.gz");
    let settings = RuntimeSettings::default();
    let no_smart = RuntimeSettings { smart_context_enabled: false, ..settings };
    let mut m = Mismatches(Vec::new());
    for c in g["heuristics"].as_array().unwrap() {
        let t = c["text"].as_str().unwrap();
        m.check(format!("ascii_ratio {t:?}"), heuristics::ascii_letter_ratio(t), c["ascii_ratio"].as_f64().unwrap());
        m.check(format!("needs_context {t:?}"), heuristics::text_needs_context(t), c["needs_context"] == true);
        m.check(format!("context_free {t:?}"), heuristics::is_context_free_short_text(t), c["context_free"] == true);
        m.check(
            format!("batch_safe_en {t:?}"),
            heuristics::is_batch_safe_short_text(t, Some("英文")),
            c["batch_safe_en"] == true,
        );
        m.check(
            format!("batch_safe_none {t:?}"),
            heuristics::is_batch_safe_short_text(t, None),
            c["batch_safe_none"] == true,
        );
        m.check(
            format!("batch_safe_ja {t:?}"),
            heuristics::is_batch_safe_short_text(t, Some("日文")),
            c["batch_safe_ja"] == true,
        );
        let w = |s: &RuntimeSettings, lang| heuristics::context_window_for_text(t, s, lang) as u64;
        m.check(format!("window_en {t:?}"), w(&settings, Some("英文")), c["window_en"].as_u64().unwrap());
        m.check(format!("window_ja {t:?}"), w(&settings, Some("日文")), c["window_ja"].as_u64().unwrap());
        m.check(format!("window_no_smart {t:?}"), w(&no_smart, None), c["window_no_smart"].as_u64().unwrap());
    }
    m.assert_empty("heuristics");
}

fn offline_client(dir: &std::path::Path) -> (TranslationClient, Arc<PromptManager>) {
    let pm = Arc::new(PromptManager::open(dir).unwrap());
    let mut options = ClientOptions::new(LlmType::Llamacpp);
    options.base_url = Some("http://127.0.0.1:9".into());
    (TranslationClient::new(options, pm.clone(), None), pm)
}

#[test]
fn post_processing_matches_python() {
    let g = load("service.json.gz");
    let dir = tempfile::tempdir().unwrap();
    let mut m = Mismatches(Vec::new());
    for c in g["post_process"].as_array().unwrap() {
        let mut glossary = GlossaryManager::open(dir.path().join("glossaries")).unwrap();
        if glossary.get("golden").is_none() {
            glossary.create("golden", "", "", "").unwrap();
            glossary.add_entry("golden", "Fire Department", "消防局", "", "", false).unwrap();
            glossary.add_entry("golden", "CPR", "心肺復甦術", "", "", true).unwrap();
        }
        if c["glossary"] == true {
            glossary.activate("golden");
        }
        let settings = ServiceSettings {
            runtime: RuntimeSettings::default(),
            preserve_punctuation: c["preserve_punctuation"] == true,
        };
        let (client, pm) = offline_client(dir.path());
        let service = TranslationService::new(client, pm, None, Some(glossary), settings);
        let (o, t) = (c["original"].as_str().unwrap(), c["translated"].as_str().unwrap());
        m.check(format!("post {c}"), service.post_process_translation(o, t).as_str(), c["output"].as_str().unwrap());
    }
    m.assert_empty("post_process");
}

fn fake_line(src: &str) -> String {
    let digest = &md5_hex(src)[..4];
    let mut mood = String::new();
    if src.contains('?') || src.contains('？') {
        mood.push('？');
    }
    if src.contains('!') || src.contains('！') {
        mood.push('！');
    }
    format!("这是译文{digest}{mood}。")
}

/// 與 gen_golden.py 的 `fake_reply` 相同的決定性假模型。
fn fake_reply(body: &Value) -> String {
    let messages = body["messages"].as_array().unwrap();
    let user = messages.last().unwrap()["content"].as_str().unwrap();
    if user.starts_with("[BATCH:") {
        let lines: Vec<&str> = user.split('\n').skip(1).collect();
        let mut out: Vec<String> = lines.iter().map(|l| fake_line(l)).collect();
        if lines.iter().any(|l| l.contains("BADBATCH")) {
            out.pop();
        }
        return out.join("\n");
    }
    fake_line(user)
}

struct FakeModel(Arc<Mutex<Vec<Value>>>);

impl Respond for FakeModel {
    fn respond(&self, request: &Request) -> ResponseTemplate {
        let body: Value = serde_json::from_slice(&request.body).unwrap();
        let reply = fake_reply(&body);
        self.0.lock().unwrap().push(body);
        ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "choices": [{"finish_reason": "stop", "message": {"content": reply}}],
        }))
    }
}

/// 鍵排序後的 JSON 字串，用來把兩邊的請求清單排成相同順序。
fn canonical(v: &Value) -> String {
    match v {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let items: Vec<String> = keys.iter().map(|k| format!("{k:?}:{}", canonical(&map[*k]))).collect();
            format!("{{{}}}", items.join(","))
        }
        Value::Array(a) => format!("[{}]", a.iter().map(canonical).collect::<Vec<_>>().join(",")),
        other => other.to_string(),
    }
}

#[tokio::test]
async fn subtitle_file_translation_matches_python() {
    let g = load("service.json.gz");
    let mut m = Mismatches(Vec::new());
    for case in g["files"].as_array().unwrap() {
        let server = MockServer::start().await;
        let calls = Arc::new(Mutex::new(Vec::new()));
        Mock::given(method("POST"))
            .and(path_regex("chat/completions$"))
            .respond_with(FakeModel(calls.clone()))
            .mount(&server)
            .await;

        let dir = tempfile::tempdir().unwrap();
        let cfg = dir.path().join("config");
        let mut pm = PromptManager::open(&cfg).unwrap();
        pm.current_content_type = case["content_type"].as_str().unwrap().into();
        pm.current_language_pair = case["language_pair"].as_str().unwrap().into();
        let pm = Arc::new(pm);

        let llm_type = LlmType::parse(case["llm_type"].as_str().unwrap()).unwrap();
        let mut options = ClientOptions::new(llm_type);
        options.base_url =
            Some(if llm_type == LlmType::Llamacpp { server.uri() } else { format!("{}/v1", server.uri()) });
        options.api_key = Some("sk-test".into());
        options.netflix_style = NetflixStyleConfig { enabled: case["netflix"] == true, ..Default::default() };
        let client = TranslationClient::new(options, pm.clone(), None);
        let settings = ServiceSettings {
            runtime: RuntimeSettings { batch_size: case["batch_size"].as_i64().unwrap(), ..Default::default() },
            preserve_punctuation: true,
        };
        let service = TranslationService::new(client, pm, None, None, settings);

        let input = dir.path().join(format!("{}_input.srt", case["fixture"].as_str().unwrap()));
        std::fs::write(&input, case["input"].as_str().unwrap()).unwrap();
        let job = FileJob {
            source_lang: case["source_lang"].as_str().unwrap().into(),
            target_lang: "繁體中文".into(),
            model_name: case["model"].as_str().unwrap().into(),
            parallel_requests: 3,
            display_mode: DisplayMode::parse(case["display_mode"].as_str().unwrap()),
            use_structure_text: case["structure"] == true,
            use_cache: false,
        };
        let output = OutputSettings::from_config(&ConfigFile::load(&cfg, ConfigKind::File).unwrap());
        let label = format!(
            "{} {} structure={} batch={}",
            case["llm_type"], case["model"], case["structure"], case["batch_size"]
        );
        match service.translate_subtitle_file(&input, &job, &output, &|_, _| {}, None).await {
            Ok(outcome) => {
                m.check(
                    format!("name {label}"),
                    outcome.output_path.file_name().unwrap().to_str(),
                    case["output_name"].as_str(),
                );
                m.check(
                    format!("output {label}"),
                    std::fs::read_to_string(&outcome.output_path).unwrap().as_str(),
                    case["output"].as_str().unwrap(),
                );
            }
            Err(e) => m.check(format!("success {label}"), format!("error: {e}"), "success".into()),
        }
        let mut actual: Vec<String> = calls.lock().unwrap().iter().map(canonical).collect();
        let mut expected: Vec<String> = case["calls"].as_array().unwrap().iter().map(canonical).collect();
        actual.sort();
        expected.sort();
        m.check(format!("request count {label}"), actual.len(), expected.len());
        for (i, (a, e)) in actual.iter().zip(&expected).enumerate() {
            m.check(format!("request #{i} {label}"), a, e);
        }
    }
    m.assert_empty("subtitle file translation");
}
