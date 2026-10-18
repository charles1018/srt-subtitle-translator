//! 翻譯快取（對等 Python `core/cache.py`），與 Python 版共用 `data/translation_cache.db`。
//!
//! 相容重點：
//! - 同一 schema 與 `CACHE_VERSION`（版本不符時清空 translations，與 Python 相同）
//! - context hash：`md5("|".join(f"{len(s)}:{s}" for 非空 strip 後的上下文))`
//! - 時間欄位以 `datetime.isoformat()` 文字儲存，清理時以字串比較
//!
//! 與 Python 的差異：`import_cache` 的匯入筆數以實際新增列數計算（Python 誤用累計的 `total_changes`）。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Instant;

use md5::{Digest, Md5};
use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use serde_json::{json, Value};

use crate::config::now_isoformat;
use crate::error::{Details, Error, Result};
use crate::py;

/// v1.2: 加入翻譯風格 (style) 和提示詞版本 (prompt_version) 到快取 key
pub const CACHE_VERSION: &str = "1.2";

/// 嚴格超過 max_memory_cache 的 120% 才觸發清理
const CLEANUP_TRIGGER_RATIO: f64 = 1.2;
/// 清理後保留 70% 的最近使用項目
const CLEANUP_KEEP_RATIO: f64 = 0.7;

const PRIMARY_KEY: [&str; 5] = ["source_text", "context_hash", "model_name", "style", "prompt_version"];

/// 快取查詢鍵（不含 source_text 以外的原始上下文）。
#[derive(Debug, Clone, Copy)]
pub struct CacheKey<'a> {
    pub source_text: &'a str,
    pub model_name: &'a str,
    pub style: &'a str,
    pub prompt_version: &'a str,
}

impl<'a> CacheKey<'a> {
    pub fn new(source_text: &'a str, model_name: &'a str, style: &'a str, prompt_version: &'a str) -> Self {
        Self { source_text, model_name, style, prompt_version }
    }
}

/// 計算上下文雜湊（對等 `_compute_context_hash`）。
pub fn compute_context_hash<S: AsRef<str>>(context_texts: &[S]) -> String {
    let parts: Vec<String> = context_texts
        .iter()
        .map(|t| py::strip(t.as_ref()))
        .filter(|s| !s.is_empty())
        .map(|s| format!("{}:{s}", py::len(s)))
        .collect();
    md5_hex(&parts.join("|"))
}

