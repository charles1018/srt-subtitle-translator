//! SRT 解析與輸出，行為對等於 pysrt 1.1.2（`SubRipFile.stream` / `SubRipItem.from_lines` / `write_into`），
//! 使用 `ERROR_PASS` 模式：無法解析的區塊直接略過。

use std::fmt;
use std::path::Path;

use serde_json::Value;

use super::time::SubRipTime;
use crate::error::{Error, Result};
use crate::py;

const TIMESTAMP_SEPARATOR: &str = "-->";

/// 字幕序號。pysrt 以 `int(index)` 轉換，失敗時保留原字串；沒有序號行時為 `None`。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SubIndex {
    Int(i64),
    Text(String),
    Missing,
}

impl SubIndex {
    fn from_raw(raw: Option<&str>) -> Self {
        match raw {
            None => Self::Missing,
            Some(s) => py::parse_int(s).map_or_else(|| Self::Text(s.to_string()), Self::Int),
        }
    }

    /// 對應 Python `json.dumps(sub.index)`。
    pub fn to_json(&self) -> Value {
        match self {
            Self::Int(i) => Value::from(*i),
            Self::Text(s) => Value::from(s.clone()),
            Self::Missing => Value::Null,
        }
    }

    /// 從 structure JSON 還原（`SubRipItem(index=...)` 對任意值做 `int()` 嘗試）。
    pub fn from_json(value: &Value) -> Self {
        match value {
            Value::Null => Self::Missing,
            Value::Number(n) => Self::Int(n.as_i64().unwrap_or_else(|| n.as_f64().unwrap_or(0.0) as i64)),
            Value::String(s) => Self::from_raw(Some(s)),
            Value::Bool(b) => Self::Int(i64::from(*b)),
            other => Self::Text(other.to_string()),
        }
    }
}

