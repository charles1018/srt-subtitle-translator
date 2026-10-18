//! CLI 入口（對等 Python `cli.py`）：translate / models / cache / config / glossary / prompt / extract / assemble / qa / cps-audit / version。

mod cli;

use std::path::PathBuf;
use std::process::ExitCode;

use clap::builder::PossibleValuesParser;
use clap::{Args, Parser, Subcommand};
use cli::{ensure_runtime_dirs, open_cache, GlossaryCommand, TranslateArgs};
use serde_json::Value;
use srt_translator::config::{resolve_config_dir, ConfigFile, ConfigKind};
use srt_translator::prompt::{PromptManager, CONTENT_TYPES, SUPPORTED_LLM_TYPES};
use srt_translator::py;
use srt_translator::tools::srt_tools::{self, CpsAuditOptions, CpsAuditReport};

#[derive(Parser)]
#[command(name = "srt-translator-rs", about = "SRT 字幕翻譯工具（Rust 移植版）")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// 顯示版本資訊
    Version,
    /// 從 SRT 提取結構與文本（結構-文本分離工作流）
    Extract {
        /// 輸入 SRT 檔案路徑
        input: PathBuf,
        /// 輸出檔案前綴 (預設: 輸入檔案名稱去除副檔名)
        #[arg(short, long)]
        output_prefix: Option<PathBuf>,
    },
    /// 將結構與翻譯文本組合為 SRT
    Assemble {
        /// 檔案前綴 (與 extract 輸出的相同)
        prefix: PathBuf,
        /// 翻譯文本檔案後綴 (預設: _translated_text.txt)
        #[arg(short, long)]
        text_file: Option<String>,
        /// 輸出 SRT 路徑 (預設: <prefix>.zh-TW.srt)
        #[arg(short, long)]
        output: Option<PathBuf>,
    },
    /// 驗證原始與翻譯字幕的結構完整性
    Qa {
        /// 原始 SRT 檔案路徑
        source: PathBuf,
        /// 翻譯後 SRT 檔案路徑
        target: PathBuf,
        /// 嚴格模式：警告視為錯誤
        #[arg(long)]
        strict: bool,
        /// 同時執行 CPS/可讀性審計
        #[arg(long)]
        cps: bool,
        /// CPS 上限
        #[arg(long, default_value_t = 17.0)]
        max_cps: f64,
        /// 單行字元上限
        #[arg(long, default_value_t = 22)]
        max_line_length: usize,
    },
    /// 字幕 CPS/可讀性審計
    CpsAudit {
        /// SRT 檔案路徑
        input: PathBuf,
        /// CPS 上限
        #[arg(long, default_value_t = 17.0)]
        max_cps: f64,
        /// 單行字元上限
        #[arg(long, default_value_t = 22)]
        max_line_length: usize,
        /// 行數上限
        #[arg(long, default_value_t = 2)]
        max_lines: usize,
        /// 最短持續時間 ms
        #[arg(long = "min-duration", default_value_t = 1000)]
        min_duration_ms: i64,
    },
    /// 翻譯字幕檔案
    Translate(TranslateCli),
    /// 列出可用模型
    Models {
        /// LLM 提供者
        #[arg(short, long, default_value = "llamacpp", value_parser = PossibleValuesParser::new(SUPPORTED_LLM_TYPES))]
        provider: String,
    },
    /// 管理術語表
    Glossary {
        #[command(subcommand)]
        command: Option<GlossaryCli>,
    },
    /// 管理翻譯快取
    Cache(CacheArgs),
    /// 顯示或設定配置
    Config {
        /// 顯示目前配置
        #[arg(long)]
        show: bool,
        /// 設定配置值
        #[arg(long, num_args = 2, value_names = ["KEY", "VALUE"])]
        set: Option<Vec<String>>,
    },
    /// 管理翻譯提示詞
    Prompt {
        #[command(subcommand)]
        command: Option<PromptCommand>,
    },
}

