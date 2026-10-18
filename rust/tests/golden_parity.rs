//! Golden parity 測試：比對 Rust 與 Python 實作在同一組輸入下的輸出。
//!
//! Golden 由 `rust/tools/gen_golden.py` 產生；Python 行為改變時需重新產生。

use std::path::{Path, PathBuf};

use serde_json::Value;
use srt_translator::glossary::Glossary;
use srt_translator::subtitle::SubRipFile;
use srt_translator::text::japanese;
use srt_translator::text::normalize;
use srt_translator::text::NetflixStylePostProcessor;
use srt_translator::tools::srt_tools::{self, CpsAuditOptions};

fn manifest_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn load(rel: &str) -> Option<Value> {
    let path = manifest_dir().join("tests/golden").join(rel);
    let text = std::fs::read_to_string(path).ok()?;
    Some(serde_json::from_str(&text).expect("golden JSON 格式錯誤"))
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or_else(|| panic!("預期字串: {v}"))
}

/// 收集所有不一致項目後一次回報，方便一次看清差異。
struct Mismatches(Vec<String>);

impl Mismatches {
    fn new() -> Self {
        Self(Vec::new())
    }

    fn check<T: PartialEq + std::fmt::Debug>(&mut self, label: impl std::fmt::Display, actual: T, expected: T) {
        if actual != expected {
            self.0.push(format!("{label}\n    rust:   {actual:?}\n    python: {expected:?}"));
        }
    }

    fn assert_empty(self, what: &str) {
        if !self.0.is_empty() {
            let shown: Vec<_> = self.0.iter().take(20).cloned().collect();
            panic!("{what}: {} 項不一致\n{}", self.0.len(), shown.join("\n"));
        }
    }
}

#[test]
fn post_processor_matches_python() {
    let cases = load("post_processor.json").unwrap();
    let mut m = Mismatches::new();
    for case in cases.as_array().unwrap() {
        let cfg = &case["config"];
        let processor = NetflixStylePostProcessor::new(
            cfg["auto_fix"].as_bool().unwrap(),
            cfg["strict_mode"].as_bool().unwrap(),
            cfg["max_chars_per_line"].as_u64().unwrap() as usize,
            cfg["max_lines"].as_u64().unwrap() as usize,
        );
        let input = s(&case["input"]);
        let result = processor.process(input);
        let label = format!("{input:?} cfg={cfg}");
        m.check(format!("text {label}"), result.text.as_str(), s(&case["text"]));
        m.check(format!("auto_fixed {label}"), result.auto_fixed as u64, case["auto_fixed"].as_u64().unwrap());
        m.check(format!("warnings {label}"), serde_json::to_value(&result.warnings).unwrap(), case["warnings"].clone());
        m.check(
            format!("formatted {label}"),
            NetflixStylePostProcessor::format_warnings(&result).as_str(),
            s(&case["formatted"]),
        );
    }
    m.assert_empty("post_processor");
}

#[test]
fn japanese_name_protection_matches_python() {
    let golden = load("japanese.json").unwrap();
    let mut m = Mismatches::new();
    for case in golden["names"].as_array().unwrap() {
        let input = s(&case["input"]);
        let contexts = vec![format!("{input}？"), "無關".to_string()];
        let expected_candidates: Vec<String> = serde_json::from_value(case["candidates"].clone()).unwrap();
        m.check(format!("candidates {input}"), japanese::extract_name_candidates(input), expected_candidates);

        let (protected, ctx, map) = japanese::protect_names(input, &contexts);
        m.check(format!("protected {input}"), protected.as_str(), s(&case["protected"]));
        let expected_ctx: Vec<String> = serde_json::from_value(case["contexts"].clone()).unwrap();
        m.check(format!("contexts {input}"), ctx, expected_ctx);
        let expected_map: Vec<(String, String)> = serde_json::from_value(case["restore_map"].clone()).unwrap();
        m.check(format!("restore_map {input}"), map.clone(), expected_map);
        m.check(format!("restored {input}"), japanese::restore_names(&protected, &map).as_str(), s(&case["restored"]));
        m.check(
            format!("mangled_restored {input}"),
            japanese::restore_names(s(&case["mangled"]), &map).as_str(),
            s(&case["mangled_restored"]),
        );
    }
    for case in golden["rejections"].as_array().unwrap() {
        let (src, tr) = (s(&case["source"]), s(&case["translated"]));
        m.check(
            format!("rejection {src:?} -> {tr:?}"),
            japanese::cache_rejection_reason(src, tr),
            case["reason"].as_str(),
        );
    }
    m.assert_empty("japanese");
}

#[test]
fn normalization_matches_python() {
    let g = load("normalize.json").unwrap();
    let mut m = Mismatches::new();
    for c in g["taiwan_terms"].as_array().unwrap() {
        let input = s(&c["input"]);
        m.check(
            format!("taiwan {input:?}"),
            normalize::normalize_taiwan_subtitle_terminology(input).as_str(),
            s(&c["output"]),
        );
    }
    for c in g["source_aware"].as_array().unwrap() {
        let (src, tr) = (s(&c["source"]), s(&c["translated"]));
        m.check(
            format!("source_aware {src:?}"),
            normalize::normalize_source_aware_subtitle_phrases(src, tr).as_str(),
            s(&c["output"]),
        );
    }
    for c in g["single_line"].as_array().unwrap() {
        let (src, tr) = (s(&c["source"]), s(&c["translated"]));
        m.check(
            format!("single_line {tr:?}"),
            normalize::clean_single_line_translation(src, tr).as_str(),
            s(&c["output"]),
        );
    }
    for c in g["sanitize"].as_array().unwrap() {
        let input = s(&c["input"]);
        m.check(format!("sanitize {input:?}"), normalize::sanitize_local_translation(input).as_str(), s(&c["output"]));
    }
    for c in g["structured"].as_array().unwrap() {
        let input = s(&c["input"]);
        m.check(
            format!("structured {input:?}"),
            normalize::extract_llamacpp_structured_translation(input).as_str(),
            s(&c["output"]),
        );
    }
    for c in g["records"].as_array().unwrap() {
        let input = s(&c["input"]);
        m.check(format!("encode {input:?}"), srt_tools::encode_text_record(input).as_str(), s(&c["encoded"]));
        m.check(format!("decode {input:?}"), srt_tools::decode_text_record(input).as_str(), s(&c["decoded"]));
    }
    m.assert_empty("normalize");
}

