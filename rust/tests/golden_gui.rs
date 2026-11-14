//! GUI 設定讀寫 golden parity：與 `gen_golden.py::gui_settings_cases` 相同的事件順序。

use std::path::PathBuf;

use serde_json::Value;
use srt_translator::app::{set_user_value, sync_language_pair, GuiSettings};
use srt_translator::prompt::PromptManager;

fn golden() -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden/gui_settings.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn as_json(s: &GuiSettings) -> Value {
    serde_json::to_value(s).unwrap()
}

#[test]
fn gui_settings_roundtrip_matches_python() {
    let g = golden();
    let dir = tempfile::tempdir().unwrap();
    let cfg = dir.path();

    let initial = GuiSettings::load(cfg).unwrap();
    assert_eq!(as_json(&initial), g["initial"], "初始設定");

    let pair_results = vec![
        sync_language_pair(cfg, &initial.source_lang, &initial.target_lang).unwrap(),
        sync_language_pair(cfg, "英文", "繁體中文").unwrap(),
        sync_language_pair(cfg, "韓文", "韓文").unwrap(),
    ];
    assert_eq!(serde_json::to_value(pair_results).unwrap(), g["language_pair_results"]);

    let mut prompt = PromptManager::open(cfg).unwrap();
    assert!(prompt.set_content_type("english_drama").unwrap());
    assert!(prompt.set_translation_style("localized").unwrap());
    set_user_value(cfg, "display_mode", "僅顯示翻譯".into()).unwrap();
    set_user_value(cfg, "netflix_style_enabled", true.into()).unwrap();
    set_user_value(cfg, "structure_text_enabled", true.into()).unwrap();
    set_user_value(cfg, "last_directory", "/tmp/subs".into()).unwrap();
    GuiSettings {
        source_lang: "英文".into(),
        target_lang: "繁體中文".into(),
        llm_type: "openai".into(),
        model_name: "gpt-4.1-mini".into(),
        parallel_requests: "5".into(),
        display_mode: "僅顯示翻譯".into(),
        netflix_style_enabled: true,
        structure_text_enabled: true,
    }
    .save(cfg)
    .unwrap();

    assert_eq!(
        std::fs::read_to_string(cfg.join("user_settings.json")).unwrap(),
        g["user_settings"].as_str().unwrap(),
        "user_settings.json"
    );
    let mut prompt_config: Value =
        serde_json::from_str(&std::fs::read_to_string(cfg.join("prompt_config.json")).unwrap()).unwrap();
    prompt_config.as_object_mut().unwrap().shift_remove("last_updated");
    assert_eq!(prompt_config, g["prompt_config"], "prompt_config.json");
    assert_eq!(as_json(&GuiSettings::load(cfg).unwrap()), g["reloaded"], "重新載入");
}

#[test]
fn partial_user_settings_fill_defaults_like_python() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("user_settings.json"), r#"{"source_lang": "韓文", "parallel_requests": 10}"#)
        .unwrap();
    assert_eq!(as_json(&GuiSettings::load(dir.path()).unwrap()), golden()["partial_initial"]);
}