#[derive(Args)]
struct TranslateCli {
    /// 輸入檔案或目錄路徑
    #[arg(required = true)]
    input: Vec<PathBuf>,
    /// 來源語言 (如: 日文, 英文)
    #[arg(short, long)]
    source: String,
    /// 目標語言 (如: 繁體中文)
    #[arg(short, long)]
    target: String,
    /// LLM 提供者
    #[arg(short, long, default_value = "llamacpp", value_parser = PossibleValuesParser::new(SUPPORTED_LLM_TYPES))]
    provider: String,
    /// 模型名稱 (未指定則使用推薦模型)
    #[arg(short, long)]
    model: Option<String>,
    /// 內容類型
    #[arg(long, value_parser = PossibleValuesParser::new(CONTENT_TYPES))]
    content_type: Option<String>,
    /// 翻譯風格
    #[arg(long, value_parser = PossibleValuesParser::new(["standard", "literal", "localized", "specialized"]))]
    style: Option<String>,
    /// 顯示模式
    #[arg(short, long, default_value = "僅顯示翻譯",
          value_parser = PossibleValuesParser::new(["僅顯示翻譯", "雙語對照", "翻譯在上", "原文在上", "僅譯文"]))]
    display_mode: String,
    /// 並行請求數
    #[arg(short, long, default_value_t = 3)]
    concurrency: usize,
    /// 輸出目錄 (預設: 與輸入檔案同目錄)
    #[arg(short, long)]
    output_dir: Option<PathBuf>,
    /// 不使用翻譯快取
    #[arg(long)]
    no_cache: bool,
    /// 啟用 Netflix 風格後處理
    #[arg(long, conflicts_with = "no_netflix_style")]
    netflix_style: bool,
    /// 停用 Netflix 風格後處理
    #[arg(long)]
    no_netflix_style: bool,
    /// 使用指定術語表 (可多次指定)
    #[arg(short, long = "glossary")]
    glossary: Vec<String>,
    /// 安靜模式，僅顯示錯誤
    #[arg(short, long, conflicts_with = "verbose")]
    quiet: bool,
    /// 詳細輸出模式
    #[arg(short, long)]
    verbose: bool,
    /// 使用結構-文本分離翻譯模式（將多個字幕合併為單一批次，減少 API 呼叫）
    #[arg(long)]
    structure_text: bool,
}

#[derive(Subcommand)]
enum GlossaryCli {
    /// 列出所有術語表
    List,
    /// 建立新術語表
    Create {
        /// 術語表名稱
        name: String,
        /// 來源語言
        #[arg(short, long, default_value = "")]
        source: String,
        /// 目標語言
        #[arg(short, long, default_value = "")]
        target: String,
        /// 說明
        #[arg(short, long, default_value = "")]
        description: String,
    },
    /// 顯示術語表內容
    Show {
        /// 術語表名稱
        name: String,
    },
    /// 新增術語
    Add {
        /// 術語表名稱
        glossary: String,
        /// 來源術語
        source: String,
        /// 目標翻譯
        target: String,
        /// 分類
        #[arg(short, long, default_value = "")]
        category: String,
        /// 備註
        #[arg(short, long, default_value = "")]
        notes: String,
    },
    /// 移除術語
    Remove {
        /// 術語表名稱
        glossary: String,
        /// 來源術語
        source: String,
    },
    /// 刪除術語表
    Delete {
        /// 術語表名稱
        name: String,
    },
    /// 匯入術語表 (支援 .json, .csv, .txt)
    Import {
        /// 檔案路徑
        file: PathBuf,
        /// 術語表名稱 (預設使用檔案名稱)
        #[arg(short, long)]
        name: Option<String>,
    },
    /// 匯出術語表
    Export {
        /// 術語表名稱
        name: String,
        /// 輸出檔案路徑
        file: PathBuf,
        /// 輸出格式
        #[arg(short, long, default_value = "json", value_parser = PossibleValuesParser::new(["json", "csv", "txt"]))]
        format: String,
    },
    /// 啟用術語表（僅本次執行有效，翻譯時請用 translate -g）
    Activate {
        /// 術語表名稱
        name: String,
    },
    /// 停用術語表
    Deactivate {
        /// 術語表名稱
        name: String,
    },
}

