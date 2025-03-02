# cache.py
import sqlite3
from datetime import datetime
from typing import Optional, List
import hashlib

class CacheManager:
    def __init__(self, db_path: str = "translation_cache.db", max_entries: int = 10000, default_expiry_days: int = 30):
        """
        初始化緩存管理器

        :param db_path: SQLite 數據庫路徑
        :param max_entries: 最大緩存條目數，超過時觸發 LRU 清理
        :param default_expiry_days: 默認過期天數
        """
        self.db_path = db_path
        self.max_entries = max_entries
        self.default_expiry_days = default_expiry_days
        self._init_db()

    def _init_db(self):
        """初始化緩存數據庫，添加 last_used_at 欄位並優化效能"""
        def adapt_datetime(dt):
            return dt.isoformat()

        def convert_datetime(s):
            try:
                return datetime.fromisoformat(s.decode())
            except:
                return datetime.now()

        sqlite3.register_adapter(datetime, adapt_datetime)
        sqlite3.register_converter("timestamp", convert_datetime)

        with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            # 啟用 WAL 模式提高寫入效能
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            
            # 更新表結構，新增 last_used_at 欄位
            conn.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    source_text TEXT,
                    target_text TEXT,
                    context_hash TEXT,
                    model_name TEXT,
                    created_at timestamp,
                    last_used_at timestamp,
                    usage_count INTEGER,
                    PRIMARY KEY (source_text, context_hash, model_name)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context ON translations(context_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model ON translations(model_name)")
            # 新增 last_used_at 索引以加速 LRU 查詢
            conn.execute("CREATE INDEX IF NOT EXISTS idx_last_used ON translations(last_used_at)")

    def _compute_context_hash(self, context_texts: List[str]) -> str:
        """計算上下文的哈希值"""
        context_str = "".join([text.strip() for text in context_texts if text.strip()])
        return hashlib.md5(context_str.encode()).hexdigest()

    def get_cached_translation(self, source_text: str, context_texts: List[str], model_name: str) -> Optional[str]:
        """
        獲取緩存的翻譯結果，並更新使用次數和最後使用時間

        :param source_text: 原始文本
        :param context_texts: 上下文列表
        :param model_name: 使用的模型名稱
        :return: 翻譯結果或 None
        """
        context_hash = self._compute_context_hash(context_texts)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT target_text, usage_count 
                    FROM translations 
                    WHERE source_text = ? AND context_hash = ? AND model_name = ?
                """, (source_text, context_hash, model_name))
                
                result = cursor.fetchone()
                if result:
                    target_text, usage_count = result
                    # 更新使用次數和最後使用時間
                    conn.execute("""
                        UPDATE translations 
                        SET usage_count = ?, last_used_at = ? 
                        WHERE source_text = ? AND context_hash = ? AND model_name = ?
                    """, (usage_count + 1, datetime.now(), source_text, context_hash, model_name))
                    # 檢查並清理 LRU
                    self._check_and_clear_lru(conn)
                    return target_text
        except sqlite3.Error as e:
            print(f"數據庫查詢錯誤: {str(e)}")
        return None

    def store_translation(self, source_text: str, target_text: str, context_texts: List[str], model_name: str):
        """
        存儲翻譯結果到緩存，並檢查 LRU 清理

        :param source_text: 原始文本
        :param target_text: 翻譯後文本
        :param context_texts: 上下文列表
        :param model_name: 使用的模型名稱
        """
        context_hash = self._compute_context_hash(context_texts)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO translations 
                    (source_text, target_text, context_hash, model_name, created_at, last_used_at, usage_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (source_text, target_text, context_hash, model_name, datetime.now(), datetime.now(), 1))
                # 檢查並清理 LRU
                self._check_and_clear_lru(conn)
        except sqlite3.Error as e:
            print(f"數據庫存儲錯誤: {str(e)}")

    def _check_and_clear_lru(self, conn):
        """
        檢查緩存條目數量並執行 LRU 清理

        :param conn: SQLite 連接對象
        """
        cursor = conn.execute("SELECT COUNT(*) FROM translations")
        total_entries = cursor.fetchone()[0]
        
        if total_entries > self.max_entries:
            # 計算加權分數：usage_count * 0.3 + 距離現在的天數 * 0.7
            # 分數越高表示越不重要（使用少且久未使用）
            conn.execute("""
                DELETE FROM translations 
                WHERE rowid IN (
                    SELECT rowid FROM translations 
                    ORDER BY (usage_count * 0.3 + (julianday('now') - julianday(last_used_at)) * 0.7) DESC
                    LIMIT ?
                )
            """, (total_entries - self.max_entries + self.max_entries // 10,))  # 移除超出部分加10%緩衝

    def clear_old_cache(self, days_threshold: int = None):
        """
        清理過期緩存（超過指定天數的舊資料）

        :param days_threshold: 過期天數，若未提供則使用默認值
        """
        days = days_threshold if days_threshold is not None else self.default_expiry_days
        threshold_date = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=days)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM translations WHERE created_at < ?", 
                    (threshold_date,)
                )
                print(f"已清理 {conn.total_changes} 條過期緩存")
        except sqlite3.Error as e:
            print(f"清理緩存時發生錯誤: {str(e)}")

    def set_expiry_by_model(self, model_name: str, expiry_days: int):
        """
        為特定模型設置動態過期時間（未直接應用於數據庫，但可作為參考）

        :param model_name: 模型名稱
        :param expiry_days: 過期天數
        """
        # 此處僅記錄邏輯，實際應用需在清理時根據 model_name 動態調整
        print(f"為模型 {model_name} 設置過期時間為 {expiry_days} 天")
        # 可選：在數據庫中添加一個 expiry_days 欄位並在 store_translation 時記錄

# 測試代碼
if __name__ == "__main__":
    cache = CacheManager(max_entries=5)  # 設置最大條目為5以便測試 LRU
    context = ["前一句", "當前句", "後一句"]
    
    # 存儲多個翻譯，觸發 LRU 清理
    for i in range(7):
        cache.store_translation(f"こんにちは{i}", f"你好{i}", context, "test_model")
    
    # 查詢並更新使用次數
    result = cache.get_cached_translation("こんにちは0", context, "test_model")
    print(f"緩存結果: {result}")  # 應輸出 "你好0" 或 None（若被 LRU 清理）
    
    # 清理過期緩存
    cache.clear_old_cache(days_threshold=1)