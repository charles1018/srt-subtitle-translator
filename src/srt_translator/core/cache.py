import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

# 從配置管理器導入
from srt_translator.core.config import ConfigManager

# 設定日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs("logs", exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = logging.handlers.TimedRotatingFileHandler(
        filename="logs/cache.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# 快取版本，用於不同版本間的快取相容性
CACHE_VERSION = "1.1"


class CacheManager:
    """快取管理器，處理翻譯結果的本地儲存和檢索"""

    # 類變數，用於實現單例模式
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: str = None) -> "CacheManager":
        """獲取快取管理器的單例實例

        參數:
            db_path: 快取資料庫路徑，若為None則使用配置中的路徑

        回傳:
            快取管理器實例
        """
        with cls._lock:
            if cls._instance is None:
                # 如果沒有指定db_path，從配置獲取
                if db_path is None:
                    config = ConfigManager.get_instance("cache")
                    db_path = config.get_value("db_path", "data/translation_cache.db")

                cls._instance = CacheManager(db_path)
            return cls._instance

    def __init__(self, db_path: str = "data/translation_cache.db"):
        """初始化快取管理器

        參數:
            db_path: 快取資料庫路徑
        """
        # 如果 db_path 為 None 或空字串，則使用預設值
        if not db_path:
            db_path = "data/translation_cache.db"
        # 確保目錄存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.db_path = db_path
        self.memory_cache = {}  # 記憶體快取層
        self.stats = {"total_queries": 0, "cache_hits": 0, "db_errors": 0, "last_cleanup": None}

        # 讀取配置
        cache_config = ConfigManager.get_instance("cache")
        self.max_memory_cache = cache_config.get_value("max_memory_cache", 1000)
        self.auto_cleanup_days = cache_config.get_value("auto_cleanup_days", 30)

        # 初始化資料庫
        self._init_db()

        # 創建用於保護記憶體快取的鎖
        self._cache_lock = threading.RLock()

        logger.info(
            f"快取管理器初始化完成: {db_path}, "
            f"max_memory_cache={self.max_memory_cache}, "
            f"auto_cleanup_days={self.auto_cleanup_days}"
        )

    def _init_db(self):
        """初始化快取資料庫並添加效能優化"""

        def adapt_datetime(dt):
            return dt.isoformat()

        def convert_datetime(s):
            try:
                return datetime.fromisoformat(s.decode())
            except (ValueError, AttributeError, UnicodeDecodeError):
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
            logger.error(f"初始化資料庫時發生錯誤: {e!s}")
            # 如果資料庫損壞，嘗試復原
            self._recover_db_if_needed()

    def _check_cache_version(self, conn):
        """檢查快取版本，確保相容性"""
        try:
            cursor = conn.execute("SELECT value FROM cache_metadata WHERE key = 'version'")
            result = cursor.fetchone()

            if not result:
                # 新建快取，設定版本
                conn.execute("INSERT INTO cache_metadata (key, value) VALUES (?, ?)", ("version", CACHE_VERSION))
                conn.execute(
                    "INSERT INTO cache_metadata (key, value) VALUES (?, ?)", ("created_at", datetime.now().isoformat())
                )
            elif result[0] != CACHE_VERSION:
                # 快取版本不匹配，清理舊數據
                logger.warning(f"快取版本不匹配: 目前={result[0]}, 需要={CACHE_VERSION}")
                conn.execute("DELETE FROM translations")
                conn.execute("UPDATE cache_metadata SET value = ? WHERE key = 'version'", (CACHE_VERSION,))
        except sqlite3.Error as e:
            logger.error(f"檢查快取版本時發生錯誤: {e!s}")

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
            logger.error(f"復原資料庫時發生錯誤: {e!s}")

    def _create_backup(self):
        """建立資料庫備份"""
        try:
            backup_path = f"{self.db_path}.bak"
            shutil.copy(self.db_path, backup_path)
            logger.info(f"已建立資料庫備份: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"建立資料庫備份時發生錯誤: {e!s}")
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
        """獲取快取的翻譯結果，先檢查記憶體，再檢查資料庫

        參數:
            source_text: 原始文字
            context_texts: 上下文文本列表
            model_name: 模型名稱

        回傳:
            翻譯結果，如果快取中不存在則返回None
        """
        self.stats["total_queries"] += 1

        # 空文本直接返回空字串
        if not source_text.strip():
            return ""

        # 計算上下文雜湊
        context_hash = self._compute_context_hash(tuple(context_texts))

        # 檢查記憶體快取
        with self._cache_lock:
            cache_key = self._generate_cache_key(source_text, context_hash, model_name)
            if cache_key in self.memory_cache:
                self.stats["cache_hits"] += 1
                self.memory_cache[cache_key]["last_accessed"] = time.time()
                return self.memory_cache[cache_key]["target_text"]

        # 檢查資料庫快取
        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.execute(
                    """
                    SELECT target_text, usage_count 
                    FROM translations 
                    WHERE source_text = ? AND context_hash = ? AND model_name = ?
                """,
                    (source_text, context_hash, model_name),
                )

                result = cursor.fetchone()
                if result:
                    target_text, usage_count = result
                    # 更新使用統計
                    conn.execute(
                        """
                        UPDATE translations 
                        SET usage_count = ?, last_used = ?
                        WHERE source_text = ? AND context_hash = ? AND model_name = ?
                    """,
                        (usage_count + 1, datetime.now(), source_text, context_hash, model_name),
                    )

                    # 添加到記憶體快取
                    with self._cache_lock:
                        self.memory_cache[cache_key] = {"target_text": target_text, "last_accessed": time.time()}

                        # 快取過大時清理 (超過 120% 才觸發)
                        if len(self.memory_cache) > self.max_memory_cache * 1.2:
                            self._clean_memory_cache()

                    self.stats["cache_hits"] += 1
                    return target_text
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"資料庫查詢錯誤: {e!s}")

        return None

    def store_translation(self, source_text: str, target_text: str, context_texts: List[str], model_name: str) -> bool:
        """儲存翻譯結果到快取

        參數:
            source_text: 原始文字
            target_text: 翻譯結果
            context_texts: 上下文文本列表
            model_name: 模型名稱

        回傳:
            是否成功儲存
        """
        # 空文本不儲存
        if not source_text.strip() or not target_text.strip():
            return False

        # 計算上下文雜湊
        context_hash = self._compute_context_hash(tuple(context_texts))

        # 添加到記憶體快取
        cache_key = self._generate_cache_key(source_text, context_hash, model_name)
        with self._cache_lock:
            self.memory_cache[cache_key] = {"target_text": target_text, "last_accessed": time.time()}

            # 快取過大時清理 (超過 120% 才觸發)
            if len(self.memory_cache) > self.max_memory_cache * 1.2:
                self._clean_memory_cache()

        # 儲存到資料庫
        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO translations 
                    (source_text, target_text, context_hash, model_name, created_at, usage_count, last_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (source_text, target_text, context_hash, model_name, datetime.now(), 1, datetime.now()),
                )
            return True
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"資料庫儲存錯誤: {e!s}")
            return False

    def _clean_memory_cache(self):
        """清理記憶體快取，移除最久未使用的項目"""
        # 已有鎖保護，不需要再加鎖
        current_size = len(self.memory_cache)
        threshold = int(self.max_memory_cache * 0.7)

        # 詳細日誌
        logger.debug(f"快取清理檢查: 當前大小={current_size}, 限制={self.max_memory_cache}, 閾值={threshold}")

        if current_size <= threshold:
            logger.debug("快取大小未超過閾值，跳過清理")
            return

        # 按最後存取時間排序
        sorted_items = sorted(self.memory_cache.items(), key=lambda x: x[1]["last_accessed"])

        # 保留 70% 最近使用的項目
        keep_count = int(self.max_memory_cache * 0.7)
        removed_count = 0

        for key, _ in sorted_items[:-keep_count]:
            del self.memory_cache[key]
            removed_count += 1

        # 更詳細的日誌
        logger.info(
            f"已清理記憶體快取: 移除 {removed_count} 項, "
            f"保留 {len(self.memory_cache)} 項 "
            f"(限制: {self.max_memory_cache})"
        )

    def _auto_cleanup(self, conn, days_threshold: int = None):
        """自動清理過期快取

        參數:
            conn: 資料庫連接
            days_threshold: 天數閾值，超過此天數的紀錄將被刪除
        """
        # 如果未指定天數閾值，從配置獲取
        if days_threshold is None:
            days_threshold = self.auto_cleanup_days

        try:
            # 檢查上次清理時間
            cursor = conn.execute("SELECT value FROM cache_metadata WHERE key = 'last_cleanup'")
            result = cursor.fetchone()

            current_time = datetime.now()
            if result:
                try:
                    last_cleanup = datetime.fromisoformat(result[0])
                    # 如果距離上次清理不到1天，則跳過
                    if current_time - last_cleanup < timedelta(days=1):
                        return
                except (ValueError, TypeError):
                    pass  # 日期格式錯誤，繼續執行清理

            # 執行清理
            threshold_date = current_time - timedelta(days=days_threshold)
            conn.execute("DELETE FROM translations WHERE last_used < ?", (threshold_date,))

            # 更新上次清理時間
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                ("last_cleanup", current_time.isoformat()),
            )

            self.stats["last_cleanup"] = current_time.isoformat()
            logger.info(f"自動清理已完成，刪除了 {conn.total_changes} 條過期快取")
        except sqlite3.Error as e:
            logger.error(f"自動清理時發生錯誤: {e!s}")

    def clear_old_cache(self, days_threshold: int = None) -> int:
        """手動清理過期快取 (超過一定天數的舊資料)

        參數:
            days_threshold: 天數閾值，超過此天數的紀錄將被刪除

        回傳:
            刪除的記錄數量
        """
        # 如果未指定天數閾值，從配置獲取
        if days_threshold is None:
            days_threshold = self.auto_cleanup_days

        threshold_date = datetime.now() - timedelta(days=days_threshold)
        deleted_count = 0

        try:
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                cursor = conn.execute("DELETE FROM translations WHERE last_used < ?", (threshold_date,))
                deleted_count = cursor.rowcount

                # 更新上次清理時間
                conn.execute(
                    "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                    ("last_cleanup", datetime.now().isoformat()),
                )

                self.stats["last_cleanup"] = datetime.now().isoformat()

            # 建立備份
            self._create_backup()

            # 優化資料庫
            self.optimize_database()

            logger.info(f"已清理 {deleted_count} 條過期快取")
            return deleted_count
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"清理快取時發生錯誤: {e!s}")
            return 0

    def clear_cache_by_model(self, model_name: str) -> int:
        """按模型清理快取

        參數:
            model_name: 模型名稱

        回傳:
            刪除的記錄數量
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM translations WHERE model_name = ?", (model_name,))
                deleted_count = cursor.rowcount

            # 清理記憶體快取中相關條目
            with self._cache_lock:
                keys_to_remove = [key for key in self.memory_cache if key.split("|")[2] == model_name]
                for key in keys_to_remove:
                    del self.memory_cache[key]

            logger.info(f"已清理模型 {model_name} 的 {deleted_count} 條快取")
            return deleted_count
        except sqlite3.Error as e:
            self.stats["db_errors"] += 1
            logger.error(f"按模型清理快取時發生錯誤: {e!s}")
            return 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """獲取快取統計資訊

        回傳:
            包含統計資訊的字典
        """
        stats = self.stats.copy()

        try:
            with sqlite3.connect(self.db_path) as conn:
                # 獲取總記錄數
                cursor = conn.execute("SELECT COUNT(*) FROM translations")
                stats["total_records"] = cursor.fetchone()[0]

                # 獲取資料庫大小
                stats["db_size_mb"] = os.path.getsize(self.db_path) / (1024 * 1024)

                # 獲取按模型分類的快取統計
                cursor = conn.execute("SELECT model_name, COUNT(*) FROM translations GROUP BY model_name")
                stats["models"] = {row[0]: row[1] for row in cursor.fetchall()}

                # 獲取使用率最高的10個快取
                cursor = conn.execute(
                    "SELECT source_text, target_text, usage_count, model_name "
                    "FROM translations ORDER BY usage_count DESC LIMIT 10"
                )
                stats["top_used"] = [
                    {"source": row[0], "target": row[1], "count": row[2], "model": row[3]} for row in cursor.fetchall()
                ]

                # 計算命中率
                if stats["total_queries"] > 0:
                    stats["hit_rate"] = (stats["cache_hits"] / stats["total_queries"]) * 100
                else:
                    stats["hit_rate"] = 0

                # 添加記憶體快取統計
                with self._cache_lock:
                    stats["memory_cache_size"] = len(self.memory_cache)
                    stats["memory_cache_limit"] = self.max_memory_cache

            return stats
        except sqlite3.Error as e:
            logger.error(f"獲取快取統計時發生錯誤: {e!s}")
            return self.stats

    def export_cache(self, output_path: str) -> bool:
        """匯出快取資料到JSON檔案

        參數:
            output_path: 輸出檔案路徑

        回傳:
            是否成功匯出
        """
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
                    "entries": [dict(row) for row in cursor.fetchall()],
                }

                # 確保輸出目錄存在
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                logger.info(f"已匯出 {len(data['entries'])} 條快取記錄到 {output_path}")
                return True
        except Exception as e:
            logger.error(f"匯出快取時發生錯誤: {e!s}")
            return False

    def import_cache(self, input_path: str) -> Tuple[bool, int]:
        """從JSON檔案匯入快取資料

        參數:
            input_path: 輸入檔案路徑

        回傳:
            (是否成功匯入, 匯入的記錄數量)
        """
        try:
            if not os.path.exists(input_path):
                logger.error(f"匯入檔案不存在: {input_path}")
                return False, 0

            with open(input_path, encoding="utf-8") as f:
                data = json.load(f)

            # 檢查版本相容性
            if "version" not in data or not (data["version"] == CACHE_VERSION or data["version"] == "1.0"):
                logger.warning(f"快取版本不匹配: {data.get('version', '未知')} != {CACHE_VERSION}")
                return False, 0

            imported_count = 0
            with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                # 先建立備份
                self._create_backup()

                for entry in data["entries"]:
                    try:
                        # 確保記錄有必要的欄位
                        if not all(k in entry for k in ["source_text", "target_text", "context_hash", "model_name"]):
                            continue

                        # 設置默認值
                        created_at = entry.get("created_at", datetime.now().isoformat())
                        usage_count = entry.get("usage_count", 1)

                        conn.execute(
                            """
                            INSERT OR IGNORE INTO translations 
                            (source_text, target_text, context_hash, model_name, created_at, usage_count, last_used)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                entry["source_text"],
                                entry["target_text"],
                                entry["context_hash"],
                                entry["model_name"],
                                created_at,
                                usage_count,
                                datetime.now(),
                            ),
                        )
                        if conn.total_changes > 0:
                            imported_count += 1
                    except (KeyError, sqlite3.Error) as e:
                        logger.warning(f"匯入條目時發生錯誤: {e!s}")
                        continue

            # 清理記憶體快取，強制從資料庫重新載入
            with self._cache_lock:
                self.memory_cache.clear()

            logger.info(f"已匯入 {imported_count} 條快取記錄從 {input_path}")
            return True, imported_count
        except Exception as e:
            logger.error(f"匯入快取時發生錯誤: {e!s}")
            return False, 0

    def optimize_database(self) -> bool:
        """最佳化資料庫以提高效能

        回傳:
            是否成功最佳化
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")
                conn.execute("ANALYZE")
            logger.info("資料庫最佳化完成")
            return True
        except sqlite3.Error as e:
            logger.error(f"最佳化資料庫時發生錯誤: {e!s}")
            return False

    def clear_all_cache(self) -> bool:
        """清空所有快取

        回傳:
            是否成功清空
        """
        try:
            # 建立備份
            self._create_backup()

            # 清空資料庫快取
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM translations")

            # 清空記憶體快取
            with self._cache_lock:
                self.memory_cache.clear()

            logger.info("已清空所有快取")
            return True
        except Exception as e:
            logger.error(f"清空快取時發生錯誤: {e!s}")
            return False

    def search_cache(self, keyword: str, model_name: str = None) -> List[Dict[str, Any]]:
        """搜尋快取

        參數:
            keyword: 搜尋關鍵字
            model_name: 限定模型名稱（可選）

        回傳:
            符合條件的快取記錄列表
        """
        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row

                # 構建查詢
                query = """
                    SELECT source_text, target_text, model_name, usage_count, last_used
                    FROM translations
                    WHERE (source_text LIKE ? OR target_text LIKE ?)
                """
                params = [f"%{keyword}%", f"%{keyword}%"]

                if model_name:
                    query += " AND model_name = ?"
                    params.append(model_name)

                query += " ORDER BY usage_count DESC LIMIT 100"

                cursor = conn.execute(query, params)
                results = [dict(row) for row in cursor.fetchall()]

            logger.debug(f"搜尋快取: 關鍵字='{keyword}', 找到 {len(results)} 項")
            return results
        except sqlite3.Error as e:
            logger.error(f"搜尋快取時發生錯誤: {e!s}")
            return []

    def update_config(self) -> None:
        """從配置管理器更新快取設定"""
        cache_config = ConfigManager.get_instance("cache")
        self.max_memory_cache = cache_config.get_value("max_memory_cache", 1000)
        self.auto_cleanup_days = cache_config.get_value("auto_cleanup_days", 30)

        # 如果記憶體快取超過新的限制，立即清理
        with self._cache_lock:
            if len(self.memory_cache) > self.max_memory_cache:
                self._clean_memory_cache()

        logger.info(
            f"已更新快取設定: max_memory_cache={self.max_memory_cache}, auto_cleanup_days={self.auto_cleanup_days}"
        )


# 測試程式碼
if __name__ == "__main__":
    # 設定控制台日誌以便於測試
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter("%(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 初始化配置管理器
    config = ConfigManager.get_instance("cache")

    # 初始化快取管理器
    cache = CacheManager.get_instance()

    # 測試功能
    print("===== 快取管理器測試 =====")

    # 測試儲存與檢索
    print("\n1. 測試儲存與檢索")
    context = ["前一句", "當前句", "後一句"]

    # 儲存翻譯
    cache.store_translation("こんにちは", "你好", context, "test_model")

    # 檢索翻譯
    result = cache.get_cached_translation("こんにちは", context, "test_model")
    print(f"快取結果: {result}")  # 應輸出 "你好"

    # 測試不存在的翻譯
    result = cache.get_cached_translation("さようなら", context, "test_model")
    print(f"不存在的翻譯: {result}")  # 應輸出 None

    # 測試模型特定清理
    print("\n2. 測試模型特定清理")
    # 先儲存一些不同模型的翻譯
    cache.store_translation("テスト", "測試", context, "model_a")
    cache.store_translation("テスト", "試驗", context, "model_b")

    # 清理特定模型的快取
    deleted = cache.clear_cache_by_model("model_a")
    print(f"已刪除 {deleted} 條 model_a 的快取")

    # 測試搜尋功能
    print("\n3. 測試搜尋功能")
    cache.store_translation("特別なテスト", "特殊測試", context, "test_model")

    results = cache.search_cache("特殊")
    print(f"搜尋結果數量: {len(results)}")
    for item in results:
        print(f"  源文本: {item['source_text']}")
        print(f"  譯文: {item['target_text']}")
        print(f"  模型: {item['model_name']}")

    # 測試統計功能
    print("\n4. 測試統計功能")
    stats = cache.get_cache_stats()
    print(f"記錄總數: {stats.get('total_records', 0)}")
    print(f"資料庫大小: {stats.get('db_size_mb', 0):.2f} MB")
    print(f"快取命中率: {stats.get('hit_rate', 0):.2f}%")
    print(f"記憶體快取大小: {stats.get('memory_cache_size', 0)}/{stats.get('memory_cache_limit', 0)}")

    # 測試最佳化功能
    print("\n5. 測試最佳化功能")
    success = cache.optimize_database()
    print(f"資料庫最佳化: {'成功' if success else '失敗'}")

    # 測試匯出功能
    print("\n6. 測試匯出功能")
    export_path = "temp_cache_export.json"
    success = cache.export_cache(export_path)
    print(f"匯出快取: {'成功' if success else '失敗'}")

    # 測試清理功能
    print("\n7. 測試清理功能")
    deleted = cache.clear_old_cache(days_threshold=1)  # 使用1天閾值讓測試可以看到效果
    print(f"清理舊快取: 已刪除 {deleted} 條記錄")

    print("\n===== 測試完成 =====")

    # 清理測試檔案
    try:
        if os.path.exists(export_path):
            os.remove(export_path)
    except OSError:
        pass
