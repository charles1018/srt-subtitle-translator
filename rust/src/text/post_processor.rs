//! Netflix 字幕風格後處理器（對等 Python `utils/post_processor.py`）。
//!
//! 行為經 benchmark 驗證，修改前必須先跑 A/B（見 FUTURE_AGENT_REPO_GUIDE.md §1）。

use std::sync::LazyLock;

use fancy_regex::Regex;
use serde::Serialize;

use crate::py;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProcessingWarning {
    pub code: &'static str,
    pub message: String,
    pub line_number: Option<usize>,
    pub original_text: Option<String>,
    pub fixed_text: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ProcessingResult {
    pub text: String,
    pub warnings: Vec<ProcessingWarning>,
    pub auto_fixed: usize,
}

impl ProcessingResult {
    fn warn(
        &mut self,
        code: &'static str,
        message: impl Into<String>,
        line_number: Option<usize>,
        original_text: Option<&str>,
        fixed_text: Option<&str>,
    ) {
        self.warnings.push(ProcessingWarning {
            code,
            message: message.into(),
            line_number,
            original_text: original_text.map(str::to_string),
            fixed_text: fixed_text.map(str::to_string),
        });
    }
}

/// 半形 → 全形標點（省略號另於 `fix_ellipsis` 處理）。
const PUNCTUATION_MAP: [(&str, &str); 5] = [(",", "，"), (";", "；"), (":", "："), ("!", "！"), ("?", "？")];

/// 西式引號 → 中文成對引號，依序處理。
const QUOTE_MAP: [(char, &str, &str); 2] = [('"', "「", "」"), ('\'', "「", "」")];

static FULLWIDTH_DIGIT_COMMA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"([０-９])，([０-９])").unwrap());
static FOUR_DIGIT_COMMA: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?<!\d)(\d{1,3}),(\d{3})(?!\d)").unwrap());
static DOTS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\.{3,}").unwrap());
static ELLIPSIS_DOT: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"⋯\.").unwrap());

fn normalize_quote(c: char) -> char {
    match c {
        '“' | '”' | '„' | '‟' => '"',
        '‘' | '’' | '‚' | '‛' => '\'',
        other => other,
    }
}

fn fullwidth_to_halfwidth(c: char) -> char {
    match c {
        '０'..='９' => char::from_u32(c as u32 - '０' as u32 + '0' as u32).unwrap(),
        other => other,
    }
}

/// (是否為斷點字元, 是否在該字元之後斷行)
type SplitPoint = (fn(char) -> bool, bool);

#[derive(Debug, Clone)]
pub struct NetflixStylePostProcessor {
    pub auto_fix: bool,
    pub strict_mode: bool,
    pub max_chars_per_line: usize,
    pub max_lines: usize,
}

impl Default for NetflixStylePostProcessor {
    fn default() -> Self {
        Self { auto_fix: true, strict_mode: false, max_chars_per_line: 16, max_lines: 2 }
    }
}

impl NetflixStylePostProcessor {
    pub fn new(auto_fix: bool, strict_mode: bool, max_chars_per_line: usize, max_lines: usize) -> Self {
        Self { auto_fix, strict_mode, max_chars_per_line, max_lines }
    }

    /// 依序套用所有 Netflix 規範。
    pub fn process(&self, text: &str) -> ProcessingResult {
        let mut result = ProcessingResult { text: text.to_string(), warnings: Vec::new(), auto_fixed: 0 };
        if py::strip(text).is_empty() {
            return result;
        }
        let steps: [fn(&Self, &str, &mut ProcessingResult) -> String; 6] = [
            Self::fix_punctuation,
            Self::fix_quotations,
            Self::fix_numbers,
            Self::fix_ellipsis,
            Self::remove_line_end_punctuation,
            Self::check_and_fix_character_limit,
        ];
        for step in steps {
            let current = std::mem::take(&mut result.text);
            result.text = step(self, &current, &mut result);
        }
        let final_text = result.text.clone();
        Self::check_question_marks(&final_text, &mut result);
        result
    }

    fn record_fix(result: &mut ProcessingResult, code: &'static str, message: &str, original: &str, fixed: &str) {
        if fixed != original {
            result.auto_fixed += 1;
            result.warn(code, message, None, Some(original), Some(fixed));
        }
    }

    fn fix_punctuation(&self, text: &str, result: &mut ProcessingResult) -> String {
        if !self.auto_fix {
            return text.to_string();
        }
        let mut out = text.to_string();
        for (half, full) in PUNCTUATION_MAP {
            out = out.replace(half, full);
        }
        Self::record_fix(result, "PUNCT_FIXED", "已自動轉換半形標點為全形中文標點", text, &out);
        out
    }