impl From<GlossaryCli> for GlossaryCommand {
    fn from(c: GlossaryCli) -> Self {
        match c {
            GlossaryCli::List => Self::List,
            GlossaryCli::Create { name, source, target, description } => {
                Self::Create { name, source, target, description }
            }
            GlossaryCli::Show { name } => Self::Show { name },
            GlossaryCli::Add { glossary, source, target, category, notes } => {
                Self::Add { glossary, source, target, category, notes }
            }
            GlossaryCli::Remove { glossary, source } => Self::Remove { glossary, source },
            GlossaryCli::Delete { name } => Self::Delete { name },
            GlossaryCli::Import { file, name } => Self::Import { file, name },
            GlossaryCli::Export { name, file, format } => Self::Export { name, file, format },
            GlossaryCli::Activate { name } => Self::Activate { name },
            GlossaryCli::Deactivate { name } => Self::Deactivate { name },
        }
    }
}

#[derive(Args)]
#[group(required = true, multiple = false)]
struct CacheArgs {
    /// 顯示快取統計資訊
    #[arg(long)]
    stats: bool,
    /// 清除所有快取
    #[arg(long)]
    clear: bool,
    /// 最佳化快取資料庫
    #[arg(long)]
    optimize: bool,
    /// 匯出快取到指定檔案
    #[arg(long, value_name = "FILE")]
    export: Option<PathBuf>,
    /// 從指定檔案匯入快取
    #[arg(long = "import", value_name = "FILE")]
    import_file: Option<PathBuf>,
}

#[derive(Args)]
struct PromptTarget {
    /// 提示詞 provider
    #[arg(short, long, default_value = "llamacpp", value_parser = PossibleValuesParser::new(SUPPORTED_LLM_TYPES))]
    provider: String,
    /// 內容類型（未指定則使用目前 prompt 設定）
    #[arg(long, value_parser = PossibleValuesParser::new(CONTENT_TYPES))]
    content_type: Option<String>,
}

#[derive(Subcommand)]
enum PromptCommand {
    /// 顯示指定 provider/content type 的提示詞
    Show(PromptTarget),
    /// 設定指定 provider/content type 的提示詞
    Set {
        #[command(flatten)]
        target: PromptTarget,
        /// 直接指定提示詞文字
        #[arg(long, conflicts_with = "file", required_unless_present = "file")]
        text: Option<String>,
        /// 從 UTF-8 文字檔讀取提示詞
        #[arg(long)]
        file: Option<PathBuf>,
    },
    /// 將提示詞重置為預設值
    Reset(PromptTarget),
    /// 匯出提示詞到 JSON
    Export {
        /// 只匯出指定 provider；未指定則匯出所有支援 provider
        #[arg(short, long, value_parser = PossibleValuesParser::new(SUPPORTED_LLM_TYPES))]
        provider: Option<String>,
        /// 內容類型（未指定則使用目前 prompt 設定）
        #[arg(long, value_parser = PossibleValuesParser::new(CONTENT_TYPES))]
        content_type: Option<String>,
        /// 輸出 JSON 路徑
        #[arg(short, long)]
        output: PathBuf,
    },
    /// 從 JSON 匯入提示詞
    Import {
        /// 提示詞 JSON 路徑
        file: PathBuf,
    },
}

fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread().enable_all().build().expect("無法建立 tokio runtime")
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let level = match &cli.command {
        Some(Command::Translate(t)) if t.quiet => log::LevelFilter::Error,
        Some(Command::Translate(t)) if t.verbose => log::LevelFilter::Debug,
        _ => log::LevelFilter::Info,
    };
    cli::logger::init(level);
    let Some(command) = cli.command else {
        use clap::CommandFactory;
        let _ = Cli::command().print_help();
        return ExitCode::SUCCESS;
    };
    let result = match command {
        Command::Version => {
            println!("SRT Subtitle Translator v{} (Rust)", env!("CARGO_PKG_VERSION"));
            Ok(true)
        }
        Command::Extract { input, output_prefix } => {
            srt_tools::extract(&input, output_prefix.as_deref()).map(|(structure, text)| {
                println!("結構檔案: {}", structure.display());
                println!("文本檔案: {}", text.display());
                true
            })
        }
        Command::Assemble { prefix, text_file, output } => {
            let suffix = text_file.unwrap_or_else(|| "_translated_text.txt".into());
            srt_tools::assemble(&prefix, &suffix, output.as_deref()).map(|out| {
                println!("輸出檔案: {}", out.display());
                true
            })
        }
        Command::Qa { source, target, strict, cps, max_cps, max_line_length } => {
            cmd_qa(&source, &target, strict, cps, CpsAuditOptions { max_cps, max_line_length, ..Default::default() })
        }
        Command::CpsAudit { input, max_cps, max_line_length, max_lines, min_duration_ms } => {
            srt_tools::cps_audit(&input, CpsAuditOptions { max_cps, max_line_length, max_lines, min_duration_ms }).map(
                |report| {
                    print_cps_report(&report);
                    report.problematic_count == 0
                },
            )
        }
        Command::Translate(t) => {
            let netflix_style = if t.netflix_style {
                Some(true)
            } else if t.no_netflix_style {
                Some(false)
            } else {
                None
            };
            let args = TranslateArgs {
                inputs: t.input,
                source: t.source,
                target: t.target,
                provider: t.provider,
                model: t.model,
                content_type: t.content_type,
                style: t.style,
                display_mode: t.display_mode,
                concurrency: t.concurrency,
                output_dir: t.output_dir,
                no_cache: t.no_cache,
                netflix_style,
                glossaries: t.glossary,
                quiet: t.quiet,
                structure_text: t.structure_text,
            };
            runtime().block_on(cli::cmd_translate(args))
        }
        Command::Models { provider } => runtime().block_on(cli::cmd_models(&provider)),
        Command::Glossary { command } => cli::cmd_glossary(command.map(Into::into)),
        Command::Cache(args) => cmd_cache(&args),
        Command::Config { show, set } => cmd_config(show, set.as_deref()),
        Command::Prompt { command } => cmd_prompt(command),
    };
    match result {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::FAILURE,
        Err(e) => {
            println!("錯誤: {e}");
            ExitCode::FAILURE
        }
    }
}

fn cmd_cache(args: &CacheArgs) -> srt_translator::Result<bool> {
    ensure_runtime_dirs();
    let cache = open_cache(&resolve_config_dir(None))?;
    if args.stats {
        let report = cache.stats()?;
        println!("\n快取統計:");
        println!("{}", "-".repeat(40));
        println!("  總筆數: {}", report.total_records);
        println!("  資料庫大小: {:.2} MB", report.db_size_mb);
        for (model, count) in &report.models {
            println!("  {model}: {count} 筆");
        }
        println!();
    } else if args.clear {
        print!("確定要清除所有快取嗎？(y/N): ");
        use std::io::Write;
        let _ = std::io::stdout().flush();
        let mut answer = String::new();
        let _ = std::io::stdin().read_line(&mut answer);
        if answer.trim().eq_ignore_ascii_case("y") {
            cache.clear_all(false)?;
            println!("快取已清除");
        } else {
            println!("取消操作");
        }
    } else if args.optimize {
        cache.optimize()?;
        println!("快取資料庫已最佳化");
    } else if let Some(path) = &args.export {
        let count = cache.export(path)?;
        println!("快取已匯出至: {} ({count} 筆)", path.display());
    } else if let Some(path) = &args.import_file {
        let count = cache.import(path)?;
        println!("快取已從 {} 匯入 ({count} 筆)", path.display());
    }
    Ok(true)
}

/// Python 版 `--set` 的型別轉換：純數字 → int，true/false → bool，其餘為字串。
fn parse_config_value(raw: &str) -> Value {
    if !raw.is_empty() && raw.chars().all(|c| c.is_ascii_digit()) {
        if let Ok(n) = raw.parse::<i64>() {
            return Value::from(n);
        }
    }
    match raw.to_lowercase().as_str() {
        "true" => Value::Bool(true),
        "false" => Value::Bool(false),
        _ => Value::from(raw),
    }
}

fn cmd_config(show: bool, set: Option<&[String]>) -> srt_translator::Result<bool> {
    ensure_runtime_dirs();
    let mut user = ConfigFile::load(&resolve_config_dir(None), ConfigKind::User)?;
    if show {
        println!("\n目前配置:");
        println!("{}", "-".repeat(40));
        for (key, value) in &user.data {
            let shown = match value {
                Value::String(s) => s.clone(),
                other => py::repr(other),
            };
            println!("  {key}: {shown}");
        }
        println!();
    } else if let Some([key, raw]) = set {
        let value = parse_config_value(raw);
        let shown = match &value {
            Value::String(s) => s.clone(),
            other => py::repr(other),
        };
        user.set_and_save(key, value)?;
        println!("已設定 {key} = {shown}");
    }
    Ok(true)
}

