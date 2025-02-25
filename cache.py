# cache.py
import sqlite3
from datetime import datetime
from typing import Optional, List
import hashlib

class CacheManager:
    def __init__(self, db_path: str = "translation_cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化緩存數據庫"""
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    source_text TEXT,
                    target_text TEXT,
                    context_hash TEXT,
                    model_name TEXT,
                    created_at timestamp,
                    usage_count INTEGER,
                    PRIMARY KEY (source_text, context_hash, model_name)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context ON translations(context_hash)")

    def _compute_context_hash(self, context_texts: List[str]) -> str:
        """計算上下文的哈希值"""
        context_str = "".join(context_texts)
        return hashlib.md5(context_str.encode()).hexdigest()

    def get_cached_translation(self, source_text: str, context_texts: List[str], model_name: str) -> Optional[str]:
        """獲取緩存的翻譯結果"""
        context_hash = self._compute_context_hash(context_texts)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT target_text, usage_count 
                FROM translations 
                WHERE source_text = ? AND context_hash = ? AND model_name = ?
            """, (source_text, context_hash, model_name))
            
            result = cursor.fetchone()
            if result:
                target_text, usage_count = result
                conn.execute("""
                    UPDATE translations 
                    SET usage_count = ? 
                    WHERE source_text = ? AND context_hash = ? AND model_name = ?
                """, (usage_count + 1, source_text, context_hash, model_name))
                return target_text
        return None

    def store_translation(self, source_text: str, target_text: str, context_texts: List[str], model_name: str):
        """存儲翻譯結果到緩存"""
        context_hash = self._compute_context_hash(context_texts)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO translations 
                (source_text, target_text, context_hash, model_name, created_at, usage_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_text, target_text, context_hash, model_name, datetime.now(), 1))

# 測試代碼
if __name__ == "__main__":
    cache = CacheManager()
    context = ["前一句", "當前句", "後一句"]
    cache.store_translation("こんにちは", "你好", context, "test_model")
    result = cache.get_cached_translation("こんにちは", context, "test_model")
    print(f"緩存結果: {result}")  # 應輸出 "你好"