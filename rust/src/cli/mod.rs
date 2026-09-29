//! `translate` / `models` / `glossary` 子命令（對等 Python `cli.py` 的 cmd_translate / cmd_models / cmd_glossary）。

pub mod logger;

use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use log::{error, info, warn};
use srt_translator::cache::CacheManager;
use srt_translator::client::{ClientOptions, LlmType, NetflixStyleConfig, TranslationClient};
use srt_translator::config::{resolve_config_dir, ConfigFile, ConfigKind};
use srt_translator::glossary::GlossaryManager;
use srt_translator::models;
use srt_translator::output::{ConflictChoice, OutputSettings};
use srt_translator::prompt::{PromptManager, LANGUAGE_PAIRS};
use srt_translator::service::{DisplayMode, FileJob, ServiceSettings, TranslationService};
use srt_translator::Result;

pub const GLOSSARY_DIR: &str = "data/glossaries";
const SUPPORTED_EXTENSIONS: [&str; 4] = ["srt", "vtt", "ass", "ssa"];

/// `translate` 子命令參數。
pub struct TranslateArgs {
    pub inputs: Vec<PathBuf>,
    pub source: String,
    pub target: String,
    pub provider: String,
    pub model: Option<String>,
    pub content_type: Option<String>,
    pub style: Option<String>,
    pub display_mode: String,
    pub concurrency: usize,
    pub output_dir: Option<PathBuf>,
    pub no_cache: bool,
    pub netflix_style: Option<bool>,
    pub glossaries: Vec<String>,
    pub quiet: bool,
    pub structure_text: bool,
}

fn is_supported(path: &Path) -> bool {
    path.extension().is_some_and(|e| SUPPORTED_EXTENSIONS.contains(&e.to_string_lossy().to_lowercase().as_str()))
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    let mut paths: Vec<PathBuf> = entries.filter_map(|e| e.ok().map(|e| e.path())).collect();
    paths.sort();
    for p in paths {
        if p.is_dir() {
            walk(&p, out);
        } else if is_supported(&p) {
            out.push(std::path::absolute(&p).unwrap_or(p));
        }
    }
}

/// 收集要翻譯的檔案（目錄遞迴，依路徑排序）。
pub fn collect_files(inputs: &[PathBuf]) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for input in inputs {
        if input.is_file() {
            if is_supported(input) {
                files.push(std::path::absolute(input).unwrap_or_else(|_| input.clone()));
            } else {
                warn!("不支援的檔案格式: {}", input.display());
            }
        } else if input.is_dir() {
            walk(input, &mut files);
        } else {
            warn!("路徑不存在: {}", input.display());
        }
    }
    files
}

fn print_progress(current: usize, total: usize) {
    if total == 0 {
        return;
    }
    let filled = 40 * current / total;
    let bar = format!("{}{}", "█".repeat(filled), "░".repeat(40 - filled));
    print!("\r進度: [{bar}] {}% ({current}/{total})", 100 * current / total);
    if current == total {
        println!();
    }
    let _ = std::io::stdout().flush();
}

/// 輸出檔名衝突時詢問使用者；非互動環境自動改名（與 Python 相同）。
fn ask_conflict(path: &Path) -> ConflictChoice {
    if !std::io::stdin().is_terminal() {
        warn!("輸出檔案已存在，非互動環境自動改名: {}", path.display());
        return ConflictChoice::Rename;
    }
    println!("\n輸出檔案已存在: {}", path.display());
    println!("請選擇動作: [o] 覆蓋  [r] 重新命名  [s] 跳過");
    loop {
        print!("請輸入 o/r/s（預設 r）: ");
        let _ = std::io::stdout().flush();
        let mut line = String::new();
        let _ = std::io::stdin().read_line(&mut line);
        match line.trim().to_lowercase().as_str() {
            "" | "r" => return ConflictChoice::Rename,
            "o" => return ConflictChoice::Overwrite,
            "s" => return ConflictChoice::Skip,
            _ => println!("無效選項，請輸入 o、r 或 s。"),
        }
    }
}

pub fn open_cache(config_dir: &Path) -> Result<CacheManager> {
    let config = ConfigFile::load(config_dir, ConfigKind::Cache)?;
    let db_path = config.get_str("db_path").unwrap_or("data/translation_cache.db").to_string();
    let max_memory = config.get_i64("max_memory_cache").filter(|v| *v > 0).unwrap_or(1000) as usize;
    let cleanup_days = config.get_i64("auto_cleanup_days").filter(|v| *v > 0).unwrap_or(30);
    CacheManager::open(db_path, max_memory, cleanup_days)
}

pub fn ensure_runtime_dirs() {
    for dir in ["data", "config", "logs"] {
        let _ = std::fs::create_dir_all(dir);
    }
}

