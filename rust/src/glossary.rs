//! 術語表（對等 Python `core/glossary.py`），檔案格式與 `data/glossaries/*.json` 相容。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use fancy_regex::{NoExpand, Regex, RegexBuilder};
use indexmap::{IndexMap, IndexSet};
use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};
use crate::py;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GlossaryEntry {
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub target: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub notes: String,
    #[serde(default)]
    pub case_sensitive: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Glossary {
    pub name: String,
    pub source_lang: String,
    pub target_lang: String,
    pub description: String,
    /// 鍵：區分大小寫時為原字串，否則為小寫；保持插入順序。
    pub entries: IndexMap<String, GlossaryEntry>,
}

/// JSON 檔案格式（`to_dict` / `from_dict`）。
#[derive(Debug, Serialize, Deserialize)]
struct GlossaryFile {
    #[serde(default)]
    name: String,
    #[serde(default)]
    source_lang: String,
    #[serde(default)]
    target_lang: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    entries: Vec<GlossaryEntry>,
}

impl Glossary {
    pub fn new(name: &str, source_lang: &str, target_lang: &str, description: &str) -> Self {
        Self {
            name: name.into(),
            source_lang: source_lang.into(),
            target_lang: target_lang.into(),
            description: description.into(),
            entries: IndexMap::new(),
        }
    }

    pub fn add_entry(&mut self, source: &str, target: &str, category: &str, notes: &str, case_sensitive: bool) {
        let key = if case_sensitive { source.to_string() } else { source.to_lowercase() };
        self.entries.insert(
            key,
            GlossaryEntry {
                source: source.into(),
                target: target.into(),
                category: category.into(),
                notes: notes.into(),
                case_sensitive,
            },
        );
    }

    pub fn remove_entry(&mut self, source: &str) -> bool {
        self.entries.shift_remove(&source.to_lowercase()).is_some() || self.entries.shift_remove(source).is_some()
    }

    pub fn get_entry(&self, source: &str) -> Option<&GlossaryEntry> {
        self.entries.get(&source.to_lowercase()).or_else(|| self.entries.get(source))
    }

    /// 依來源術語長度降序替換（穩定排序，避免短詞誤替換長詞）。
    ///
    /// 與 Python 的差異：Python `re.sub` 會解析譯文中的反斜線跳脫，此處一律視為字面文字。
    pub fn apply_to_text(&self, text: &str) -> String {
        let mut sorted: Vec<&GlossaryEntry> = self.entries.values().collect();
        sorted.sort_by_key(|e| std::cmp::Reverse(py::len(&e.source)));
        let mut result = text.to_string();
        for entry in sorted {
            if entry.case_sensitive {
                result = result.replace(&entry.source, &entry.target);
            } else if let Ok(re) = RegexBuilder::new(&fancy_regex::escape(&entry.source)).case_insensitive(true).build()
            {
                result = re.replace_all(&result, NoExpand(&entry.target)).into_owned();
            }
        }
        result
    }

    pub fn to_json(&self) -> String {
        let file = GlossaryFile {
            name: self.name.clone(),
            source_lang: self.source_lang.clone(),
            target_lang: self.target_lang.clone(),
            description: self.description.clone(),
            entries: self.entries.values().cloned().collect(),
        };
        serde_json::to_string_pretty(&file).expect("glossary 序列化不會失敗")
    }

    pub fn from_json(json: &str) -> Result<Self> {
        let file: GlossaryFile = serde_json::from_str(json).map_err(|e| Error::file(format!("術語表格式錯誤: {e}")))?;
        let mut g = Self::new(&file.name, &file.source_lang, &file.target_lang, &file.description);
        for e in file.entries {
            g.add_entry(&e.source, &e.target, &e.category, &e.notes, e.case_sensitive);
        }
        Ok(g)
    }
}

static UNSAFE_FILENAME_CHARS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r#"[<>:"/\\|?*]"#).unwrap());

/// 術語表目錄管理（對等 `GlossaryManager`，但不是 singleton，由呼叫端持有）。
#[derive(Debug)]
pub struct GlossaryManager {
    dir: PathBuf,
    glossaries: HashMap<String, Glossary>,
    active: IndexSet<String>,
}

impl GlossaryManager {
    /// 載入目錄下所有 `.json` 術語表（目錄不存在時建立）。載入失敗的檔案略過。
    pub fn open(dir: impl Into<PathBuf>) -> Result<Self> {
        let dir = dir.into();
        std::fs::create_dir_all(&dir).map_err(|e| Error::file(format!("無法建立術語表目錄: {e}")))?;
        let mut glossaries = HashMap::new();
        let mut paths: Vec<PathBuf> = std::fs::read_dir(&dir)
            .map_err(|e| Error::file(format!("無法讀取術語表目錄: {e}")))?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().is_some_and(|x| x == "json"))
            .collect();
        paths.sort();
        for path in paths {
            if let Ok(g) =
                std::fs::read_to_string(&path).map_err(|_| ()).and_then(|s| Glossary::from_json(&s).map_err(|_| ()))
            {
                glossaries.insert(g.name.clone(), g);
            }
        }
        Ok(Self { dir, glossaries, active: IndexSet::new() })
    }

    fn file_path(&self, name: &str) -> PathBuf {
        let safe = UNSAFE_FILENAME_CHARS.replace_all(name, "_");
        self.dir.join(format!("{safe}.json"))
    }

    pub fn save(&self, glossary: &Glossary) -> Result<()> {
        let path = self.file_path(&glossary.name);
        std::fs::write(&path, glossary.to_json())
            .map_err(|e| Error::file(format!("儲存術語表失敗 {}: {e}", glossary.name)))
    }

    pub fn create(&mut self, name: &str, source_lang: &str, target_lang: &str, description: &str) -> Result<&Glossary> {
        if self.glossaries.contains_key(name) {
            return Err(Error::file(format!("術語表 '{name}' 已存在")));
        }
        let g = Glossary::new(name, source_lang, target_lang, description);
        self.save(&g)?;
        Ok(self.glossaries.entry(name.to_string()).or_insert(g))
    }

    pub fn get(&self, name: &str) -> Option<&Glossary> {
        self.glossaries.get(name)
    }

    pub fn list(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.glossaries.keys().map(String::as_str).collect();
        names.sort_unstable();
        names
    }

    pub fn delete(&mut self, name: &str) -> Result<bool> {
        if self.glossaries.remove(name).is_none() {
            return Ok(false);
        }
        self.active.shift_remove(name);
        let path = self.file_path(name);
        if path.exists() {
            std::fs::remove_file(&path).map_err(|e| Error::file(format!("刪除術語表失敗: {e}")))?;
        }
        Ok(true)
    }

    pub fn add_entry(
        &mut self,
        name: &str,
        source: &str,
        target: &str,
        category: &str,
        notes: &str,
        case_sensitive: bool,
    ) -> Result<bool> {
        let Some(g) = self.glossaries.get_mut(name) else { return Ok(false) };
        g.add_entry(source, target, category, notes, case_sensitive);
        let g = g.clone();
        self.save(&g)?;
        Ok(true)
    }

    pub fn remove_entry(&mut self, name: &str, source: &str) -> Result<bool> {
        let Some(g) = self.glossaries.get_mut(name) else { return Ok(false) };
        if !g.remove_entry(source) {
            return Ok(false);
        }
        let g = g.clone();
        self.save(&g)?;
        Ok(true)
    }

    pub fn activate(&mut self, name: &str) -> bool {
        self.glossaries.contains_key(name) && {
            self.active.insert(name.to_string());
            true
        }
    }

    pub fn deactivate(&mut self, name: &str) -> bool {
        self.active.shift_remove(name)
    }

    pub fn active(&self) -> impl Iterator<Item = &str> {
        self.active.iter().map(String::as_str)
    }

    /// 依啟用順序套用；指定語言時略過語言不符的術語表。
    pub fn apply(&self, text: &str, source_lang: &str, target_lang: &str) -> String {
        let mut result = text.to_string();
        for name in &self.active {
            let Some(g) = self.glossaries.get(name) else { continue };
            if !source_lang.is_empty() && !g.source_lang.is_empty() && g.source_lang != source_lang {
                continue;
            }
            if !target_lang.is_empty() && !g.target_lang.is_empty() && g.target_lang != target_lang {
                continue;
            }
            result = g.apply_to_text(&result);
        }
        result
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// 匯出術語表：json（同儲存格式）、csv（UTF-8 BOM、含標頭）、txt（`來源\t譯文`，# 開頭為註解）。
    pub fn export(&self, name: &str, path: &Path, format: &str) -> Result<bool> {
        let Some(g) = self.glossaries.get(name) else { return Ok(false) };
        let io_err = |e: std::io::Error| Error::file(format!("匯出術語表失敗: {e}"));
        let content = match format {
            "json" => g.to_json(),
            "csv" => {
                let mut writer = csv::WriterBuilder::new().terminator(csv::Terminator::CRLF).from_writer(Vec::new());
                let csv_err = |e: csv::Error| Error::file(format!("匯出術語表失敗: {e}"));
                writer.write_record(["source", "target", "category", "notes", "case_sensitive"]).map_err(csv_err)?;
                for e in g.entries.values() {
                    let cs = if e.case_sensitive { "True" } else { "False" };
                    writer.write_record([e.source.as_str(), &e.target, &e.category, &e.notes, cs]).map_err(csv_err)?;
                }
                let bytes = writer.into_inner().map_err(|e| Error::file(format!("匯出術語表失敗: {e}")))?;
                format!("\u{feff}{}", String::from_utf8(bytes).expect("csv 輸出為 UTF-8"))
            }
            "txt" => {
                let mut out =
                    format!("# 術語表: {}\n# 來源語言: {}\n# 目標語言: {}\n\n", g.name, g.source_lang, g.target_lang);
                for e in g.entries.values() {
                    out.push_str(&format!("{}\t{}\n", e.source, e.target));
                }
                out
            }
            other => return Err(Error::file(format!("不支援的匯出格式: {other}"))),
        };
        std::fs::write(path, content).map_err(io_err)?;
        Ok(true)
    }

    /// 依副檔名匯入（.json/.csv/.txt）並儲存；`name` 為空時用檔名（json 則用檔案內的名稱）。
    pub fn import(&mut self, path: &Path, name: Option<&str>) -> Result<&Glossary> {
        let name = name.filter(|n| !n.is_empty());
        let stem = path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
        let read = |p: &Path| std::fs::read_to_string(p).map_err(|e| Error::file(format!("匯入術語表失敗: {e}")));
        let ext = path.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
        let glossary = match ext.as_str() {
            "json" => {
                let mut g = Glossary::from_json(&read(path)?)?;
                if let Some(n) = name {
                    g.name = n.to_string();
                }
                g
            }
            "csv" => {
                let text = read(path)?;
                let mut g = Glossary::new(name.unwrap_or(&stem), "", "", "");
                let mut reader = csv::Reader::from_reader(text.trim_start_matches('\u{feff}').as_bytes());
                let headers = reader.headers().map_err(|e| Error::file(format!("匯入術語表失敗: {e}")))?.clone();
                for record in reader.records() {
                    let record = record.map_err(|e| Error::file(format!("匯入術語表失敗: {e}")))?;
                    let field = |k: &str| headers.iter().position(|h| h == k).and_then(|i| record.get(i)).unwrap_or("");
                    let cs = field("case_sensitive").to_lowercase() == "true";
                    g.add_entry(field("source"), field("target"), field("category"), field("notes"), cs);
                }
                g
            }
            "txt" => {
                let mut g = Glossary::new(name.unwrap_or(&stem), "", "", "");
                for line in read(path)?.lines() {
                    let line = py::strip(line);
                    if line.is_empty() || line.starts_with('#') {
                        continue;
                    }
                    let parts: Vec<&str> = line.split('\t').collect();
                    if parts.len() >= 2 {
                        g.add_entry(parts[0], parts[1], "", "", false);
                    }
                }
                g
            }
            other => return Err(Error::file(format!("不支援的匯入格式: .{other}"))),
        };
        self.save(&glossary)?;
        let key = glossary.name.clone();
        self.glossaries.insert(key.clone(), glossary);
        Ok(&self.glossaries[&key])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn apply_prefers_longer_terms_and_ignores_case() {
        let mut g = Glossary::new("t", "ja", "zh-tw", "");
        g.add_entry("Fire", "火", "", "", false);
        g.add_entry("Fire Department", "消防局", "", "", false);
        g.add_entry("CPR", "心肺復甦術", "", "", true);
        assert_eq!(g.apply_to_text("call the fire department, fire! CPR cpr"), "call the 消防局, 火! 心肺復甦術 cpr");
    }

    #[test]
    fn export_import_formats() {
        let dir = tempfile::tempdir().unwrap();
        let mut m = GlossaryManager::open(dir.path().join("g")).unwrap();
        m.create("t", "en", "zh", "").unwrap();
        m.add_entry("t", "Fire, Dept", "消防局", "單位", "", true).unwrap();
        for fmt in ["json", "csv", "txt"] {
            let out = dir.path().join(format!("out.{fmt}"));
            assert!(m.export("t", &out, fmt).unwrap());
            let g = m.import(&out, Some(&format!("from_{fmt}"))).unwrap();
            assert_eq!(g.entries.len(), 1, "{fmt}");
            assert_eq!(g.get_entry("Fire, Dept").unwrap().target, "消防局");
        }
        let csv = std::fs::read_to_string(dir.path().join("out.csv")).unwrap();
        assert_eq!(csv, "\u{feff}source,target,category,notes,case_sensitive\r\n\"Fire, Dept\",消防局,單位,,True\r\n");
    }

    #[test]
    fn manager_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let mut m = GlossaryManager::open(dir.path()).unwrap();
        m.create("片源/名字", "ja", "zh-tw", "").unwrap();
        m.add_entry("片源/名字", "メア", "梅雅", "人名", "", false).unwrap();
        assert!(dir.path().join("片源_名字.json").exists());

        let mut m2 = GlossaryManager::open(dir.path()).unwrap();
        assert!(m2.activate("片源/名字"));
        assert_eq!(m2.apply("メアちゃん", "ja", ""), "梅雅ちゃん");
        assert_eq!(m2.apply("メア", "en", ""), "メア");
    }
}
