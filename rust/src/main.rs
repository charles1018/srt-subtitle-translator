//! CLI 入口（對等 Python `cli.py`）。目前已移植：extract / assemble / qa / cps-audit / version。

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use serde_json::Value;
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
}

fn main() -> ExitCode {
    let Some(command) = Cli::parse().command else {
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