    fn fix_quotations(&self, text: &str, result: &mut ProcessingResult) -> String {
        if !self.auto_fix {
            return text.to_string();
        }
        let mut out: String = text.chars().map(normalize_quote).collect();
        for (western, open, close) in QUOTE_MAP {
            if !out.contains(western) {
                continue;
            }
            // 奇數次出現 → 開引號，偶數次 → 閉引號
            let mut parts = out.split(western);
            let mut rebuilt = parts.next().unwrap_or_default().to_string();
            for (i, part) in parts.enumerate() {
                rebuilt.push_str(if i % 2 == 0 { open } else { close });
                rebuilt.push_str(part);
            }
            out = rebuilt;
        }
        Self::record_fix(result, "QUOTE_FIXED", "已自動轉換引號為中文引號「」", text, &out);
        out
    }

    fn fix_numbers(&self, text: &str, result: &mut ProcessingResult) -> String {
        if !self.auto_fix {
            return text.to_string();
        }
        let out = FULLWIDTH_DIGIT_COMMA.replace_all(text, "$1,$2");
        let out: String = out.chars().map(fullwidth_to_halfwidth).collect();
        // 移除四位數中的逗號分隔符（1,234 → 1234），保留五位數以上
        let out = FOUR_DIGIT_COMMA.replace_all(&out, "$1$2").into_owned();
        Self::record_fix(result, "NUMBER_FIXED", "已自動轉換數字格式（全形轉半形，移除四位數逗號）", text, &out);
        out
    }

    fn fix_ellipsis(&self, text: &str, result: &mut ProcessingResult) -> String {
        if !self.auto_fix {
            return text.to_string();
        }
        let out = DOTS.replace_all(text, "⋯").replace("。。。", "⋯").replace('…', "⋯");
        let out = ELLIPSIS_DOT.replace_all(&out, "⋯").into_owned();
        Self::record_fix(result, "ELLIPSIS_FIXED", "已自動統一省略號格式為 ⋯", text, &out);
        out
    }

    fn remove_line_end_punctuation(&self, text: &str, result: &mut ProcessingResult) -> String {
        if !self.auto_fix {
            return text.to_string();
        }
        let fixed: Vec<String> = text
            .split('\n')
            .map(|line| {
                let stripped = py::rstrip(line);
                match stripped.strip_suffix(['。', '，', '、']) {
                    Some(without) => format!("{without}{}", &line[stripped.len()..]),
                    None => line.to_string(),
                }
            })
            .collect();
        let out = fixed.join("\n");
        Self::record_fix(result, "LINE_END_PUNCT_REMOVED", "已自動移除行尾的句號和逗號", text, &out);
        out
    }

    /// 智慧分割長行：優先在逗號/頓號後、連接詞前、空白後斷行，選最接近行中間的位置。
    pub fn smart_split_line(line: &str, max_chars: usize) -> Vec<String> {
        if py::len(line) <= max_chars {
            return vec![line.to_string()];
        }
        let split_points: [SplitPoint; 3] = [
            (|c| matches!(c, '，' | '、'), true),
            (|c| matches!(c, '和' | '與' | '或' | '但'), false),
            (py::is_space, true),
        ];

        let mut result = Vec::new();
        let mut remaining = line.to_string();
        while py::len(&remaining) > max_chars {
            let window: Vec<char> = remaining.chars().take(max_chars).collect();
            let mut best_pos = 0usize;
            let mut best_distance = usize::MAX;
            for (matches, after) in split_points {
                if let Some(i) = window.iter().rposition(|&c| matches(c)) {
                    let pos = if after { i + 1 } else { i };
                    let distance = pos.abs_diff(max_chars / 2);
                    if distance < best_distance {
                        best_pos = pos;
                        best_distance = distance;
                    }
                }
            }
            let cut = if best_pos > 0 { best_pos } else { max_chars };
            let head = py::prefix(&remaining, cut);
            let head = if best_pos > 0 { py::rstrip_chars(py::strip(head), "。，、") } else { py::strip(head) };
            result.push(head.to_string());
            remaining = py::lstrip(&remaining[py::byte_offset(&remaining, cut)..]).to_string();
        }
        if !remaining.is_empty() {
            result.push(py::strip(&remaining).to_string());
        }
        result
    }

