//! 輸出路徑決定與檔名衝突處理（對等 Python `FileHandler.get_output_path`）。

use std::path::{Component, Path, PathBuf};

use serde_json::Value;

use crate::config::ConfigFile;
use crate::error::{Error, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OverwriteMode {
    Ask,
    Overwrite,
    Rename,
    Skip,
}

impl OverwriteMode {
    pub fn parse(s: &str) -> Self {
        match s {
            "overwrite" => Self::Overwrite,
            "rename" => Self::Rename,
            "skip" => Self::Skip,
            _ => Self::Ask,
        }
    }
}

/// 使用者對檔名衝突的選擇。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConflictChoice {
    Overwrite,
    Rename,
    Skip,
}

#[derive(Debug, Clone)]
pub struct OutputSettings {
    /// 語言 → 後綴（如 繁體中文 → .zh_tw）
    pub lang_suffix: Vec<(String, String)>,
    pub name_pattern: String,
    pub overwrite_mode: OverwriteMode,
    pub output_directory: String,
    pub preserve_folder_structure: bool,
    pub last_directory: String,
}

impl OutputSettings {
    /// 由 `file_handler_config.json` 建立（鍵與預設值同 Python `FileHandler.__init__`）。
    pub fn from_config(file_config: &ConfigFile) -> Self {
        let lang_suffix = file_config
            .get("lang_suffix")
            .and_then(Value::as_object)
            .map(|m| m.iter().filter_map(|(k, v)| Some((k.clone(), v.as_str()?.to_string()))).collect())
            .unwrap_or_default();
        let batch = |key: &str| file_config.get(&format!("batch_settings.{key}"));
        Self {
            lang_suffix,
            name_pattern: batch("name_pattern").and_then(Value::as_str).unwrap_or("{filename}_{language}{ext}").into(),
            overwrite_mode: OverwriteMode::parse(batch("overwrite_mode").and_then(Value::as_str).unwrap_or("ask")),
            output_directory: batch("output_directory").and_then(Value::as_str).unwrap_or_default().into(),
            preserve_folder_structure: batch("preserve_folder_structure").and_then(Value::as_bool).unwrap_or(true),
            last_directory: file_config.get_str("last_directory").unwrap_or_default().into(),
        }
    }
}

/// Python `str.format` 的具名欄位替換；遇到未知欄位時回報錯誤（Python 會拋 KeyError）。
fn format_pattern(pattern: &str, fields: &[(&str, &str)]) -> Result<String> {
    let mut out = String::new();
    let mut rest = pattern;
    while let Some(start) = rest.find(['{', '}']) {
        out.push_str(&rest[..start]);
        let tail = &rest[start..];
        if tail.starts_with("{{") || tail.starts_with("}}") {
            out.push_str(&tail[..1]);
            rest = &tail[2..];
            continue;
        }
        if tail.starts_with('}') {
            return Err(Error::file(format!("Error determining output path: 檔名樣式格式錯誤: {pattern}")));
        }
        let end = tail.find('}').ok_or_else(|| Error::file(format!("檔名樣式格式錯誤: {pattern}")))?;
        let key = &tail[1..end];
        let value = fields
            .iter()
            .find(|(k, _)| *k == key)
            .map(|(_, v)| *v)
            .ok_or_else(|| Error::file(format!("Error determining output path: '{key}'")))?;
        out.push_str(value);
        rest = &tail[end + 1..];
    }
    out.push_str(rest);
    Ok(out)
}

/// `os.path.splitext`：回傳 (主檔名, 含點的副檔名)；以點開頭的隱藏檔不視為副檔名。
fn splitext(name: &str) -> (&str, &str) {
    match name.rfind('.') {
        Some(i) if name[..i].chars().any(|c| c != '.') => (&name[..i], &name[i..]),
        _ => (name, ""),
    }
}

/// `os.path.normpath` 的純字串版本（不解析符號連結）。
fn normpath(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for comp in path.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() {
                    out.push("..");
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    if out.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        out
    }
}

/// `os.path.commonpath`：兩者必須同為絕對或同為相對，否則回傳 None（Python 拋 ValueError）。
fn commonpath(a: &Path, b: &Path) -> Option<PathBuf> {
    if a.as_os_str().is_empty() || a.is_absolute() != b.is_absolute() {
        return None;
    }
    let mut common = PathBuf::new();
    for (x, y) in a.components().zip(b.components()) {
        if x != y {
            break;
        }
        common.push(x.as_os_str());
    }
    Some(common)
}

fn is_within(path: &Path, directory: &Path) -> bool {
    let absolute = |p: &Path| std::path::absolute(p).map(|p| normpath(&p)).unwrap_or_else(|_| normpath(p));
    absolute(path).starts_with(absolute(directory))
}