/// 執行翻譯；回傳是否全部成功。
///
/// 與 Python 的差異：`-o/--output-dir` 只作用於本次執行，不會寫回 `file_handler_config.json`。
pub async fn cmd_translate(args: TranslateArgs) -> Result<bool> {
    ensure_runtime_dirs();
    let files = collect_files(&args.inputs);
    if files.is_empty() {
        error!("找不到可翻譯的字幕檔案");
        return Ok(false);
    }
    info!("找到 {} 個檔案待翻譯", files.len());

    let config_dir = resolve_config_dir(None);
    let user = ConfigFile::load(&config_dir, ConfigKind::User)?;
    let model_config = ConfigFile::load(&config_dir, ConfigKind::Model)?;
    let file_config = ConfigFile::load(&config_dir, ConfigKind::File)?;

    // 本次執行的覆寫（不寫回設定檔）
    let mut prompt = PromptManager::open(&config_dir)?;
    if let Some(ct) = &args.content_type {
        prompt.current_content_type = ct.clone();
    }
    if let Some(style) = &args.style {
        prompt.current_style = style.clone();
    }
    let pair = format!("{}→{}", args.source, args.target);
    if LANGUAGE_PAIRS.iter().any(|(name, _, _)| *name == pair) {
        prompt.current_language_pair = pair;
    } else {
        warn!("未支援的語言對 {pair}，沿用 {}", prompt.current_language_pair);
    }
    let prompt = Arc::new(prompt);

    let model_name = args.model.clone().unwrap_or_else(|| {
        let m = models::recommended_model(&args.provider).to_string();
        info!("使用推薦模型: {m}");
        m
    });

    let mut output = OutputSettings::from_config(&file_config);
    if let Some(dir) = &args.output_dir {
        output.output_directory = dir.to_string_lossy().into_owned();
    }

    let mut glossary = GlossaryManager::open(GLOSSARY_DIR)?;
    for name in &args.glossaries {
        if glossary.activate(name) {
            info!("已啟用術語表: {name}");
        } else {
            warn!("找不到術語表: {name}");
        }
    }

    let cache = Arc::new(open_cache(&config_dir)?);
    let llm_type = LlmType::parse(&args.provider).expect("clap 已驗證 provider");
    let mut options = ClientOptions::new(llm_type);
    if llm_type == LlmType::Llamacpp {
        options.base_url = model_config.get_str("llamacpp_url").map(str::to_string);
    }
    options.api_key = models::load_api_key(&args.provider);
    options.openai_max_requests_per_minute =
        model_config.get_i64("openai_max_requests_per_minute").filter(|v| *v > 0).unwrap_or(500) as u64;
    options.openai_max_tokens_per_minute =
        model_config.get_i64("openai_max_tokens_per_minute").filter(|v| *v > 0).unwrap_or(200_000) as u64;
    options.netflix_style = NetflixStyleConfig {
        enabled: args.netflix_style.unwrap_or_else(|| user.get_bool("netflix_style_enabled", false)),
        ..Default::default()
    };
    let client = TranslationClient::new(options, prompt.clone(), Some(cache.clone()));
    let service =
        TranslationService::new(client, prompt, Some(cache), Some(glossary), ServiceSettings::from_user_config(&user));

    let job = FileJob {
        source_lang: args.source.clone(),
        target_lang: args.target.clone(),
        model_name,
        parallel_requests: args.concurrency,
        display_mode: DisplayMode::parse(&args.display_mode),
        use_structure_text: args.structure_text,
        use_cache: !args.no_cache,
    };
    let quiet_progress = |_: usize, _: usize| {};
    let progress: &(dyn Fn(usize, usize) + Sync) = if args.quiet { &quiet_progress } else { &print_progress };
    let ask: Option<&dyn Fn(&Path) -> ConflictChoice> = if args.quiet { None } else { Some(&ask_conflict) };

    let (mut ok, mut failed) = (0, 0);
    for (i, file) in files.iter().enumerate() {
        let name = file.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        info!("[{}/{}] 翻譯: {name}", i + 1, files.len());
        match service.translate_subtitle_file(file, &job, &output, progress, ask).await {
            Ok(outcome) => {
                if outcome.failed > 0 {
                    warn!(
                        "翻譯部分完成 | 成功 {}/{}，失敗 {}（耗時 {}）",
                        outcome.successful, outcome.total, outcome.failed, outcome.elapsed
                    );
                }
                info!("✓ 完成: {}", outcome.output_path.display());
                ok += 1;
            }
            Err(e) => {
                error!("✗ 失敗: {e}");
                failed += 1;
            }
        }
    }
    info!("\n翻譯完成: 成功 {ok} 個, 失敗 {failed} 個");
    Ok(failed == 0)
}

/// 列出 provider 可用模型。
pub async fn cmd_models(provider: &str) -> Result<bool> {
    let config_dir = resolve_config_dir(None);
    let model_config = ConfigFile::load(&config_dir, ConfigKind::Model)?;
    let url = model_config.get_str("llamacpp_url").unwrap_or("http://localhost:8080").to_string();
    let key = models::load_api_key(provider);
    let list = models::list_models(provider, &url, key.as_deref()).await;
    if list.is_empty() {
        println!("\n{provider} 沒有可用的模型");
    } else {
        println!("\n{provider} 可用模型:");
        println!("{}", "-".repeat(40));
        for m in list {
            println!("  • {m}");
        }
        println!();
    }
    Ok(true)
}