    fn check_and_fix_character_limit(&self, text: &str, result: &mut ProcessingResult) -> String {
        let mut fixed_lines: Vec<String> = Vec::new();
        let mut needs_fix = false;

        for (i, line) in text.split('\n').enumerate() {
            let i = i + 1;
            let stripped = py::strip(line);
            let char_count = py::len(stripped);
            if char_count > self.max_chars_per_line {
                if self.auto_fix {
                    let split = Self::smart_split_line(stripped, self.max_chars_per_line);
                    needs_fix = true;
                    result.auto_fixed += 1;
                    let joined = split.join("\n");
                    result.warn(
                        "LINE_TOO_LONG_AUTO_FIXED",
                        format!("第 {i} 行超過限制 ({char_count} 字符)，已自動分割為 {} 行", split.len()),
                        Some(i),
                        Some(stripped),
                        Some(&joined),
                    );
                    fixed_lines.extend(split);
                } else {
                    fixed_lines.push(stripped.to_string());
                    result.warn(
                        "LINE_TOO_LONG",
                        format!("第 {i} 行超過字符限制: {char_count} 字符 (最多 {} 字符)", self.max_chars_per_line),
                        Some(i),
                        Some(stripped),
                        None,
                    );
                }
            } else {
                fixed_lines.push(stripped.to_string());
            }
        }

        if fixed_lines.len() > self.max_lines {
            result.warn(
                "TOO_MANY_LINES",
                format!("超過最大行數限制: {} 行 (最多 {} 行)", fixed_lines.len(), self.max_lines),
                Some(fixed_lines.len()),
                None,
                None,
            );
        }

        if needs_fix {
            fixed_lines.join("\n")
        } else {
            text.to_string()
        }
    }

    fn check_question_marks(text: &str, result: &mut ProcessingResult) {
        if text.contains("？？") || text.contains("??") {
            result.warn("DOUBLE_QUESTION_MARK", "不應使用雙問號 (？？)", None, Some(text), None);
        }
        if text.contains("！！") || text.contains("!!") {
            result.warn("DOUBLE_EXCLAMATION", "不應使用雙驚嘆號 (！！)", None, Some(text), None);
        }
        if ["!?", "！？", "?!", "？！"].iter().any(|p| text.contains(p)) {
            result.warn("MIXED_PUNCTUATION", "不應使用混合驚嘆問號 (!? 或 ?!)", None, Some(text), None);
        }
    }

    /// 格式化警告訊息為可讀字串。
    pub fn format_warnings(result: &ProcessingResult) -> String {
        if result.warnings.is_empty() {
            return "無警告".to_string();
        }
        let mut lines = vec![format!("共 {} 個警告，{} 個自動修正:\n", result.warnings.len(), result.auto_fixed)];
        for (i, w) in result.warnings.iter().enumerate() {
            let line_info = match w.line_number {
                Some(n) if n != 0 => format!(" (第{n}行)"),
                _ => String::new(),
            };
            lines.push(format!("{}. [{}]{line_info} {}", i + 1, w.code, w.message));
            if let (Some(o), Some(f)) = (&w.original_text, &w.fixed_text) {
                if !o.is_empty() && !f.is_empty() {
                    lines.push(format!("   原文: {}...", py::prefix(o, 50)));
                    lines.push(format!("   修正: {}...", py::prefix(f, 50)));
                }
            }
        }
        lines.join("\n")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(text: &str) -> String {
        NetflixStylePostProcessor::default().process(text).text
    }

    #[test]
    fn punctuation_and_quotes() {
        assert_eq!(run("他說:\"你好\"!"), "他說：「你好」！");
        assert_eq!(run("“真的”嗎?"), "「真的」嗎？");
    }

    #[test]
    fn numbers_and_ellipsis() {
        assert_eq!(run("價格１，２３４元"), "價格1234元");
        assert_eq!(run("共12,345人"), "共12，345人");
        assert_eq!(run("等等....."), "等等⋯");
        assert_eq!(run("嗯…。"), "嗯⋯");
    }

    #[test]
    fn line_end_punctuation() {
        assert_eq!(run("好的。\n走吧，"), "好的\n走吧");
    }

    #[test]
    fn smart_split_prefers_comma() {
        let r = NetflixStylePostProcessor::default().process("我們今天一起去市場買菜，然後回家煮一頓豐盛的晚餐");
        assert_eq!(r.text, "我們今天一起去市場買菜\n然後回家煮一頓豐盛的晚餐");
        assert_eq!(r.warnings.last().unwrap().code, "LINE_TOO_LONG_AUTO_FIXED");
    }

    #[test]
    fn whitespace_only_untouched() {
        let r = NetflixStylePostProcessor::default().process("  ");
        assert_eq!(r.text, "  ");
        assert_eq!(r.auto_fixed, 0);
    }
}
