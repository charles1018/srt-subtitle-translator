//! Python 字串語意的小工具，讓移植的邏輯與 CPython 行為一致。

/// 對應 `str.isspace()`：Unicode White_Space 加上 `\x1c`–`\x1f`（CPython 視為空白）。
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()`
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `str.rstrip()`
pub fn rstrip(s: &str) -> &str {
    s.trim_end_matches(is_space)
}

/// `str.lstrip()`
pub fn lstrip(s: &str) -> &str {
    s.trim_start_matches(is_space)
}

/// `str.strip(chars)` / `rstrip(chars)` 以字元集合剝除。
pub fn strip_chars<'a>(s: &'a str, chars: &str) -> &'a str {
    s.trim_matches(|c| chars.contains(c))
}

pub fn rstrip_chars<'a>(s: &'a str, chars: &str) -> &'a str {
    s.trim_end_matches(|c| chars.contains(c))
}

/// `len(str)`：以 code point 計數。
pub fn len(s: &str) -> usize {
    s.chars().count()
}

/// 以 code point 位置切片 `s[start:end]`（位置超出範圍時截斷，如 Python）。
pub fn slice(s: &str, start: usize, end: usize) -> &str {
    let b = byte_offset(s, start);
    let e = byte_offset(s, end.max(start));
    &s[b..e]
}

/// `s[:n]`
pub fn prefix(s: &str, n: usize) -> &str {
    &s[..byte_offset(s, n)]
}

/// 第 n 個 code point 的位元組位置（超出時回傳 `s.len()`）。
pub fn byte_offset(s: &str, n: usize) -> usize {
    s.char_indices().nth(n).map_or(s.len(), |(i, _)| i)
}

fn is_line_boundary(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

/// `str.splitlines(keepends)`：`\r\n` 視為單一換行，並包含 Python 認定的所有行界字元。
pub fn splitlines(s: &str, keepends: bool) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut iter = s.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        if is_line_boundary(c) {
            let mut end = i + c.len_utf8();
            if c == '\r' {
                if let Some(&(j, '\n')) = iter.peek() {
                    iter.next();
                    end = j + 1;
                }
            }
            out.push(if keepends { &s[start..end] } else { &s[start..i] });
            start = end;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// Python `int(str)`：允許前後空白、正負號，以及全形數字。
pub fn parse_int(s: &str) -> Option<i64> {
    let t = strip(s);
    let (neg, digits) = match t.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    if digits.is_empty() {
        return None;
    }
    let mut value: i64 = 0;
    for c in digits.chars() {
        let d = match c {
            '0'..='9' => c as i64 - '0' as i64,
            '０'..='９' => c as i64 - '０' as i64,
            _ => return None,
        };
        value = value.checked_mul(10)?.checked_add(d)?;
    }
    Some(if neg { -value } else { value })
}

/// Python `repr(float)` 的常見情況：整數值補 `.0`，其餘使用最短往返表示。
pub fn float_repr(x: f64) -> String {
    if x.is_finite() && x.fract() == 0.0 && x.abs() < 1e16 {
        format!("{x:.1}")
    } else {
        format!("{x}")
    }
}

/// Python `round(x, ndigits)`：以正確捨入的十進位字串為準（與 CPython 相同）。
pub fn round(x: f64, ndigits: usize) -> f64 {
    format!("{x:.ndigits$}").parse().unwrap_or(x)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_matches_python() {
        assert_eq!(splitlines("a\r\nb\rc\nd", true), vec!["a\r\n", "b\r", "c\n", "d"]);
        assert_eq!(splitlines("a\n\nb\n", false), vec!["a", "", "b"]);
        assert_eq!(splitlines("", true), Vec::<&str>::new());
        assert_eq!(splitlines("x\u{2028}y", false), vec!["x", "y"]);
    }

    #[test]
    fn strip_includes_info_separators() {
        assert_eq!(strip("\u{1f} a \u{3000}"), "a");
    }

    #[test]
    fn slicing_by_code_point() {
        assert_eq!(prefix("日本語テキスト", 3), "日本語");
        assert_eq!(slice("日本語", 1, 10), "本語");
    }

    #[test]
    fn int_parsing() {
        assert_eq!(parse_int(" 12 "), Some(12));
        assert_eq!(parse_int("１２"), Some(12));
        assert_eq!(parse_int("-3"), Some(-3));
        assert_eq!(parse_int("1a"), None);
    }
}
