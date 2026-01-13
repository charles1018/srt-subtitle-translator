"""術語表管理模組 - 維護專有名詞對照表以確保翻譯一致性"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, cast

from srt_translator.core.singleton import SingletonMixin

logger = logging.getLogger(__name__)


@dataclass
class GlossaryEntry:
    """術語表條目"""

    source: str  # 來源語言術語
    target: str  # 目標語言翻譯
    category: str = ""  # 分類（如：人名、地名、技術術語）
    notes: str = ""  # 備註說明
    case_sensitive: bool = False  # 是否區分大小寫


@dataclass
class Glossary:
    """術語表"""

    name: str  # 術語表名稱
    source_lang: str  # 來源語言
    target_lang: str  # 目標語言
    entries: Dict[str, GlossaryEntry] = field(default_factory=dict)
    description: str = ""

    def add_entry(
        self,
        source: str,
        target: str,
        category: str = "",
        notes: str = "",
        case_sensitive: bool = False,
    ) -> None:
        """新增術語條目"""
        key = source if case_sensitive else source.lower()
        self.entries[key] = GlossaryEntry(
            source=source,
            target=target,
            category=category,
            notes=notes,
            case_sensitive=case_sensitive,
        )

    def remove_entry(self, source: str) -> bool:
        """移除術語條目"""
        key = source.lower()
        if key in self.entries:
            del self.entries[key]
            return True
        # 嘗試精確匹配
        if source in self.entries:
            del self.entries[source]
            return True
        return False

    def get_entry(self, source: str) -> Optional[GlossaryEntry]:
        """取得術語條目"""
        # 先嘗試不區分大小寫
        key = source.lower()
        if key in self.entries:
            return self.entries[key]
        # 再嘗試精確匹配
        return self.entries.get(source)

    def apply_to_text(self, text: str) -> str:
        """將術語表應用到文字上"""
        result = text
        # 按來源術語長度降序排列，避免短詞誤替換長詞
        sorted_entries = sorted(self.entries.values(), key=lambda e: len(e.source), reverse=True)

        for entry in sorted_entries:
            if entry.case_sensitive:
                result = result.replace(entry.source, entry.target)
            else:
                # 不區分大小寫的替換
                pattern = re.compile(re.escape(entry.source), re.IGNORECASE)
                result = pattern.sub(entry.target, result)

        return result

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "name": self.name,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "description": self.description,
            "entries": [
                {
                    "source": e.source,
                    "target": e.target,
                    "category": e.category,
                    "notes": e.notes,
                    "case_sensitive": e.case_sensitive,
                }
                for e in self.entries.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Glossary":
        """從字典格式建立術語表"""
        glossary = cls(
            name=data.get("name", ""),
            source_lang=data.get("source_lang", ""),
            target_lang=data.get("target_lang", ""),
            description=data.get("description", ""),
        )

        for entry_data in data.get("entries", []):
            glossary.add_entry(
                source=entry_data.get("source", ""),
                target=entry_data.get("target", ""),
                category=entry_data.get("category", ""),
                notes=entry_data.get("notes", ""),
                case_sensitive=entry_data.get("case_sensitive", False),
            )

        return glossary


class GlossaryManager(SingletonMixin):
    """術語表管理器 - 單例模式"""

    def __init__(self) -> None:
        """初始化術語表管理器"""
        self._glossaries: Dict[str, Glossary] = {}
        self._active_glossaries: Set[str] = set()
        self._glossary_dir = os.path.join("data", "glossaries")

        # 確保目錄存在
        os.makedirs(self._glossary_dir, exist_ok=True)

        # 載入現有術語表
        self._load_all_glossaries()

        logger.info(f"術語表管理器初始化完成，已載入 {len(self._glossaries)} 個術語表")

    @classmethod
    def get_instance(cls) -> "GlossaryManager":
        """取得術語表管理器單例"""
        return cast("GlossaryManager", cls._get_instance())

    def _load_all_glossaries(self) -> None:
        """載入所有術語表檔案"""
        if not os.path.exists(self._glossary_dir):
            return

        for filename in os.listdir(self._glossary_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(self._glossary_dir, filename)
                try:
                    self._load_glossary_file(file_path)
                except Exception as e:
                    logger.error(f"載入術語表失敗 {filename}: {e}")

    def _load_glossary_file(self, file_path: str) -> Optional[Glossary]:
        """載入單一術語表檔案"""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                glossary = Glossary.from_dict(data)
                self._glossaries[glossary.name] = glossary
                logger.debug(f"已載入術語表: {glossary.name} ({len(glossary.entries)} 條目)")
                return glossary
        except Exception as e:
            logger.error(f"載入術語表檔案失敗 {file_path}: {e}")
            return None

    def _save_glossary(self, glossary: Glossary) -> bool:
        """儲存術語表到檔案"""
        try:
            # 產生安全的檔案名稱
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", glossary.name)
            file_path = os.path.join(self._glossary_dir, f"{safe_name}.json")

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(glossary.to_dict(), f, ensure_ascii=False, indent=2)

            logger.info(f"已儲存術語表: {glossary.name}")
            return True
        except Exception as e:
            logger.error(f"儲存術語表失敗 {glossary.name}: {e}")
            return False

    def create_glossary(
        self,
        name: str,
        source_lang: str,
        target_lang: str,
        description: str = "",
    ) -> Glossary:
        """建立新的術語表"""
        if name in self._glossaries:
            raise ValueError(f"術語表 '{name}' 已存在")

        glossary = Glossary(
            name=name,
            source_lang=source_lang,
            target_lang=target_lang,
            description=description,
        )
        self._glossaries[name] = glossary
        self._save_glossary(glossary)
        return glossary

    def get_glossary(self, name: str) -> Optional[Glossary]:
        """取得指定術語表"""
        return self._glossaries.get(name)

    def list_glossaries(self) -> List[str]:
        """列出所有術語表名稱"""
        return list(self._glossaries.keys())

    def get_all_glossaries(self) -> Dict[str, Glossary]:
        """取得所有術語表"""
        return self._glossaries.copy()

    def delete_glossary(self, name: str) -> bool:
        """刪除術語表"""
        if name not in self._glossaries:
            return False

        # 從記憶體移除
        del self._glossaries[name]
        self._active_glossaries.discard(name)

        # 刪除檔案
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)
        file_path = os.path.join(self._glossary_dir, f"{safe_name}.json")
        if os.path.exists(file_path):
            os.remove(file_path)

        logger.info(f"已刪除術語表: {name}")
        return True

    def add_entry_to_glossary(
        self,
        glossary_name: str,
        source: str,
        target: str,
        category: str = "",
        notes: str = "",
        case_sensitive: bool = False,
    ) -> bool:
        """新增條目到指定術語表"""
        glossary = self._glossaries.get(glossary_name)
        if not glossary:
            return False

        glossary.add_entry(source, target, category, notes, case_sensitive)
        self._save_glossary(glossary)
        return True

    def remove_entry_from_glossary(self, glossary_name: str, source: str) -> bool:
        """從指定術語表移除條目"""
        glossary = self._glossaries.get(glossary_name)
        if not glossary:
            return False

        if glossary.remove_entry(source):
            self._save_glossary(glossary)
            return True
        return False

    def activate_glossary(self, name: str) -> bool:
        """啟用術語表（用於翻譯）"""
        if name in self._glossaries:
            self._active_glossaries.add(name)
            logger.info(f"已啟用術語表: {name}")
            return True
        return False

    def deactivate_glossary(self, name: str) -> bool:
        """停用術語表"""
        if name in self._active_glossaries:
            self._active_glossaries.remove(name)
            logger.info(f"已停用術語表: {name}")
            return True
        return False

    def get_active_glossaries(self) -> List[str]:
        """取得已啟用的術語表名稱"""
        return list(self._active_glossaries)

    def apply_glossaries(self, text: str, source_lang: str = "", target_lang: str = "") -> str:
        """將啟用的術語表應用到文字上

        參數:
            text: 要處理的文字
            source_lang: 來源語言（用於篩選適用的術語表）
            target_lang: 目標語言（用於篩選適用的術語表）

        回傳:
            處理後的文字
        """
        result = text

        for name in self._active_glossaries:
            glossary = self._glossaries.get(name)
            if not glossary:
                continue

            # 如果指定了語言，檢查術語表是否適用
            if source_lang and glossary.source_lang and glossary.source_lang != source_lang:
                continue
            if target_lang and glossary.target_lang and glossary.target_lang != target_lang:
                continue

            result = glossary.apply_to_text(result)

        return result

    def export_glossary(self, name: str, file_path: str, format: str = "json") -> bool:
        """匯出術語表到檔案

        參數:
            name: 術語表名稱
            file_path: 輸出檔案路徑
            format: 輸出格式 (json, csv, txt)
        """
        glossary = self._glossaries.get(name)
        if not glossary:
            return False

        try:
            if format == "json":
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(glossary.to_dict(), f, ensure_ascii=False, indent=2)

            elif format == "csv":
                import csv

                with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["source", "target", "category", "notes", "case_sensitive"])
                    for entry in glossary.entries.values():
                        writer.writerow(
                            [entry.source, entry.target, entry.category, entry.notes, entry.case_sensitive]
                        )

            elif format == "txt":
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"# 術語表: {glossary.name}\n")
                    f.write(f"# 來源語言: {glossary.source_lang}\n")
                    f.write(f"# 目標語言: {glossary.target_lang}\n\n")
                    for entry in glossary.entries.values():
                        f.write(f"{entry.source}\t{entry.target}\n")

            else:
                logger.error(f"不支援的匯出格式: {format}")
                return False

            logger.info(f"已匯出術語表 {name} 到 {file_path}")
            return True

        except Exception as e:
            logger.error(f"匯出術語表失敗: {e}")
            return False

    def import_glossary(
        self,
        file_path: str,
        name: Optional[str] = None,
        source_lang: str = "",
        target_lang: str = "",
    ) -> Optional[Glossary]:
        """從檔案匯入術語表

        參數:
            file_path: 輸入檔案路徑
            name: 術語表名稱（如果不指定，嘗試從檔案讀取或使用檔案名稱）
            source_lang: 來源語言
            target_lang: 目標語言
        """
        try:
            ext = os.path.splitext(file_path)[1].lower()

            if ext == ".json":
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    glossary = Glossary.from_dict(data)
                    if name:
                        glossary.name = name

            elif ext == ".csv":
                import csv

                glossary_name = name or os.path.splitext(os.path.basename(file_path))[0]
                glossary = Glossary(
                    name=glossary_name,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )

                with open(file_path, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        glossary.add_entry(
                            source=row.get("source", ""),
                            target=row.get("target", ""),
                            category=row.get("category", ""),
                            notes=row.get("notes", ""),
                            case_sensitive=row.get("case_sensitive", "").lower() == "true",
                        )

            elif ext == ".txt":
                glossary_name = name or os.path.splitext(os.path.basename(file_path))[0]
                glossary = Glossary(
                    name=glossary_name,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )

                with open(file_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("\t")
                        if len(parts) >= 2:
                            glossary.add_entry(source=parts[0], target=parts[1])

            else:
                logger.error(f"不支援的匯入格式: {ext}")
                return None

            # 儲存到記憶體和檔案
            self._glossaries[glossary.name] = glossary
            self._save_glossary(glossary)

            logger.info(f"已匯入術語表 {glossary.name} ({len(glossary.entries)} 條目)")
            return glossary

        except Exception as e:
            logger.error(f"匯入術語表失敗: {e}")
            return None

    def find_glossaries_for_languages(self, source_lang: str, target_lang: str) -> List[Glossary]:
        """尋找適用於指定語言對的術語表"""
        result = []
        for glossary in self._glossaries.values():
            # 檢查語言是否匹配（空字串表示適用於所有語言）
            source_match = not glossary.source_lang or glossary.source_lang == source_lang
            target_match = not glossary.target_lang or glossary.target_lang == target_lang
            if source_match and target_match:
                result.append(glossary)
        return result


# 便捷函數
def get_glossary_manager() -> GlossaryManager:
    """取得術語表管理器單例"""
    return GlossaryManager.get_instance()
