//! SRT 字幕工具 — 結構-文本分離工作流（對等 Python `tools/srt_tools.py`）。
//!
//! 1. extract  — SRT → `_structure.json` + `_text.txt`
//! 2. 翻譯     — 只翻譯純文本
//! 3. assemble — `_structure.json` + `_translated_text.txt` → 翻譯後 SRT
//! 4. qa       — 驗證源檔與翻譯檔的結構完整性

use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use fancy_regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::{Details, Error, Result};
use crate::py;
use crate::subtitle::{SubIndex, SubRipFile, SubRipItem, SubRipTime};

// ─── 資料結構 ───────────────────────────────────────────────

/// 單一字幕的結構資訊（不含文本）。欄位順序即 JSON 輸出順序。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SubtitleStructure {
    pub index: Value,
    pub start: String,
    pub end: String,
    pub line_count: usize,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct QaResult {
    pub is_valid: bool,
    pub source_count: usize,
    pub target_count: usize,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SubtitleAuditEntry {
    pub index: Value,
    pub text: String,
    pub duration_ms: i64,
    pub char_count: usize,
    pub cps: f64,
    pub line_count: usize,
    pub max_line_length: usize,
    pub issues: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CpsSummary {
    pub high_cps: usize,
    pub long_line: usize,
    pub too_many_lines: usize,
    pub short_duration: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct CpsAuditReport {
    pub total_subtitles: usize,
    pub problematic_count: usize,
    pub entries: Vec<SubtitleAuditEntry>,
    pub avg_cps: f64,
    pub max_cps: f64,
    pub summary: CpsSummary,
}

#[derive(Debug, Clone, Copy)]
pub struct CpsAuditOptions {
    pub max_cps: f64,
    pub max_line_length: usize,
    pub max_lines: usize,
    pub min_duration_ms: i64,
}

impl Default for CpsAuditOptions {
    fn default() -> Self {
        Self { max_cps: 17.0, max_line_length: 22, max_lines: 2, min_duration_ms: 1000 }
    }
}

// ─── 內部輔助 ───────────────────────────────────────────────

fn open_srt(path: &Path) -> Result<SubRipFile> {
    SubRipFile::open(path)
}

/// 統一換行格式為 LF。
pub fn normalize_newlines(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}

/// 將字幕文字編碼成可安全存放於單行文本檔的格式。
pub fn encode_text_record(text: &str) -> String {
    normalize_newlines(text).replace('\\', "\\\\").replace('\n', "\\n")
}

/// 還原單行文本檔中的字幕文字。
pub fn decode_text_record(record: &str) -> String {
    let mut out = String::with_capacity(record.len());
    let mut chars = record.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next() {
            None => out.push('\\'),
            Some('n') => out.push('\n'),
            Some('\\') => out.push('\\'),
            Some(other) => {
                out.push('\\');
                out.push(other);
            }
        }
    }
    out
}

/// 讀取一行一字幕的文本檔，保留首尾空白字幕。
fn read_text_records(text: &str) -> Vec<String> {
    let normalized = normalize_newlines(text);
    if normalized.is_empty() {
        return Vec::new();
    }
    let body = normalized.strip_suffix('\n').unwrap_or(&normalized);
    body.split('\n').map(str::to_string).collect()
}

fn read_utf8(path: &Path) -> Result<String> {
    std::fs::read_to_string(path).map_err(|e| Error::file(format!("無法讀取檔案: {} ({e})", path.display())))
}

fn write_file(path: &Path, content: &str) -> Result<()> {
    std::fs::write(path, content).map_err(|e| Error::file(format!("無法寫入檔案: {} ({e})", path.display())))
}

/// `Path(p).with_suffix("")`
fn strip_suffix(path: &Path) -> PathBuf {
    path.with_extension("")
}

fn path_with_suffix(prefix: &Path, suffix: &str) -> PathBuf {
    let mut s = prefix.as_os_str().to_os_string();
    s.push(suffix);
    PathBuf::from(s)
}

// ─── extract ────────────────────────────────────────────────

/// 將 SRT 拆分為 `_structure.json` + `_text.txt`，回傳兩個輸出路徑。
pub fn extract(srt_path: &Path, output_prefix: Option<&Path>) -> Result<(PathBuf, PathBuf)> {
    if !srt_path.exists() {
        return Err(Error::file(format!("檔案不存在: {}", srt_path.display())));
    }
    let subs = open_srt(srt_path)?;
    if subs.is_empty() {
        return Err(Error::file(format!("SRT 檔案為空或無法解析: {}", srt_path.display())));
    }

    let prefix = output_prefix.map_or_else(|| strip_suffix(srt_path), Path::to_path_buf);

    let structure: Vec<SubtitleStructure> = subs
        .items
        .iter()
        .map(|sub| SubtitleStructure {
            index: sub.index.to_json(),
            start: sub.start.to_string(),
            end: sub.end.to_string(),
            line_count: sub.text.split('\n').count(),
        })
        .collect();
    let text_lines: Vec<String> = subs.items.iter().map(|s| encode_text_record(&s.text)).collect();

    let structure_path = path_with_suffix(&prefix, "_structure.json");
    let json = serde_json::to_string_pretty(&structure).expect("structure 序列化不會失敗");
    write_file(&structure_path, &json)?;

    let text_path = path_with_suffix(&prefix, "_text.txt");
    write_file(&text_path, &(text_lines.join("\n") + "\n"))?;

    Ok((structure_path, text_path))
}

// ─── assemble ───────────────────────────────────────────────

/// 將 `_structure.json` + 翻譯文本組合為 SRT，回傳輸出路徑。
pub fn assemble(base_prefix: &Path, text_suffix: &str, output_path: Option<&Path>) -> Result<PathBuf> {
    let structure_path = path_with_suffix(base_prefix, "_structure.json");
    let text_path = path_with_suffix(base_prefix, text_suffix);

    if !structure_path.exists() {
        return Err(Error::file(format!("結構檔案不存在: {}", structure_path.display())));
    }
    if !text_path.exists() {
        return Err(Error::file(format!("文本檔案不存在: {}", text_path.display())));
    }

    let structure: Vec<Value> = serde_json::from_str(&read_utf8(&structure_path)?)
        .map_err(|e| Error::file(format!("結構檔案格式錯誤: {} ({e})", structure_path.display())))?;
    let translated = read_text_records(&read_utf8(&text_path)?);

    if structure.len() != translated.len() {
        return Err(line_mismatch_error(structure.len(), &translated));
    }

    let mut file = SubRipFile::default();
    for (entry, line) in structure.iter().zip(&translated) {
        let time = |key: &str| -> Result<SubRipTime> {
            let raw = entry.get(key).and_then(Value::as_str).unwrap_or_default();
            SubRipTime::parse(raw).ok_or_else(|| Error::file(format!("無效的時間格式: {raw}")))
        };
        file.items.push(SubRipItem {
            index: SubIndex::from_json(entry.get("index").unwrap_or(&Value::Null)),
            start: time("start")?,
            end: time("end")?,
            text: decode_text_record(line),
            position: String::new(),
        });
    }

    let out = output_path.map_or_else(|| path_with_suffix(base_prefix, ".zh-TW.srt"), Path::to_path_buf);
    file.save(&out)?;
    Ok(out)
}

fn line_mismatch_error(structure_count: usize, translated: &[String]) -> Error {
    let translated_count = translated.len();
    let diff = translated_count as i64 - structure_count as i64;
    let message =
        format!("行數不匹配: 結構有 {structure_count} 個字幕，翻譯文本有 {translated_count} 行 (差異: {diff:+})");

    let mut details = Details::new();
    details.insert("structure_count".into(), structure_count.into());
    details.insert("translated_count".into(), translated_count.into());
    details.insert("diff".into(), diff.into());

    let min_len = structure_count.min(translated_count);
    if min_len > 0 {
        let context: Vec<Value> = (min_len.saturating_sub(3)..min_len)
            .map(|j| format!("  [{}] {}", j + 1, py::prefix(&translated[j], 60)).into())
            .collect();
        details.insert("last_aligned".into(), context.into());
        if translated_count > structure_count {
            let overflow: Vec<Value> = (structure_count..translated_count.min(structure_count + 5))
                .map(|j| format!("  [{}] {}", j + 1, py::prefix(&translated[j], 60)).into())
                .collect();
            details.insert("overflow_lines".into(), overflow.into());
        }
    }
    Error::validation(message, details)
}

// ─── qa ─────────────────────────────────────────────────────

/// 驗證源檔與翻譯檔的結構完整性。
pub fn qa(source: &Path, target: &Path) -> Result<QaResult> {
    if !source.exists() {
        return Err(Error::file(format!("來源檔案不存在: {}", source.display())));
    }
    if !target.exists() {
        return Err(Error::file(format!("目標檔案不存在: {}", target.display())));
    }
    let src = open_srt(source)?;
    let tgt = open_srt(target)?;

    let mut result = QaResult { source_count: src.len(), target_count: tgt.len(), ..Default::default() };

    if src.len() != tgt.len() {
        result.errors.push(format!("字幕數量不匹配: 來源 {} 個，目標 {} 個", src.len(), tgt.len()));
        return Ok(result);
    }

    let mut ts_mismatches = 0;
    let mut idx_mismatches = 0;
    for (i, (s, t)) in src.items.iter().zip(&tgt.items).enumerate() {
        if s.index != t.index {
            idx_mismatches += 1;
            if idx_mismatches <= 5 {
                result.warnings.push(format!("Index 不匹配 #{}: 來源={}, 目標={}", i + 1, s.index, t.index));
            }
        }
        if s.start.to_string() != t.start.to_string() || s.end.to_string() != t.end.to_string() {
            ts_mismatches += 1;
            if ts_mismatches <= 5 {
                result.warnings.push(format!(
                    "Timestamp 不匹配 #{}: 來源={} --> {}, 目標={} --> {}",
                    s.index, s.start, s.end, t.start, t.end
                ));
            }
        }
    }

    if ts_mismatches > 5 {
        result.warnings.push(format!("... 共 {ts_mismatches} 個 timestamp 不匹配"));
    }
    if idx_mismatches > 5 {
        result.warnings.push(format!("... 共 {idx_mismatches} 個 index 不匹配"));
    }
    if ts_mismatches > 0 {
        result.errors.push(format!("共 {ts_mismatches} 個 timestamp 不匹配"));
    }
    if idx_mismatches > 0 {
        result.errors.push(format!("共 {idx_mismatches} 個 index 不匹配"));
    }
    result.is_valid = result.errors.is_empty();
    Ok(result)
}

// ─── CPS 可讀性審計 ─────────────────────────────────────────

static TAG_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());

/// 移除 HTML/ASS 標籤，回傳純顯示文字。
pub fn strip_tags(text: &str) -> String {
    TAG_RE.replace_all(text, "").into_owned()
}

/// CPS / 可讀性審計。
pub fn cps_audit(srt_path: &Path, opts: CpsAuditOptions) -> Result<CpsAuditReport> {
    if !srt_path.exists() {
        return Err(Error::file(format!("檔案不存在: {}", srt_path.display())));
    }
    let subs = open_srt(srt_path)?;
    if subs.is_empty() {
        return Err(Error::file(format!("SRT 檔案為空或無法解析: {}", srt_path.display())));
    }

    let mut entries = Vec::new();
    let mut all_cps = Vec::with_capacity(subs.len());
    let mut summary = CpsSummary { high_cps: 0, long_line: 0, too_many_lines: 0, short_duration: 0 };
    let max_cps_repr = py::float_repr(opts.max_cps);

    for sub in &subs.items {
        let plain = strip_tags(&sub.text);
        let display_lines: Vec<&str> = sub.text.split('\n').collect();
        let line_count = display_lines.len();
        let max_len = display_lines.iter().map(|l| py::len(&strip_tags(l))).max().unwrap_or(0);

        let duration_ms = sub.end.ordinal - sub.start.ordinal;
        let duration_sec = (duration_ms as f64 / 1000.0).max(0.001);
        let char_count = py::len(&plain.replace('\n', ""));
        let cps = char_count as f64 / duration_sec;
        all_cps.push(cps);

        let mut issues = Vec::new();
        if cps > opts.max_cps {
            issues.push(format!("CPS={cps:.1} (>{max_cps_repr})"));
            summary.high_cps += 1;
        }
        if max_len > opts.max_line_length {
            issues.push(format!("行長={max_len} (>{})", opts.max_line_length));
            summary.long_line += 1;
        }
        if line_count > opts.max_lines {
            issues.push(format!("行數={line_count} (>{})", opts.max_lines));
            summary.too_many_lines += 1;
        }
        if duration_ms < opts.min_duration_ms {
            issues.push(format!("持續={duration_ms}ms (<{}ms)", opts.min_duration_ms));
            summary.short_duration += 1;
        }

        if !issues.is_empty() {
            entries.push(SubtitleAuditEntry {
                index: sub.index.to_json(),
                text: py::prefix(&plain, 60).to_string(),
                duration_ms,
                char_count,
                cps: py::round(cps, 2),
                line_count,
                max_line_length: max_len,
                issues,
            });
        }
    }

    let avg = all_cps.iter().sum::<f64>() / all_cps.len() as f64;
    let max = all_cps.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    Ok(CpsAuditReport {
        total_subtitles: subs.len(),
        problematic_count: entries.len(),
        entries,
        avg_cps: py::round(avg, 2),
        max_cps: py::round(max, 2),
        summary,
    })
}

// ─── 批次文本輔助函式 ────────────────────────────────────────

/// 每個字幕成為一行，內部換行以 literal `\n` 跳脫。
pub fn texts_to_batch_string<S: AsRef<str>>(texts: &[S]) -> String {
    texts.iter().map(|t| encode_text_record(t.as_ref())).collect::<Vec<_>>().join("\n")
}

/// 將 LLM 批次翻譯輸出轉回字幕文本列表；行數不符時回傳 `ValidationError`。
pub fn batch_string_to_texts(batch: &str, expected_count: usize) -> Result<Vec<String>> {
    let normalized = normalize_newlines(batch);
    let mut lines: Vec<&str> = normalized.split('\n').collect();
    if lines.len() == expected_count + 1 && lines.last() == Some(&"") {
        lines.pop();
    }
    if lines.len() != expected_count {
        let mut d = Details::new();
        d.insert("expected".into(), expected_count.into());
        d.insert("actual".into(), lines.len().into());
        return Err(Error::validation(format!("行數不匹配: 預期 {expected_count} 行，實際 {} 行", lines.len()), d));
    }
    Ok(lines.into_iter().map(decode_text_record).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_roundtrip() {
        for s in ["a\nb", "back\\slash", "\\n literal", "trailing\\", "", "  spaced  "] {
            assert_eq!(decode_text_record(&encode_text_record(s)), s);
        }
        assert_eq!(decode_text_record("a\\tb"), "a\\tb");
    }

    #[test]
    fn batch_string_count_validation() {
        let batch = texts_to_batch_string(&["一\n二", "三"]);
        assert_eq!(batch, "一\\n二\n三");
        assert_eq!(batch_string_to_texts(&(batch.clone() + "\n"), 2).unwrap(), vec!["一\n二", "三"]);
        assert!(batch_string_to_texts(&batch, 3).is_err());
    }

    #[test]
    fn extract_assemble_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("movie.srt");
        std::fs::write(
            &src,
            "1\n00:00:01,000 --> 00:00:02,000\nHello\nWorld\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n",
        )
        .unwrap();
        let (structure, text) = extract(&src, None).unwrap();
        assert_eq!(structure, dir.path().join("movie_structure.json"));
        assert_eq!(std::fs::read_to_string(&text).unwrap(), "Hello\\nWorld\nBye\n");

        std::fs::write(dir.path().join("movie_translated_text.txt"), "哈囉\\n世界\n再見\n").unwrap();
        let out = assemble(&dir.path().join("movie"), "_translated_text.txt", None).unwrap();
        assert_eq!(out, dir.path().join("movie.zh-TW.srt"));
        assert_eq!(
            std::fs::read_to_string(&out).unwrap(),
            "1\n00:00:01,000 --> 00:00:02,000\n哈囉\n世界\n\n2\n00:00:03,000 --> 00:00:04,000\n再見\n\n"
        );
        assert!(qa(&src, &out).unwrap().is_valid);
    }

    #[test]
    fn assemble_mismatch_reports_details() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("a.srt");
        std::fs::write(&src, "1\n00:00:01,000 --> 00:00:02,000\nx\n").unwrap();
        extract(&src, None).unwrap();
        std::fs::write(dir.path().join("a_translated_text.txt"), "一\n二\n").unwrap();
        let err = assemble(&dir.path().join("a"), "_translated_text.txt", None).unwrap_err();
        assert_eq!(err.to_string(), "[1900] 行數不匹配: 結構有 1 個字幕，翻譯文本有 2 行 (差異: +1)");
        assert_eq!(err.details()["overflow_lines"][0], "  [2] 二");
    }
}
