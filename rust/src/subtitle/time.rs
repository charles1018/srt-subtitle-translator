//! 對等於 pysrt `SubRipTime`：以毫秒 ordinal 儲存，寬鬆解析 `HH:MM:SS,mmm`。

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default)]
pub struct SubRipTime {
    pub ordinal: i64,
}

impl SubRipTime {
    pub const fn from_ordinal(ordinal: i64) -> Self {
        Self { ordinal }
    }

    pub const fn new(hours: i64, minutes: i64, seconds: i64, milliseconds: i64) -> Self {
        Self { ordinal: hours * 3_600_000 + minutes * 60_000 + seconds * 1000 + milliseconds }
    }

    /// 與 pysrt 相同：以 `:`、`.`、`,` 切成 4 段，每段取前導數字（無則 0）。
    pub fn parse(source: &str) -> Option<Self> {
        let items: Vec<&str> = source.split([':', '.', ',']).collect();
        if items.len() != 4 {
            return None;
        }
        let v: Vec<i64> = items.iter().map(|s| parse_int(s)).collect();
        Some(Self::new(v[0], v[1], v[2], v[3]))
    }
}

/// pysrt `parse_int`：先試整段 `int()`（允許前後空白與正負號），失敗則取前導數字。
fn parse_int(digits: &str) -> i64 {
    if let Some(v) = crate::py::parse_int(digits) {
        return v;
    }
    let end = digits.find(|c: char| !c.is_ascii_digit() && !('０'..='９').contains(&c)).unwrap_or(digits.len());
    crate::py::parse_int(&digits[..end]).unwrap_or(0)
}

impl fmt::Display for SubRipTime {
    /// 負數時間輸出為零（pysrt 行為）。Python `//` 與 `%` 對負數是 floor 語意，此處只處理非負。
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let o = self.ordinal.max(0);
        write!(f, "{:02}:{:02}:{:02},{:03}", o / 3_600_000, (o % 3_600_000) / 60_000, (o % 60_000) / 1000, o % 1000)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_and_format_roundtrip() {
        let t = SubRipTime::parse("01:02:03,456").unwrap();
        assert_eq!(t.ordinal, 3_723_456);
        assert_eq!(t.to_string(), "01:02:03,456");
    }

    #[test]
    fn lenient_parse() {
        assert_eq!(SubRipTime::parse("00:00:01.5").unwrap().ordinal, 1005);
        assert_eq!(SubRipTime::parse("00:00:01,500abc").unwrap().ordinal, 1500);
        assert!(SubRipTime::parse("00:01,500").is_none());
    }

    #[test]
    fn negative_displays_as_zero() {
        assert_eq!(SubRipTime::from_ordinal(-5).to_string(), "00:00:00,000");
    }

    #[test]
    fn hours_over_99() {
        assert_eq!(SubRipTime::new(100, 0, 0, 0).to_string(), "100:00:00,000");
    }
}