/// glossary 子命令。
pub enum GlossaryCommand {
    List,
    Create { name: String, source: String, target: String, description: String },
    Show { name: String },
    Add { glossary: String, source: String, target: String, category: String, notes: String },
    Remove { glossary: String, source: String },
    Delete { name: String },
    Import { file: PathBuf, name: Option<String> },
    Export { name: String, file: PathBuf, format: String },
    Activate { name: String },
    Deactivate { name: String },
}

/// 管理術語表。注意：啟用狀態只存在於單次執行（與 Python 相同），翻譯時請用 `translate -g`。
pub fn cmd_glossary(command: Option<GlossaryCommand>) -> Result<bool> {
    let Some(command) = command else {
        println!("請指定術語表操作，使用 --help 查看可用選項");
        return Ok(false);
    };
    ensure_runtime_dirs();
    let mut m = GlossaryManager::open(GLOSSARY_DIR)?;
    match command {
        GlossaryCommand::List => {
            let names: Vec<String> = m.list().into_iter().map(str::to_string).collect();
            if names.is_empty() {
                println!("\n目前沒有任何術語表\n");
            } else {
                println!("\n術語表列表:");
                println!("{}", "-".repeat(50));
                let active: Vec<String> = m.active().map(str::to_string).collect();
                for name in names {
                    let g = m.get(&name).expect("list 回傳的名稱必定存在");
                    let mark = if active.contains(&name) { "✓" } else { " " };
                    println!("  [{mark}] {name} ({} 條目)", g.entries.len());
                    if !g.source_lang.is_empty() || !g.target_lang.is_empty() {
                        println!("      {} → {}", g.source_lang, g.target_lang);
                    }
                }
                println!();
            }
        }
        GlossaryCommand::Create { name, source, target, description } => {
            match m.create(&name, &source, &target, &description) {
                Ok(g) => println!("已建立術語表: {}", g.name),
                Err(e) => {
                    error!("{e}");
                    return Ok(false);
                }
            }
        }
        GlossaryCommand::Show { name } => {
            let Some(g) = m.get(&name) else {
                error!("找不到術語表: {name}");
                return Ok(false);
            };
            println!("\n術語表: {}", g.name);
            println!("{}", "-".repeat(50));
            if !g.description.is_empty() {
                println!("說明: {}", g.description);
            }
            if !g.source_lang.is_empty() {
                println!("來源語言: {}", g.source_lang);
            }
            if !g.target_lang.is_empty() {
                println!("目標語言: {}", g.target_lang);
            }
            println!("條目數: {}\n", g.entries.len());
            if !g.entries.is_empty() {
                println!("條目:");
                for e in g.entries.values() {
                    let category = if e.category.is_empty() { String::new() } else { format!(" [{}]", e.category) };
                    println!("  {} → {}{category}", e.source, e.target);
                }
            }
            println!();
        }
        GlossaryCommand::Add { glossary, source, target, category, notes } => {
            if !m.add_entry(&glossary, &source, &target, &category, &notes, false)? {
                error!("找不到術語表: {glossary}");
                return Ok(false);
            }
            println!("已新增術語: {source} → {target}");
        }
        GlossaryCommand::Remove { glossary, source } => {
            if !m.remove_entry(&glossary, &source)? {
                error!("找不到術語或術語表: {glossary}/{source}");
                return Ok(false);
            }
            println!("已移除術語: {source}");
        }
        GlossaryCommand::Delete { name } => {
            print!("確定要刪除術語表 '{name}' 嗎？(y/N): ");
            let _ = std::io::stdout().flush();
            let mut answer = String::new();
            let _ = std::io::stdin().read_line(&mut answer);
            if answer.trim().eq_ignore_ascii_case("y") {
                if !m.delete(&name)? {
                    error!("找不到術語表: {name}");
                    return Ok(false);
                }
                println!("已刪除術語表: {name}");
            } else {
                println!("取消操作");
            }
        }
        GlossaryCommand::Import { file, name } => {
            let g = m.import(&file, name.as_deref())?;
            println!("已匯入術語表: {} ({} 條目)", g.name, g.entries.len());
        }
        GlossaryCommand::Export { name, file, format } => {
            if !m.export(&name, &file, &format)? {
                return Ok(false);
            }
            println!("已匯出術語表到: {}", file.display());
        }
        GlossaryCommand::Activate { name } => {
            if !m.activate(&name) {
                error!("找不到術語表: {name}");
                return Ok(false);
            }
            println!("已啟用術語表: {name}");
        }
        GlossaryCommand::Deactivate { name } => {
            if !m.deactivate(&name) {
                error!("術語表未啟用或不存在: {name}");
                return Ok(false);
            }
            println!("已停用術語表: {name}");
        }
    }
    Ok(true)
}