pub fn md5_hex(text: &str) -> String {
    let digest = Md5::digest(text.as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

fn memory_key(key: &CacheKey<'_>, context_hash: &str) -> String {
    format!("{}|{context_hash}|{}|{}|{}", key.source_text, key.model_name, key.style, key.prompt_version)
}

fn is_error_translation(text: &str) -> bool {
    py::strip(text).starts_with("[翻譯錯誤")
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct CacheStats {
    pub total_queries: u64,
    pub cache_hits: u64,
    pub db_errors: u64,
    pub last_cleanup: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CacheReport {
    #[serde(flatten)]
    pub stats: CacheStats,
    pub total_records: i64,
    pub db_size_mb: f64,
    pub models: Vec<(String, i64)>,
    pub top_used: Vec<Value>,
    pub hit_rate: f64,
    pub memory_cache_size: usize,
    pub memory_cache_limit: usize,
}

struct MemoryEntry {
    target_text: String,
    last_accessed: Instant,
}

pub struct CacheManager {
    db_path: PathBuf,
    conn: Mutex<Connection>,
    memory: Mutex<HashMap<String, MemoryEntry>>,
    stats: Mutex<CacheStats>,
    pub max_memory_cache: usize,
    pub auto_cleanup_days: i64,
}

fn db_error(e: rusqlite::Error) -> Error {
    let mut details = Details::new();
    details.insert("error".into(), e.to_string().into());
    Error::Config { message: "快取資料庫錯誤".into(), details }
}

impl CacheManager {
    /// 開啟（必要時建立/遷移）快取資料庫並執行每日一次的過期清理。
    /// 資料庫損壞時嘗試由 `.bak` 還原，沒有備份則重建。
    pub fn open(db_path: impl Into<PathBuf>, max_memory_cache: usize, auto_cleanup_days: i64) -> Result<Self> {
        let db_path: PathBuf = db_path.into();
        let db_path = if db_path.as_os_str().is_empty() { PathBuf::from("data/translation_cache.db") } else { db_path };
        if let Some(parent) = db_path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent).map_err(|e| Error::file(format!("無法建立快取目錄: {e}")))?;
        }
        let conn = match Self::init_db(&db_path, auto_cleanup_days) {
            Ok(conn) => conn,
            Err(_) => {
                Self::recover(&db_path)?;
                Self::init_db(&db_path, auto_cleanup_days).map_err(db_error)?
            }
        };
        Ok(Self {
            db_path,
            conn: Mutex::new(conn),
            memory: Mutex::new(HashMap::new()),
            stats: Mutex::new(CacheStats::default()),
            max_memory_cache: max_memory_cache.max(1),
            auto_cleanup_days: auto_cleanup_days.max(1),
        })
    }

    fn init_db(path: &Path, auto_cleanup_days: i64) -> rusqlite::Result<Connection> {
        let conn = Connection::open(path)?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;
        ensure_schema(&conn)?;
        auto_cleanup(&conn, auto_cleanup_days)?;
        Ok(conn)
    }

    fn recover(path: &Path) -> Result<()> {
        let backup = backup_path(path);
        let _ = std::fs::remove_file(path);
        if backup.exists() {
            std::fs::copy(&backup, path).map_err(|e| Error::file(format!("從備份復原資料庫失敗: {e}")))?;
        }
        Ok(())
    }

    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    /// 查詢快取：先記憶體、後資料庫。空白原文回傳 `Some("")`；錯誤翻譯會被刪除並視為未命中。
    pub fn get(&self, key: CacheKey<'_>, context_texts: &[String]) -> Option<String> {
        self.stats.lock().unwrap().total_queries += 1;
        if py::strip(key.source_text).is_empty() {
            return Some(String::new());
        }
        let context_hash = compute_context_hash(context_texts);
        let mem_key = memory_key(&key, &context_hash);
        {
            let mut memory = self.memory.lock().unwrap();
            if let Some(entry) = memory.get_mut(&mem_key) {
                if is_error_translation(&entry.target_text) {
                    memory.remove(&mem_key);
                } else {
                    entry.last_accessed = Instant::now();
                    self.stats.lock().unwrap().cache_hits += 1;
                    return Some(entry.target_text.clone());
                }
            }
        }

        let result = self.lookup_db(&key, &context_hash);
        match result {
            Ok(Some(target)) => {
                self.remember(mem_key, target.clone());
                self.stats.lock().unwrap().cache_hits += 1;
                Some(target)
            }
            Ok(None) => None,
            Err(_) => {
                self.stats.lock().unwrap().db_errors += 1;
                None
            }
        }
    }

    fn lookup_db(&self, key: &CacheKey<'_>, context_hash: &str) -> rusqlite::Result<Option<String>> {
        let conn = self.conn.lock().unwrap();
        let where_clause =
            "source_text = ?1 AND context_hash = ?2 AND model_name = ?3 AND style = ?4 AND prompt_version = ?5";
        let key_params = params![key.source_text, context_hash, key.model_name, key.style, key.prompt_version];
        let row: Option<(String, i64)> = conn
            .query_row(
                &format!("SELECT target_text, usage_count FROM translations WHERE {where_clause}"),
                key_params,
                |r| Ok((r.get::<_, Option<String>>(0)?.unwrap_or_default(), r.get::<_, Option<i64>>(1)?.unwrap_or(0))),
            )
            .optional()?;
        let Some((target, usage_count)) = row else { return Ok(None) };
        if is_error_translation(&target) {
            conn.execute(&format!("DELETE FROM translations WHERE {where_clause}"), key_params)?;
            return Ok(None);
        }
        conn.execute(
            "UPDATE translations SET usage_count = ?1, last_used = ?2 WHERE source_text = ?3 AND context_hash = ?4 \
             AND model_name = ?5 AND style = ?6 AND prompt_version = ?7",
            params![
                usage_count + 1,
                now_isoformat(),
                key.source_text,
                context_hash,
                key.model_name,
                key.style,
                key.prompt_version
            ],
        )?;
        Ok(Some(target))
    }

    fn remember(&self, mem_key: String, target_text: String) {
        let mut memory = self.memory.lock().unwrap();
        memory.insert(mem_key, MemoryEntry { target_text, last_accessed: Instant::now() });
        if memory.len() as f64 > self.max_memory_cache as f64 * CLEANUP_TRIGGER_RATIO {
            self.clean_memory(&mut memory);
        }
    }

    /// 移除最久未使用的項目，保留 70%。
    fn clean_memory(&self, memory: &mut HashMap<String, MemoryEntry>) {
        let keep = (self.max_memory_cache as f64 * CLEANUP_KEEP_RATIO) as usize;
        if memory.len() <= keep {
            return;
        }
        let mut by_age: Vec<(String, Instant)> = memory.iter().map(|(k, v)| (k.clone(), v.last_accessed)).collect();
        by_age.sort_by_key(|(_, t)| *t);
        let remove = by_age.len() - keep;
        for (k, _) in by_age.into_iter().take(remove) {
            memory.remove(&k);
        }
    }

    /// 儲存翻譯結果；空白原文/譯文或錯誤翻譯不儲存。
    pub fn store(&self, key: CacheKey<'_>, target_text: &str, context_texts: &[String]) -> bool {
        if py::strip(key.source_text).is_empty()
            || py::strip(target_text).is_empty()
            || is_error_translation(target_text)
        {
            return false;
        }
        let context_hash = compute_context_hash(context_texts);
        self.remember(memory_key(&key, &context_hash), target_text.to_string());
        let now = now_isoformat();
        let result = self.conn.lock().unwrap().execute(
            "INSERT OR REPLACE INTO translations (source_text, target_text, context_hash, model_name, style, \
             prompt_version, created_at, usage_count, last_used) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 1, ?7)",
            params![key.source_text, target_text, context_hash, key.model_name, key.style, key.prompt_version, now],
        );
        match result {
            Ok(_) => true,
            Err(_) => {
                self.stats.lock().unwrap().db_errors += 1;
                false
            }
        }
    }

    /// 清理超過指定天數未使用的紀錄，之後建立備份並最佳化資料庫。
    pub fn clear_old(&self, days_threshold: Option<i64>) -> Result<usize> {
        let days = days_threshold.unwrap_or(self.auto_cleanup_days);
        let deleted = {
            let conn = self.conn.lock().unwrap();
            let deleted = delete_older_than(&conn, days).map_err(db_error)?;
            let now = now_isoformat();
            conn.execute("INSERT OR REPLACE INTO cache_metadata (key, value) VALUES ('last_cleanup', ?1)", [&now])
                .map_err(db_error)?;
            self.stats.lock().unwrap().last_cleanup = Some(now);
            deleted
        };
        self.create_backup();
        self.optimize()?;
        Ok(deleted)
    }

    pub fn clear_by_model(&self, model_name: &str) -> Result<usize> {
        let deleted = self
            .conn
            .lock()
            .unwrap()
            .execute("DELETE FROM translations WHERE model_name = ?1", [model_name])
            .map_err(db_error)?;
        self.memory.lock().unwrap().retain(|k, _| k.split('|').nth(2) != Some(model_name));
        Ok(deleted)
    }

    /// 清空所有快取；預設備份失敗時中止以保護資料。
    pub fn clear_all(&self, force: bool) -> Result<()> {
        if !self.create_backup() && !force {
            return Err(Error::file("備份失敗，中止清空快取操作以保護資料。如需強制清空，請使用 force"));
        }
        self.conn.lock().unwrap().execute("DELETE FROM translations", []).map_err(db_error)?;
        self.memory.lock().unwrap().clear();
        Ok(())
    }

    /// 建立 `<db>.bak`（先 checkpoint WAL，確保備份完整）。
    pub fn create_backup(&self) -> bool {
        let conn = self.conn.lock().unwrap();
        let _ = conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE)");
        std::fs::copy(&self.db_path, backup_path(&self.db_path)).is_ok()
    }

    pub fn optimize(&self) -> Result<()> {
        self.conn.lock().unwrap().execute_batch("VACUUM; ANALYZE;").map_err(db_error)
    }

    pub fn stats(&self) -> Result<CacheReport> {
        let stats = self.stats.lock().unwrap().clone();
        let conn = self.conn.lock().unwrap();
        let total_records: i64 =
            conn.query_row("SELECT COUNT(*) FROM translations", [], |r| r.get(0)).map_err(db_error)?;
        let mut stmt =
            conn.prepare("SELECT model_name, COUNT(*) FROM translations GROUP BY model_name").map_err(db_error)?;
        let models = stmt
            .query_map([], |r| Ok((r.get::<_, Option<String>>(0)?.unwrap_or_default(), r.get(1)?)))
            .and_then(Iterator::collect)
            .map_err(db_error)?;
        let mut stmt = conn
            .prepare("SELECT source_text, target_text, usage_count, model_name FROM translations ORDER BY usage_count DESC LIMIT 10")
            .map_err(db_error)?;
        let top_used = stmt
            .query_map([], |r| {
                Ok(json!({
                    "source": r.get::<_, Option<String>>(0)?,
                    "target": r.get::<_, Option<String>>(1)?,
                    "count": r.get::<_, Option<i64>>(2)?,
                    "model": r.get::<_, Option<String>>(3)?,
                }))
            })
            .and_then(Iterator::collect)
            .map_err(db_error)?;
        let hit_rate =
            if stats.total_queries > 0 { stats.cache_hits as f64 / stats.total_queries as f64 * 100.0 } else { 0.0 };
        let db_size_mb = std::fs::metadata(&self.db_path).map(|m| m.len() as f64 / (1024.0 * 1024.0)).unwrap_or(0.0);
        Ok(CacheReport {
            stats,
            total_records,
            db_size_mb,
            models,
            top_used,
            hit_rate,
            memory_cache_size: self.memory.lock().unwrap().len(),
            memory_cache_limit: self.max_memory_cache,
        })
    }

    /// 匯出為 JSON（格式與 Python `export_cache` 相同）。
    pub fn export(&self, output_path: &Path) -> Result<usize> {
        let entries: Vec<Value> = {
            let conn = self.conn.lock().unwrap();
            let mut stmt = conn
                .prepare("SELECT source_text, target_text, context_hash, model_name, created_at, usage_count FROM translations")
                .map_err(db_error)?;
            stmt.query_map([], |r| {
                Ok(json!({
                    "source_text": r.get::<_, Option<String>>(0)?,
                    "target_text": r.get::<_, Option<String>>(1)?,
                    "context_hash": r.get::<_, Option<String>>(2)?,
                    "model_name": r.get::<_, Option<String>>(3)?,
                    "created_at": r.get::<_, Option<String>>(4)?,
                    "usage_count": r.get::<_, Option<i64>>(5)?,
                }))
            })
            .and_then(Iterator::collect)
            .map_err(db_error)?
        };
        let count = entries.len();
        let data = json!({"version": CACHE_VERSION, "exported_at": now_isoformat(), "entries": entries});
        if let Some(parent) = output_path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent).map_err(|e| Error::file(format!("無法建立輸出目錄: {e}")))?;
        }
        std::fs::write(output_path, serde_json::to_string_pretty(&data).expect("JSON 序列化不會失敗"))
            .map_err(|e| Error::file(format!("匯出快取失敗: {e}")))?;
        Ok(count)
    }

    /// 匯入 JSON（接受版本 1.2 與 1.0），已存在的鍵略過；回傳新增筆數。
    pub fn import(&self, input_path: &Path) -> Result<usize> {
        let text = std::fs::read_to_string(input_path)
            .map_err(|e| Error::file(format!("匯入檔案不存在或無法讀取: {} ({e})", input_path.display())))?;
        let data: Value = serde_json::from_str(&text).map_err(|e| Error::file(format!("匯入檔案格式錯誤: {e}")))?;
        let version = data.get("version").and_then(Value::as_str);
        if !matches!(version, Some(CACHE_VERSION) | Some("1.0")) {
            return Err(Error::file(format!("快取版本不匹配: {} != {CACHE_VERSION}", version.unwrap_or("未知"))));
        }
        self.create_backup();
        let mut imported = 0;
        {
            let conn = self.conn.lock().unwrap();
            for entry in data.get("entries").and_then(Value::as_array).into_iter().flatten() {
                let field = |k: &str| entry.get(k).and_then(Value::as_str);
                let (Some(source), Some(target), Some(ctx), Some(model)) =
                    (field("source_text"), field("target_text"), field("context_hash"), field("model_name"))
                else {
                    continue;
                };
                let created_at = field("created_at").map_or_else(now_isoformat, str::to_string);
                let usage_count = entry.get("usage_count").and_then(Value::as_i64).unwrap_or(1);
                if let Ok(changed) = conn.execute(
                    "INSERT OR IGNORE INTO translations (source_text, target_text, context_hash, model_name, created_at, \
                     usage_count, last_used) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                    params![source, target, ctx, model, created_at, usage_count, now_isoformat()],
                ) {
                    imported += changed;
                }
            }
        }
        self.memory.lock().unwrap().clear();
        Ok(imported)
    }

    /// 以關鍵字搜尋原文或譯文（最多 100 筆，依使用次數排序）。
    pub fn search(&self, keyword: &str, model_name: Option<&str>) -> Result<Vec<Value>> {
        let conn = self.conn.lock().unwrap();
        let pattern = format!("%{keyword}%");
        let mut sql = "SELECT source_text, target_text, model_name, usage_count, last_used FROM translations \
                       WHERE (source_text LIKE ?1 OR target_text LIKE ?1)"
            .to_string();
        if model_name.is_some() {
            sql.push_str(" AND model_name = ?2");
        }
        sql.push_str(" ORDER BY usage_count DESC LIMIT 100");
        let mut stmt = conn.prepare(&sql).map_err(db_error)?;
        let map_row = |r: &rusqlite::Row<'_>| {
            Ok(json!({
                "source_text": r.get::<_, Option<String>>(0)?,
                "target_text": r.get::<_, Option<String>>(1)?,
                "model_name": r.get::<_, Option<String>>(2)?,
                "usage_count": r.get::<_, Option<i64>>(3)?,
                "last_used": r.get::<_, Option<String>>(4)?,
            }))
        };
        let rows = match model_name {
            Some(m) => stmt.query_map(params![pattern, m], map_row),
            None => stmt.query_map(params![pattern], map_row),
        };
        rows.and_then(Iterator::collect).map_err(db_error)
    }
}

