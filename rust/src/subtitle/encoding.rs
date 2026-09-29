//! 字幕檔編碼偵測與解碼。
//!
//! Python 版以 chardet 偵測，`ascii`/`windows-1252` 一律改用 utf-8。
//! 此處順序：BOM → 合法 UTF-8 → chardetng 猜測。UTF-8/BOM 檔案結果與 Python 一致；
//! 舊式編碼（Big5/GBK/Shift-JIS）的猜測結果可能與 chardet 不同。

use std::path::Path;

use encoding_rs::{Encoding, UTF_8};

use crate::error::{Details, Error, Result};

/// 偵測位元組內容的編碼。
pub fn detect(bytes: &[u8]) -> &'static Encoding {
    if let Some((enc, _)) = Encoding::for_bom(bytes) {
        return enc;
    }
    if std::str::from_utf8(bytes).is_ok() {
        return UTF_8;
    }
    let mut detector = chardetng::EncodingDetector::new(chardetng::Iso2022JpDetection::Allow);
    detector.feed(bytes, true);
    detector.guess(None, chardetng::Utf8Detection::Deny)
}

/// 以偵測到的編碼嚴格解碼（遇到非法序列回報錯誤，對應 Python codecs 的 strict 模式），並移除 BOM。
pub fn decode(bytes: &[u8]) -> std::result::Result<(String, &'static Encoding), &'static Encoding> {
    let enc = detect(bytes);
    let (enc, body) = match Encoding::for_bom(bytes) {
        Some((bom_enc, bom_len)) => (bom_enc, &bytes[bom_len..]),
        None => (enc, bytes),
    };
    match enc.decode_without_bom_handling_and_without_replacement(body) {
        Some(text) => Ok((text.into_owned(), enc)),
        None => Err(enc),
    }
}

/// 讀取並解碼文字檔。
pub fn read_text_file(path: &Path) -> Result<(String, &'static Encoding)> {
    let bytes = std::fs::read(path).map_err(|e| {
        let mut d = Details::new();
        d.insert("error".into(), e.to_string().into());
        Error::file_with(format!("無法讀取檔案: {}", path.display()), d)
    })?;
    decode(&bytes).map_err(|enc| {
        let mut d = Details::new();
        d.insert("error".into(), format!("無法以 {} 解碼", enc.name()).into());
        Error::file_with(format!("無法解析 SRT 檔案: {}", path.display()), d)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utf8_bom_is_stripped() {
        let (text, enc) = decode(b"\xef\xbb\xbfhello").unwrap();
        assert_eq!(enc, UTF_8);
        assert_eq!(text, "hello");
    }

    #[test]
    fn plain_utf8() {
        let (text, enc) = decode("字幕".as_bytes()).unwrap();
        assert_eq!(enc, UTF_8);
        assert_eq!(text, "字幕");
    }

    #[test]
    fn legacy_big5_is_detected() {
        let (bytes, _, _) = encoding_rs::BIG5.encode("這是一段繁體中文字幕，用來測試編碼偵測是否正常運作。");
        let (text, _) = decode(&bytes).unwrap();
        assert_eq!(text, "這是一段繁體中文字幕，用來測試編碼偵測是否正常運作。");
    }
}