fn unique_path(dir: &Path, name: &str, lang_suffix: &str, ext: &str) -> PathBuf {
    (1..)
        .map(|n| normpath(&dir.join(format!("{name}{lang_suffix}_{n}{ext}"))))
        .find(|p| !p.exists())
        .expect("無限序列必有未使用的檔名")
}

/// 決定輸出路徑並處理衝突；回傳 `None` 表示略過（skip）。
///
/// `ask` 模式下若沒有提供 `ask` 回呼則直接覆寫（與 Python CLI 安靜模式相同）。
pub fn resolve_output_path(
    source: &Path,
    target_lang: &str,
    settings: &OutputSettings,
    ask: Option<&dyn Fn(&Path) -> ConflictChoice>,
) -> Result<Option<PathBuf>> {
    if !source.exists() {
        return Ok(None);
    }
    let file_name = source.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let (name, ext) = splitext(&file_name);
    let mut dir = source.parent().map(Path::to_path_buf).unwrap_or_default();

    let output_dir = Path::new(&settings.output_directory);
    if !settings.output_directory.is_empty() && output_dir.exists() {
        dir = output_dir.to_path_buf();
        if settings.preserve_folder_structure {
            if let Some(common) = commonpath(Path::new(&settings.last_directory), source) {
                let rel_dir = source.strip_prefix(&common).ok().and_then(Path::parent).unwrap_or(Path::new(""));
                let nested = output_dir.join(rel_dir);
                if is_within(&nested, output_dir) && std::fs::create_dir_all(&nested).is_ok() {
                    dir = nested;
                }
            }
        }
    }

    let lang_suffix =
        settings.lang_suffix.iter().find(|(lang, _)| lang == target_lang).map_or(".unknown", |(_, s)| s.as_str());
    let now = chrono::Local::now();
    let (date, time) = (now.format("%Y%m%d").to_string(), now.format("%H%M%S").to_string());
    let language = target_lang.to_lowercase();
    let suffix = lang_suffix.replace('.', "");
    let mut output_name = format_pattern(
        &settings.name_pattern,
        &[
            ("filename", name),
            ("language", &language),
            ("suffix", &suffix),
            ("ext", ext),
            ("date", &date),
            ("time", &time),
        ],
    )?;
    if splitext(&output_name).1.is_empty() {
        output_name.push_str(ext);
    }
    let base = dir.join(&output_name);

    if base.exists() {
        let choice = match (settings.overwrite_mode, ask) {
            (OverwriteMode::Ask, Some(ask)) => ask(&base),
            (OverwriteMode::Rename, _) => ConflictChoice::Rename,
            (OverwriteMode::Skip, _) => ConflictChoice::Skip,
            _ => ConflictChoice::Overwrite,
        };
        match choice {
            ConflictChoice::Rename => return Ok(Some(unique_path(&dir, name, lang_suffix, ext))),
            ConflictChoice::Skip => return Ok(None),
            ConflictChoice::Overwrite => {}
        }
    }
    Ok(Some(normpath(&base)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings(mode: OverwriteMode) -> OutputSettings {
        OutputSettings {
            lang_suffix: vec![("繁體中文".into(), ".zh_tw".into())],
            name_pattern: "{filename}_{language}{ext}".into(),
            overwrite_mode: mode,
            output_directory: String::new(),
            preserve_folder_structure: true,
            last_directory: String::new(),
        }
    }

    #[test]
    fn default_pattern_and_conflicts() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("movie.en.srt");
        std::fs::write(&src, "x").unwrap();
        let out = resolve_output_path(&src, "繁體中文", &settings(OverwriteMode::Ask), None).unwrap().unwrap();
        assert_eq!(out, dir.path().join("movie.en_繁體中文.srt"));

        std::fs::write(&out, "old").unwrap();
        let renamed = resolve_output_path(&src, "繁體中文", &settings(OverwriteMode::Rename), None).unwrap().unwrap();
        assert_eq!(renamed, dir.path().join("movie.en.zh_tw_1.srt"));
        assert!(resolve_output_path(&src, "繁體中文", &settings(OverwriteMode::Skip), None).unwrap().is_none());
        let asked = resolve_output_path(
            &src,
            "繁體中文",
            &settings(OverwriteMode::Ask),
            Some(&|_: &Path| ConflictChoice::Skip),
        );
        assert!(asked.unwrap().is_none());
    }

    #[test]
    fn output_directory_and_pattern_fields() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("a.srt");
        std::fs::write(&src, "x").unwrap();
        let out_dir = dir.path().join("out");
        std::fs::create_dir(&out_dir).unwrap();
        let mut s = settings(OverwriteMode::Ask);
        s.output_directory = out_dir.to_string_lossy().into();
        s.name_pattern = "{filename}.{suffix}".into();
        assert_eq!(resolve_output_path(&src, "繁體中文", &s, None).unwrap().unwrap(), out_dir.join("a.zh_tw"));
        s.name_pattern = "{nope}".into();
        assert!(resolve_output_path(&src, "繁體中文", &s, None).is_err());
    }
}