fn backup_path(db_path: &Path) -> PathBuf {
    let mut s = db_path.as_os_str().to_os_string();
    s.push(".bak");
    PathBuf::from(s)
}

fn table_exists(conn: &Connection, name: &str) -> rusqlite::Result<bool> {
    conn.query_row("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1", [name], |_| Ok(()))
        .optional()
        .map(|r| r.is_some())
}

const CREATE_TRANSLATIONS: &str = "
            CREATE TABLE IF NOT EXISTS translations (
                source_text TEXT,
                target_text TEXT,
                context_hash TEXT,
                model_name TEXT,
                style TEXT DEFAULT 'standard',
                prompt_version TEXT DEFAULT '',
                created_at timestamp,
                usage_count INTEGER,
                last_used timestamp,
                PRIMARY KEY (source_text, context_hash, model_name, style, prompt_version)
            )
        ";

const CREATE_METADATA: &str = "
            CREATE TABLE IF NOT EXISTS cache_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ";

fn translations_schema_is_current(conn: &Connection) -> rusqlite::Result<bool> {
    let mut stmt = conn.prepare("PRAGMA table_info(translations)")?;
    let columns: Vec<(String, i64)> =
        stmt.query_map([], |r| Ok((r.get(1)?, r.get(5)?)))?.collect::<rusqlite::Result<_>>()?;
    let required = [
        "source_text",
        "target_text",
        "context_hash",
        "model_name",
        "style",
        "prompt_version",
        "created_at",
        "usage_count",
        "last_used",
    ];
    if !required.iter().all(|c| columns.iter().any(|(name, _)| name == c)) {
        return Ok(false);
    }
    let mut pk: Vec<&(String, i64)> = columns.iter().filter(|(_, p)| *p > 0).collect();
    pk.sort_by_key(|(_, p)| *p);
    Ok(pk.iter().map(|(n, _)| n.as_str()).eq(PRIMARY_KEY))
}

