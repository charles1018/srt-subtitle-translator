//! OpenCC s2twp（簡體 → 台灣繁體，含詞彙轉換），逐行移植 `opencc-python-reimplemented` 0.1.7。
//!
//! 刻意不用其他 Rust OpenCC 實作：該 Python 套件的比對方式特殊——在片段中尋找「最長、最左」的
//! 字典鍵，命中後對左右剩餘部分遞迴（只允許更短或等長的鍵），群組內的字典依序嘗試、每段只命中一次。
//! 標準 OpenCC 的最大正向匹配在部分詞彙上結果不同，為與 Python 版輸出逐字一致而完整重現。

use std::collections::HashMap;
use std::sync::LazyLock;

use fancy_regex::Regex;

struct Dict {
    max_len: usize,
    min_len: usize,
    map: HashMap<String, String>,
}

impl Dict {
    fn parse(text: &str) -> Self {
        let mut map = HashMap::new();
        let (mut max_len, mut min_len) = (1usize, 1000usize);
        for line in text.lines() {
            let line = crate::py::strip(line);
            let Some((key, value)) = line.split_once('\t') else { continue };
            let len = key.chars().count();
            max_len = max_len.max(len);
            min_len = min_len.min(len);
            map.insert(key.to_string(), value.to_string());
        }
        Self { max_len, min_len, map }
    }
}

/// s2twp 轉換鏈：[STPhrases, STCharacters]（群組）→ [TWPhrases] → [TWVariants]
static S2TWP_CHAIN: LazyLock<Vec<Vec<Dict>>> = LazyLock::new(|| {
    vec![
        vec![
            Dict::parse(include_str!("../../assets/opencc/STPhrases.txt")),
            Dict::parse(include_str!("../../assets/opencc/STCharacters.txt")),
        ],
        vec![Dict::parse(include_str!("../../assets/opencc/TWPhrases.txt"))],
        vec![Dict::parse(include_str!("../../assets/opencc/TWVariants.txt"))],
    ]
});

/// OpenCC PhraseExtract 的句子分隔字元，分隔字元本身不參與轉換。
static SPLIT_CHARS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(concat!(
        r"(\s+|-|,|\.|\?|!|\*|　|，|。|、|；|：|？|！|…|“|”|‘|’|『|』|「|」|﹁|﹂|—|－|（|）|《|》|〈|〉|～|．|／|＼|",
        r"︒|︑|︔|︓|︿|﹀|︹|︺|︙|︐|［|﹇|］|﹈|︕|︖|︰|︳|︴|︽|︾|︵|︶|｛|︷|｝|︸|﹃|﹄|【|︻|】|︼)"
    ))
    .unwrap()
});

/// 在片段中找最長（同長取最左）的字典鍵；`hint` 限制鍵長上限。
/// 回傳 (命中位置, 鍵長, 轉換值)，位置與長度以字元計。
fn find_match<'d>(chars: &[char], dict: &'d Dict, hint: Option<usize>) -> Option<(usize, usize, &'d str)> {
    let len = chars.len();
    let mut test_len = len.min(dict.max_len);
    if let Some(h) = hint {
        test_len = test_len.min(h);
    }
    let mut key = String::new();
    while test_len >= dict.min_len && test_len > 0 {
        for i in 0..=(len - test_len) {
            key.clear();
            key.extend(&chars[i..i + test_len]);
            if let Some(value) = dict.map.get(&key) {
                // 一對多時取第一個
                let first = value.split(' ').next().unwrap_or(value);
                return Some((i, test_len, first));
            }
        }
        test_len -= 1;
    }
    None
}

/// 以一個字典群組轉換片段（等價於 Python `StringTree.create_parse_tree` + 中序走訪）。
fn convert_with_group(chars: &[char], group: &[Dict], dict_index: usize, hint: Option<usize>, out: &mut String) {
    if chars.is_empty() {
        return;
    }
    let Some(dict) = group.get(dict_index) else {
        out.extend(chars);
        return;
    };
    match find_match(chars, dict, hint) {
        // 未命中：換群組內的下一個字典，且不再限制鍵長
        None => convert_with_group(chars, group, dict_index + 1, None, out),
        Some((i, test_len, value)) => {
            convert_with_group(&chars[..i], group, dict_index, Some(test_len), out);
            out.push_str(value);
            convert_with_group(&chars[i + test_len..], group, dict_index, Some(test_len), out);
        }
    }
}

fn convert_segment(segment: &str) -> String {
    let mut current = segment.to_string();
    for group in S2TWP_CHAIN.iter() {
        let chars: Vec<char> = current.chars().collect();
        let mut out = String::with_capacity(current.len());
        convert_with_group(&chars, group, 0, None, &mut out);
        current = out;
    }
    current
}

/// 簡體 → 台灣繁體（s2twp）。對繁中與非中文輸入冪等。
pub fn s2twp(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
    let mut last = 0;
    for m in SPLIT_CHARS.find_iter(text).flatten() {
        result.push_str(&convert_segment(&text[last..m.start()]));
        result.push_str(m.as_str());
        last = m.end();
    }
    result.push_str(&convert_segment(&text[last..]));
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_common_phrases() {
        assert_eq!(s2twp("软件和网络"), "軟體和網路");
        assert_eq!(s2twp("这是一个测试。"), "這是一個測試。");
    }

    #[test]
    fn traditional_and_ascii_are_idempotent() {
        for s in ["這是繁體中文", "Hello, world!", "", "  "] {
            assert_eq!(s2twp(s), s);
        }
    }
}