#[test]
fn glossary_matches_python() {
    let mut g = Glossary::new("g", "en", "zh-tw", "");
    g.add_entry("Fire", "火", "", "", false);
    g.add_entry("Fire Department", "消防局", "", "", false);
    g.add_entry("CPR", "心肺復甦術", "", "", true);
    g.add_entry("ÉCOLE", "學校", "", "", false);
    g.add_entry("a.b", "點", "", "", false);
    let mut m = Mismatches::new();
    for c in load("glossary.json").unwrap().as_array().unwrap() {
        let input = s(&c["input"]);
        m.check(format!("glossary {input:?}"), g.apply_to_text(input).as_str(), s(&c["output"]));
    }
    m.assert_empty("glossary");
}

fn fixture_path(file: &str) -> Option<PathBuf> {
    let repo = manifest_dir().parent().unwrap().to_path_buf();
    [
        repo.join("tests/e2e/fixtures").join(file),
        repo.join("tests/e2e/fixtures/batch").join(file),
        repo.join("data").join(file),
    ]
    .into_iter()
    .find(|p| p.exists())
}

fn check_srt_case(case: &Value, source: &Path, m: &mut Mismatches) {
    let file = s(&case["file"]);
    let dir = tempfile::tempdir().unwrap();
    let copy = dir.path().join(source.file_name().unwrap());
    std::fs::copy(source, &copy).unwrap();

    match SubRipFile::open(&copy) {
        Ok(subs) => {
            if case.get("open_error").is_some() {
                m.check(format!("{file} open"), "ok", "error");
            } else {
                let items: Vec<Value> = subs
                    .items
                    .iter()
                    .map(|it| {
                        serde_json::json!({
                            "index": it.index.to_json(),
                            "start": it.start.to_string(),
                            "end": it.end.to_string(),
                            "text": it.text,
                            "position": it.position,
                        })
                    })
                    .collect();
                m.check(format!("{file} items"), Value::from(items), case["items"].clone());
                m.check(format!("{file} serialized"), subs.to_srt_string(Some("\n")).as_str(), s(&case["serialized"]));
            }
        }
        Err(e) => m.check(format!("{file} open_error"), Some(e.error_code() as u64), case["open_error"].as_u64()),
    }

    match srt_tools::extract(&copy, None) {
        Ok((structure, text)) => {
            let ex = &case["extract"];
            m.check(
                format!("{file} structure"),
                std::fs::read_to_string(&structure).unwrap().as_str(),
                s(&ex["structure"]),
            );
            m.check(format!("{file} text"), std::fs::read_to_string(&text).unwrap().as_str(), s(&ex["text"]));
            let stem = copy.with_extension("");
            std::fs::copy(
                &text,
                dir.path().join(format!("{}_translated_text.txt", stem.file_name().unwrap().to_string_lossy())),
            )
            .unwrap();
            let out = srt_tools::assemble(&stem, "_translated_text.txt", None).unwrap();
            m.check(
                format!("{file} assembled"),
                std::fs::read_to_string(&out).unwrap().as_str(),
                s(&case["assembled"]),
            );
            let qa = srt_tools::qa(&copy, &out).unwrap();
            m.check(format!("{file} qa"), serde_json::to_value(&qa).unwrap(), case["qa"].clone());
        }
        Err(e) => m.check(format!("{file} extract_error"), Some(e.error_code() as u64), case["extract_error"].as_u64()),
    }

    match srt_tools::cps_audit(&copy, CpsAuditOptions::default()) {
        Ok(report) => {
            m.check(format!("{file} cps_audit"), serde_json::to_value(&report).unwrap(), case["cps_audit"].clone())
        }
        Err(e) => {
            m.check(format!("{file} cps_audit_error"), Some(e.error_code() as u64), case["cps_audit_error"].as_u64())
        }
    }
}

fn run_srt_golden(rel: &str) {
    let Some(cases) = load(rel) else {
        eprintln!("略過 {rel}（不存在，請以 --local 產生）");
        return;
    };
    let mut m = Mismatches::new();
    for case in cases.as_array().unwrap() {
        let file = s(&case["file"]);
        let Some(path) = fixture_path(file) else {
            eprintln!("略過 {file}（找不到來源檔）");
            continue;
        };
        check_srt_case(case, &path, &mut m);
    }
    m.assert_empty(rel);
}

#[test]
fn srt_tools_match_python_on_fixtures() {
    run_srt_golden("srt_files.json");
}

#[test]
fn srt_tools_match_python_on_local_data() {
    run_srt_golden("local/srt_files.json");
}

#[test]
fn post_processor_matches_python_on_local_data() {
    let Some(cases) = load("local/post_processor.json") else { return };
    let processor = NetflixStylePostProcessor::default();
    let mut m = Mismatches::new();
    for c in cases.as_array().unwrap() {
        let input = s(&c["input"]);
        m.check(format!("{input:?}"), processor.process(input).text.as_str(), s(&c["text"]));
    }
    m.assert_empty("local post_processor");
}