fn ensure_schema(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(CREATE_METADATA)?;
    let current_version: Option<String> =
        conn.query_row("SELECT value FROM cache_metadata WHERE key = 'version'", [], |r| r.get(0)).optional()?;
    let translations_exists = table_exists(conn, "translations")?;
    if translations_exists && current_version.as_deref().is_some_and(|v| v != CACHE_VERSION) {
        conn.execute_batch("DROP TABLE IF EXISTS translations")?;
        conn.execute_batch(CREATE_TRANSLATIONS)?;
    } else {
        conn.execute_batch(CREATE_TRANSLATIONS)?;
        if translations_exists && !translations_schema_is_current(conn)? {
            conn.execute_batch("DROP TABLE IF EXISTS translations")?;
            conn.execute_batch(CREATE_TRANSLATIONS)?;
        }
    }
    conn.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_context ON translations(context_hash);
         CREATE INDEX IF NOT EXISTS idx_model ON translations(model_name);
         CREATE INDEX IF NOT EXISTS idx_usage ON translations(usage_count);
         CREATE INDEX IF NOT EXISTS idx_last_used ON translations(last_used);
         CREATE INDEX IF NOT EXISTS idx_style ON translations(style);",
    )?;
    match current_version {
        None => {
            conn.execute("INSERT INTO cache_metadata (key, value) VALUES ('version', ?1)", [CACHE_VERSION])?;
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES ('created_at', ?1)",
                [now_isoformat()],
            )?;
        }
        Some(v) if v != CACHE_VERSION => {
            conn.execute("DELETE FROM translations", [])?;
            conn.execute("UPDATE cache_metadata SET value = ?1 WHERE key = 'version'", [CACHE_VERSION])?;
        }
        Some(_) => {}
    }
    Ok(())
}

