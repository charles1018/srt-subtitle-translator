import sqlite3
import os
import json
import time
import shutil
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import hashlib
from functools import lru_cache

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='logs/cache.log'
)
logger = logging.getLogger('CacheManager')

# 快取版本，用於不同版本間的快取相容性
CACHE_VERSION = "1.0"

class CacheManager:
    def __init__(self, db_path: str = "data/translation_cache.db"):
        # 確保目錄存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.db_path = db_path
        self.memory_cache = {}  # 記憶體快取層
        self.stats = {
            "total_queries": 0,
            "cache_hits": 0,
            "db_errors": 0,
            "last_cleanup": None
        }
        self._init_db()
        
        # 記憶體快取的最大數量
        self.max_memory_cache = 1000
        
    def _init_db(self):
        """初始化快取資料庫並添加效能優化"""
        def adapt_datetime(dt):
            return dt.isoformat()

        def convert_datetime(s):
            try:
                return datetime.fromisoformat(s.decode())
            except:
                return datetime.now()

        sqlite3.register_adapter(datetime, adapt_datetime)
        sqlite3.register_converter("timestamp", convert_datetime)
        
        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                # 啟用WAL模式提高寫入效能
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                
                # 建立快取表格
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS translations (
                        source_text TEXT,
                        target_text TEXT,
                        context_hash TEXT,
                        model_name TEXT,
                        created_at timestamp,
                        usage_count INTEGER,
                        last_used timestamp,
                        PRIMARY KEY (source_text, context_hash, model_name)
                    )
                """)
                
                # 建立快取元數據表格
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                
                # 添加索引提高查詢速度
                conn.execute("CREATE INDEX IF NOT EXISTS idx_context ON translations(context_hash)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_model ON translations(model_name)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_usage ON translations(usage_count)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_last_used ON translations(last_used)")
                
                # 檢查快取版本
                self._check_cache_version(conn)
                
                # 清理過舊的紀錄
                self._auto_cleanup(conn)
                
            logger.info(f"快取資料庫初始化完成: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"初始化資料庫時發生錯誤: {str(e)}")
            # 如果資料庫損壞，嘗試復原
            self._recover_db_if_needed()
    
    def _check_cache_version(self, conn):
        """檢查快取版本，確保相容性"""
        try:
            cursor = conn.execute("SELECT value FROM cache_metadata WHERE key = 'version'")
            result = cursor.fetchone()
            
            if not result:
                # 新建快取，設定版本
                conn.execute(
                    "INSERT INTO cache_metadata (key, value) VALUES (?, ?)",
                    ("version", CACHE_VERSION)
                )
                conn.execute(
                    "INSERT INTO cache_metadata (key, value) VALUES (?, ?)",
                    ("created_at", datetime.now().isoformat())
                )
            elif result[0] != CACHE_VERSION:
                # 快取版本不匹配，清理舊數據
                logger.warning(f"快取版本不匹配: 目前={result[0]}, 需要={CACHE_VERSION}")
                conn.execute("DELETE FROM translations")
                conn.execute(
                    "UPDATE cache_metadata SET value = ? WHERE key = 'version'",
                    (CACHE_VERSION,)
                )
        except sqlite3.Error as e:
            logger.error(f"檢查快取版本時發生錯誤: {str(e)}")
    
    def _recover_db_if_needed(self):
        """嘗試復原損壞的資料庫"""
        try:
            # 檢查是否有備份
            backup_path = f"{self.db_path}.bak"
            if os.path.exists(backup_path):
                # 復原備份
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                shutil.copy(backup_path, self.db_path)
                logger.info(f"已從備份復原資料庫: {backup_path}")
            else:
                # 如果沒有備份，重新建立資料庫
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                self._init_db()
        except Exception as e:
            logger.error(f"復原資料庫時發生錯誤: {str(e)}")
    
    def _create_backup(self):
        """建立資料庫備份"""
        try:
            backup_path = f"{self.db_path}.bak"
            shutil.copy(self.db_path, backup_path)
            logger.info(f"已建立資料庫備份: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"建立資料庫備份時發生錯誤: {str(e)}")
            return False
    
    @lru_cache(maxsize=1000)
    def _compute_context_hash(self, context_tuple: Tuple[str, ...]) -> str:
        """計算上下文的雜湊值，使用LRU快取加速"""
        context_str = "".join([text.strip() for text in context_tuple if text.strip()])
        return hashlib.md5(context_str.encode()).hexdigest()
    
    def _generate_cache_key(self, source_text: str, context_hash: str, model_name: str) -> str:
        """產生記憶體快取的鍵值"""
        return f"{source_text}|{context_hash}|{model_name}"

    def get_cached_translation(self, source_text: str, context_texts: List[str], model_name: str) -> Optional[str]:
        """獲取快取的翻譯結果，先檢查記憶體，再檢查資料庫"""
        self.stats["total_queries"] += 1
        
        # 計算上下文雜湊
        context_hash = self._compute_context_hash(tuple(context_texts))
        
        # 檢查記憶體快取
        cache_key = self._generate_cache_key(source_text, context_hash, model_name)
        if cache_key in self.memory_cache:
            self.stats["cache_hits"] += 1
            self.memory_cache[cache_key]["last_accessed"] = time.time()
            return self.memory_cache[cache_key]["target_text"]
        
        # 檢查資料庫快取
        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.execute("""
                    SELECT target_text, usage_count 
                    FROM translations 
                    WHERE source_text = ? AND context_hash = ? AND model_name = ?
                """, (source_text, context_hash, model_name))
                
                result = cursor.fetchone()
                if result:
                    target_text, usage_count = result
                    # 更新使用統計
                    conn.execute("""
                        UPDATE translations 
                        SET usage_count = ?, last_used = ?
                        WHERE source_text = ? AND context_hash = ? AND model_name = ?
                    """, (usage_count + 1, datetime.now(), source_text, context_hash, model_name))
                    
                    # 添加到記憶體快取
                    self.memory_cache[cache_key] = {
                        "target_text": target_text,
                        "last_accessed": time.time()
                    }
                    
                    # 快取過大時清理
                    if len(self.memory_cache) > self.max_memory_cache:
                        self._clean_memory_cache()
                    
                    self.stats["cache_hits"] += 1
                    return target_text
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"資料庫查詢錯誤: {str(e)}")
        
        return None

    def store_translation(self, source_text: str, target_text: str, context_texts: List[str], model_name: str) -> bool:
        """儲存翻譯結果到快取"""
        # 計算上下文雜湊
        context_hash = self._compute_context_hash(tuple(context_texts))
        
        # 添加到記憶體快取
        cache_key = self._generate_cache_key(source_text, context_hash, model_name)
        self.memory_cache[cache_key] = {
            "target_text": target_text,
            "last_accessed": time.time()
        }
        
        # 快取過大時清理
        if len(self.memory_cache) > self.max_memory_cache:
            self._clean_memory_cache()
        
        # 儲存到資料庫
        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO translations 
                    (source_text, target_text, context_hash, model_name, created_at, usage_count, last_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (source_text, target_text, context_hash, model_name, datetime.now(), 1, datetime.now()))
            return True
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"資料庫儲存錯誤: {str(e)}")
            return False

    def _clean_memory_cache(self):
        """清理記憶體快取，移除最久未使用的項目"""
        if len(self.memory_cache) <= self.max_memory_cache // 2:
            return
        
        # 按最後存取時間排序
        sorted_items = sorted(
            self.memory_cache.items(), 
            key=lambda x: x[1]["last_accessed"]
        )
        
        # 保留一半最近使用的項目
        keep_count = self.max_memory_cache // 2
        for key, _ in sorted_items[:-keep_count]:
            del self.memory_cache[key]
        
        logger.info(f"已清理記憶體快取至 {len(self.memory_cache)} 項")

    def _auto_cleanup(self, conn, days_threshold: int = 30):
        """自動清理過期快取"""
        try:
            # 檢查上次清理時間
            cursor = conn.execute("SELECT value FROM cache_metadata WHERE key = 'last_cleanup'")
            result = cursor.fetchone()
            
            current_time = datetime.now()
            if result:
                last_cleanup = datetime.fromisoformat(result[0])
                # 如果距離上次清理不到1天，則跳過
                if current_time - last_cleanup < timedelta(days=1):
                    return
            
            # 執行清理
            threshold_date = current_time - timedelta(days=days_threshold)
            conn.execute(
                "DELETE FROM translations WHERE last_used < ?", 
                (threshold_date,)
            )
            
            # 更新上次清理時間
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                ("last_cleanup", current_time.isoformat())
            )
            
            self.stats["last_cleanup"] = current_time.isoformat()
            logger.info(f"自動清理已完成，刪除了 {conn.total_changes} 條過期快取")
        except sqlite3.Error as e:
            logger.error(f"自動清理時發生錯誤: {str(e)}")

    def clear_old_cache(self, days_threshold: int = 30) -> int:
        """手動清理過期快取 (超過一定天數的舊資料)"""
        threshold_date = datetime.now() - timedelta(days=days_threshold)
        deleted_count = 0
        
        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.execute(
                    "DELETE FROM translations WHERE last_used < ?", 
                    (threshold_date,)
                )
                deleted_count = cursor.rowcount
                
                # 更新上次清理時間
                conn.execute(
                    "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                    ("last_cleanup", datetime.now().isoformat())
                )
                
                self.stats["last_cleanup"] = datetime.now().isoformat()
                
            # 建立備份
            self._create_backup()
            
            logger.info(f"已清理 {deleted_count} 條過期快取")
            return deleted_count
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"清理快取時發生錯誤: {str(e)}")
            return 0

    def clear_cache_by_model(self, model_name: str) -> int:
        """按模型清理快取"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM translations WHERE model_name = ?", 
                    (model_name,)
                )
                deleted_count = cursor.rowcount
            
            # 清理記憶體快取中相關條目
            keys_to_remove = [
                key for key in self.memory_cache 
                if key.split("|")[2] == model_name
            ]
            for key in keys_to_remove:
                del self.memory_cache[key]
                
            logger.info(f"已清理模型 {model_name} 的 {deleted_count} 條快取")
            return deleted_count
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"按模型清理快取時發生錯誤: {str(e)}")
            return 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """獲取快取統計資訊"""
        stats = self.stats.copy()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 獲取總記錄數
                cursor = conn.execute("SELECT COUNT(*) FROM translations")
                stats["total_records"] = cursor.fetchone()[0]
                
                # 獲取資料庫大小
                stats["db_size_mb"] = os.path.getsize(self.db_path) / (1024 * 1024)
                
                # 獲取按模型分類的快取統計
                cursor = conn.execute(
                    "SELECT model_name, COUNT(*) FROM translations GROUP BY model_name"
                )
                stats["models"] = {row[0]: row[1] for row in cursor.fetchall()}
                
                # 獲取使用率最高的10個快取
                cursor = conn.execute(
                    "SELECT source_text, target_text, usage_count, model_name "
                    "FROM translations ORDER BY usage_count DESC LIMIT 10"
                )
                stats["top_used"] = [
                    {
                        "source": row[0], 
                        "target": row[1], 
                        "count": row[2],
                        "model": row[3]
                    } 
                    for row in cursor.fetchall()
                ]
                
                # 計算命中率
                if stats["total_queries"] > 0:
                    stats["hit_rate"] = (stats["cache_hits"] / stats["total_queries"]) * 100
                else:
                    stats["hit_rate"] = 0
                
            return stats
        except sqlite3.Error as e:
            logger.error(f"獲取快取統計時發生錯誤: {str(e)}")
            return self.stats

    def export_cache(self, output_path: str) -> bool:
        """匯出快取資料到JSON檔案"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT 
                        source_text, target_text, context_hash, 
                        model_name, created_at, usage_count
                    FROM translations
                """)
                
                data = {
                    "version": CACHE_VERSION,
                    "exported_at": datetime.now().isoformat(),
                    "entries": [dict(row) for row in cursor.fetchall()]
                }
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"已匯出 {len(data['entries'])} 條快取記錄到 {output_path}")
                return True
        except Exception as e:
            logger.error(f"匯出快取時發生錯誤: {str(e)}")
            return False

    def import_cache(self, input_path: str) -> Tuple[bool, int]:
        """從JSON檔案匯入快取資料"""
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 檢查版本相容性
            if "version" not in data or data["version"] != CACHE_VERSION:
                logger.warning(f"快取版本不匹配: {data.get('version', '未知')} != {CACHE_VERSION}")
                return False, 0
            
            imported_count = 0
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                for entry in data["entries"]:
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO translations 
                            (source_text, target_text, context_hash, model_name, created_at, usage_count, last_used)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            entry["source_text"], 
                            entry["target_text"], 
                            entry["context_hash"],
                            entry["model_name"],
                            entry["created_at"],
                            entry["usage_count"],
                            datetime.now()
                        ))
                        if conn.total_changes > 0:
                            imported_count += 1
                    except (KeyError, sqlite3.Error) as e:
                        logger.warning(f"匯入條目時發生錯誤: {str(e)}")
                        continue
            
            logger.info(f"已匯入 {imported_count} 條快取記錄從 {input_path}")
            return True, imported_count
        except Exception as e:
            logger.error(f"匯入快取時發生錯誤: {str(e)}")
            return False, 0

    def optimize_database(self) -> bool:
        """最佳化資料庫以提高效能"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")
                conn.execute("ANALYZE")
            logger.info("資料庫最佳化完成")
            return True
        except sqlite3.Error as e:
            logger.error(f"最佳化資料庫時發生錯誤: {str(e)}")
            return False

# 測試程式碼
if __name__ == "__main__":
    cache = CacheManager()
    context = ["前一句", "當前句", "後一句"]
    
    # 測試儲存與檢索
    cache.store_translation("こんにちは", "你好", context, "test_model")
    result = cache.get_cached_translation("こんにちは", context, "test_model")
    print(f"快取結果: {result}")  # 應輸出 "你好"
    
    # 測試統計功能
    stats = cache.get_cache_stats()
    print(f"快取統計: {json.dumps(stats, indent=2)}")
    
    # 測試備份功能
    cache._create_backup()
    
    # 測試匯出功能
    cache.export_cache("cache_export.json")