impl fmt::Display for SubIndex {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Int(i) => write!(f, "{i}"),
            Self::Text(s) => f.write_str(s),
            Self::Missing => f.write_str("None"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SubRipItem {
    pub index: SubIndex,
    pub start: SubRipTime,
    pub end: SubRipTime,
    pub text: String,
    pub position: String,
}

impl SubRipItem {
    pub fn new(index: i64, start: SubRipTime, end: SubRipTime, text: impl Into<String>) -> Self {
        Self { index: SubIndex::Int(index), start, end, text: text.into(), position: String::new() }
    }

    /// `SubRipItem.from_lines`；回傳 `None` 代表 pysrt 會拋出 `InvalidItem`/`InvalidTimeString`。
    fn from_lines(lines: &[&str]) -> Option<Self> {
        if lines.len() < 2 {
            return None;
        }
        let mut lines: Vec<&str> = lines.iter().map(|l| py::rstrip(l)).collect();
        let mut index = None;
        if !lines[0].contains(TIMESTAMP_SEPARATOR) {
            index = Some(lines.remove(0));
        }
        let (start, end, position) = split_timestamps(lines[0])?;
        let body = lines[1..].join("\n");
        Some(Self {
            index: SubIndex::from_raw(index),
            start: coerce_time(start)?,
            end: coerce_time(end)?,
            text: body,
            position: position.to_string(),
        })
    }
}

/// `SubRipTime.coerce(value or 0)`：空字串視為 0。
fn coerce_time(s: &str) -> Option<SubRipTime> {
    if s.is_empty() {
        return Some(SubRipTime::default());
    }
    SubRipTime::parse(s)
}

fn split_timestamps(line: &str) -> Option<(&str, &str, &str)> {
    let parts: Vec<&str> = line.split(TIMESTAMP_SEPARATOR).collect();
    if parts.len() != 2 {
        return None;
    }
    let end_and_position = py::lstrip(parts[1]);
    let (end, position) = match end_and_position.split_once(' ') {
        Some((e, p)) => (e, p),
        None => (end_and_position, ""),
    };
    Some((py::strip(parts[0]), py::strip(end), py::strip(position)))
}

impl fmt::Display for SubRipItem {
    /// `ITEM_PATTERN = '%s\n%s --> %s%s\n%s\n'`
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let position = if py::strip(&self.position).is_empty() { String::new() } else { format!(" {}", self.position) };
        write!(f, "{}\n{} --> {}{}\n{}\n", self.index, self.start, self.end, position, self.text)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SubRipFile {
    pub items: Vec<SubRipItem>,
    /// 原檔換行字元；新建檔案為 `None`，輸出時使用 `\n`（Linux 的 `os.linesep`）。
    pub eol: Option<String>,
}

impl SubRipFile {
    pub fn parse(source: &str) -> Self {
        let lines = py::splitlines(source, true);
        let eol = lines
            .first()
            .map(|first| ["\r\n", "\r", "\n"].into_iter().find(|e| first.ends_with(e)).unwrap_or("\n").to_string());
        Self { items: stream(&lines), eol }
    }

    /// 讀取並解析 SRT（自動偵測編碼）。
    pub fn open(path: &Path) -> Result<Self> {
        let (text, _) = super::encoding::read_text_file(path)?;
        Ok(Self::parse(&text))
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// `write_into`：每個項目若未以兩個 eol 結尾則補一個 eol。
    pub fn to_srt_string(&self, eol: Option<&str>) -> String {
        let eol = eol.or(self.eol.as_deref()).unwrap_or("\n");
        let mut out = String::new();
        for item in &self.items {
            let mut repr = item.to_string();
            if eol != "\n" {
                repr = repr.replace('\n', eol);
            }
            out.push_str(&repr);
            if !repr.ends_with(&eol.repeat(2)) {
                out.push_str(eol);
            }
        }
        out
    }

    /// 以 UTF-8 寫出。
    pub fn save(&self, path: &Path) -> Result<()> {
        std::fs::write(path, self.to_srt_string(None))
            .map_err(|e| Error::file(format!("無法寫入檔案: {} ({e})", path.display())))
    }
}

fn stream(lines: &[&str]) -> Vec<SubRipItem> {
    let mut items = Vec::new();
    let mut buffer: Vec<&str> = Vec::new();
    for line in lines.iter().copied().chain(std::iter::once("\n")) {
        if !py::strip(line).is_empty() {
            buffer.push(line);
        } else {
            let source = std::mem::take(&mut buffer);
            if !source.is_empty() {
                if let Some(item) = SubRipItem::from_lines(&source) {
                    items.push(item);
                }
            }
        }
    }
    items
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str =
        "1\n00:00:01,000 --> 00:00:02,500\nHello\nWorld  \n\n2\n00:00:03,000 --> 00:00:04,000 X1:10\n第二句\n";

    #[test]
    fn parses_items() {
        let f = SubRipFile::parse(SAMPLE);
        assert_eq!(f.len(), 2);
        assert_eq!(f.items[0].text, "Hello\nWorld");
        assert_eq!(f.items[1].position, "X1:10");
        assert_eq!(f.eol.as_deref(), Some("\n"));
    }

    #[test]
    fn roundtrip_output() {
        let f = SubRipFile::parse(SAMPLE);
        assert_eq!(
            f.to_srt_string(None),
            "1\n00:00:01,000 --> 00:00:02,500\nHello\nWorld\n\n2\n00:00:03,000 --> 00:00:04,000 X1:10\n第二句\n\n"
        );
    }

    #[test]
    fn crlf_and_missing_index() {
        let f = SubRipFile::parse(
            "00:00:01,000 --> 00:00:02,000\r\nNo index\r\n\r\nabc\r\n00:00:03,000 --> 00:00:04,000\r\nx\r\n",
        );
        assert_eq!(f.eol.as_deref(), Some("\r\n"));
        assert_eq!(f.items[0].index, SubIndex::Missing);
        assert_eq!(f.items[1].index, SubIndex::Text("abc".into()));
        assert!(f.to_srt_string(None).starts_with("None\r\n00:00:01,000"));
    }

    #[test]
    fn invalid_blocks_are_skipped() {
        let f = SubRipFile::parse("1\nnot a timestamp\ntext\n\n2\n00:00:01,000 --> 00:00:02,000\nok\n\njunk\n");
        assert_eq!(f.len(), 1);
        assert_eq!(f.items[0].text, "ok");
    }

    #[test]
    fn empty_text_item_output() {
        let mut f = SubRipFile::default();
        f.items.push(SubRipItem::new(1, SubRipTime::new(0, 0, 1, 0), SubRipTime::new(0, 0, 2, 0), ""));
        assert_eq!(f.to_srt_string(None), "1\n00:00:01,000 --> 00:00:02,000\n\n");
    }
}