fn delete_older_than(conn: &Connection, days: i64) -> rusqlite::Result<usize> {
    let threshold =
        (chrono::Local::now().naive_local() - chrono::Duration::days(days)).format("%Y-%m-%dT%H:%M:%S%.6f").to_string();
    conn.execute("DELETE FROM translations WHERE last_used < ?1", [threshold])
}

/// 距離上次清理超過一天才執行。
fn auto_cleanup(conn: &Connection, days: i64) -> rusqlite::Result<()> {
    let last: Option<String> =
        conn.query_row("SELECT value FROM cache_metadata WHERE key = 'last_cleanup'", [], |r| r.get(0)).optional()?;
    let now = chrono::Local::now().naive_local();
    if let Some(parsed) = last.as_deref().and_then(parse_isoformat) {
        if now - parsed < chrono::Duration::days(1) {
            return Ok(());
        }
    }
    delete_older_than(conn, days)?;
    conn.execute(
        "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES ('last_cleanup', ?1)",
        [now.format("%Y-%m-%dT%H:%M:%S%.6f").to_string()],
    )?;
    Ok(())
}

fn parse_isoformat(s: &str) -> Option<chrono::NaiveDateTime> {
    chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f")
        .or_else(|_| chrono::NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S"))
        .ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn store_and_get_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let cache = CacheManager::open(dir.path().join("c.db"), 1000, 30).unwrap();
        let key = CacheKey::new("こんにちは", "m", "standard", "abcd1234");
        let context = ctx(&["前", "こんにちは", "後"]);
        assert_eq!(cache.get(key, &context), None);
        assert!(cache.store(key, "你好", &context));
        assert_eq!(cache.get(key, &context).as_deref(), Some("你好"));

        // 新的 manager（無記憶體快取）也能從 DB 讀到
        drop(cache);
        let cache = CacheManager::open(dir.path().join("c.db"), 1000, 30).unwrap();
        assert_eq!(cache.get(key, &context).as_deref(), Some("你好"));
        assert_eq!(cache.get(CacheKey::new("こんにちは", "m", "literal", "abcd1234"), &context), None);
        assert_eq!(cache.stats().unwrap().total_records, 1);
    }

    #[test]
    fn error_translations_are_not_cached() {
        let dir = tempfile::tempdir().unwrap();
        let cache = CacheManager::open(dir.path().join("c.db"), 1000, 30).unwrap();
        let key = CacheKey::new("a", "m", "standard", "");
        assert!(!cache.store(key, "[翻譯錯誤] x", &[]));
        assert!(!cache.store(key, "  ", &[]));
        assert_eq!(cache.get(CacheKey::new(" ", "m", "standard", ""), &[]).as_deref(), Some(""));
    }

    #[test]
    fn context_hash_ignores_blank_and_counts_code_points() {
        assert_eq!(compute_context_hash(&["", "  "]), md5_hex(""));
        assert_eq!(compute_context_hash(&[" 日本 ", "ab"]), md5_hex("2:日本|2:ab"));
    }

    #[test]
    fn memory_cleanup_keeps_recent() {
        let dir = tempfile::tempdir().unwrap();
        let cache = CacheManager::open(dir.path().join("c.db"), 10, 30).unwrap();
        for i in 0..13 {
            let s = format!("s{i}");
            cache.store(CacheKey::new(&s, "m", "standard", ""), "t", &[]);
        }
        assert_eq!(cache.memory.lock().unwrap().len(), 7);
    }

    #[test]
    fn export_import_and_clear_by_model() {
        let dir = tempfile::tempdir().unwrap();
        let cache = CacheManager::open(dir.path().join("c.db"), 1000, 30).unwrap();
        cache.store(CacheKey::new("a", "m1", "standard", ""), "甲", &[]);
        cache.store(CacheKey::new("b", "m2", "standard", ""), "乙", &[]);
        let out = dir.path().join("export/cache.json");
        assert_eq!(cache.export(&out).unwrap(), 2);
        assert_eq!(cache.clear_by_model("m1").unwrap(), 1);
        assert_eq!(cache.search("乙", None).unwrap().len(), 1);
        assert_eq!(cache.import(&out).unwrap(), 1);
        cache.clear_all(false).unwrap();
        assert_eq!(cache.stats().unwrap().total_records, 0);
    }

    #[test]
    fn old_version_is_migrated() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("c.db");
        {
            let conn = Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE cache_metadata (key TEXT PRIMARY KEY, value TEXT);
                 INSERT INTO cache_metadata VALUES ('version', '1.1');
                 CREATE TABLE translations (source_text TEXT, target_text TEXT, context_hash TEXT, model_name TEXT,
                   created_at timestamp, usage_count INTEGER, last_used timestamp,
                   PRIMARY KEY (source_text, context_hash, model_name));",
            )
            .unwrap();
        }
        let cache = CacheManager::open(&path, 1000, 30).unwrap();
        assert!(cache.store(CacheKey::new("a", "m", "standard", "v"), "甲", &[]));
    }
}