fn cmd_prompt(command: Option<PromptCommand>) -> srt_translator::Result<bool> {
    let Some(command) = command else {
        println!("請指定提示詞操作，使用 --help 查看可用選項");
        return Ok(false);
    };
    ensure_runtime_dirs();
    let mut pm = PromptManager::open(&resolve_config_dir(None))?;
    match command {
        PromptCommand::Show(t) => println!("{}", pm.get_prompt(&t.provider, t.content_type.as_deref(), None, None)),
        PromptCommand::Set { target, text, file } => {
            let text = match (text, file) {
                (Some(t), _) => t,
                (None, Some(f)) => std::fs::read_to_string(&f)
                    .map_err(|e| srt_translator::Error::file(format!("無法讀取提示詞檔案: {} ({e})", f.display())))?,
                (None, None) => unreachable!("clap 保證二擇一"),
            };
            pm.set_prompt(&text, &target.provider, target.content_type.as_deref())?;
            let ct = target.content_type.unwrap_or_else(|| pm.current_content_type.clone());
            println!("已更新 {ct}/{} 提示詞", target.provider);
        }
        PromptCommand::Reset(t) => {
            if !pm.reset_to_default(Some(&t.provider), t.content_type.as_deref())? {
                println!("錯誤: 提示詞重置失敗");
                return Ok(false);
            }
            let ct = t.content_type.unwrap_or_else(|| pm.current_content_type.clone());
            println!("已重置 {ct}/{} 提示詞為預設值", t.provider);
        }
        PromptCommand::Export { provider, content_type, output } => {
            let path = pm.export_prompt(content_type.as_deref(), provider.as_deref(), Some(&output))?;
            println!("提示詞已匯出到: {}", path.display());
        }
        PromptCommand::Import { file } => {
            pm.import_prompt(&file)?;
            println!("已匯入提示詞: {}", file.display());
        }
    }
    Ok(true)
}

fn cmd_qa(
    source: &std::path::Path,
    target: &std::path::Path,
    strict: bool,
    cps: bool,
    cps_opts: CpsAuditOptions,
) -> srt_translator::Result<bool> {
    let result = srt_tools::qa(source, target)?;
    println!("來源字幕: {} 個", result.source_count);
    println!("目標字幕: {} 個", result.target_count);
    if !result.errors.is_empty() {
        println!("\n錯誤:");
        result.errors.iter().for_each(|e| println!("  - {e}"));
    }
    if !result.warnings.is_empty() {
        println!("\n警告:");
        result.warnings.iter().for_each(|w| println!("  - {w}"));
    }
    let has_warnings = !result.warnings.is_empty();
    if result.is_valid {
        if strict && has_warnings {
            println!("\nQA 失敗（嚴格模式：有警告）");
        } else {
            println!("\nQA 通過");
        }
    } else {
        println!("\nQA 失敗");
    }
    if cps {
        println!("\n--- CPS/可讀性審計 ---");
        print_cps_report(&srt_tools::cps_audit(target, cps_opts)?);
    }
    Ok(result.is_valid && !(strict && has_warnings))
}

/// Python `str(index)`：int、str 或 None。
fn index_display(index: &Value) -> String {
    match index {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        other => other.to_string(),
    }
}

fn print_cps_report(report: &CpsAuditReport) {
    println!("總字幕數: {}", report.total_subtitles);
    println!("問題字幕: {}", report.problematic_count);
    println!("平均 CPS: {}", py::float_repr(report.avg_cps));
    println!("最高 CPS: {}", py::float_repr(report.max_cps));
    println!("\n問題統計:");
    let s = &report.summary;
    for (key, count) in [
        ("high_cps", s.high_cps),
        ("long_line", s.long_line),
        ("too_many_lines", s.too_many_lines),
        ("short_duration", s.short_duration),
    ] {
        if count > 0 {
            println!("  {key}: {count}");
        }
    }
    if !report.entries.is_empty() {
        println!("\n問題字幕詳情 (前 {} 筆):", report.entries.len().min(20));
        for entry in report.entries.iter().take(20) {
            println!("  #{} [{}] {}", index_display(&entry.index), entry.issues.join(", "), entry.text);
        }
    }
}
