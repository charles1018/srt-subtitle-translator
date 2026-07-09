"""測試 glossary 模組 - Glossary / GlossaryEntry 純邏輯與 GlossaryManager 生命週期

此檔補上 GlossaryManager 先前只有間接（透過 test_factory.py）覆蓋的缺口。
重點鎖定 apply_glossaries 的語言篩選行為：不帶語言參數時一律套用，
對應 `-g` 顯式啟用 + 輸出端字面替換的既有設計（見 SHARED_NOTES / factory.py 呼叫慣例）。
"""

import pytest

from srt_translator.core.glossary import Glossary, GlossaryManager


class TestGlossaryEntryAndGlossary:
    """Glossary / GlossaryEntry 純邏輯，不涉及檔案 IO。"""

    def test_add_entry_case_insensitive_lookup(self):
        g = Glossary(name="t", source_lang="英文", target_lang="繁體中文")
        g.add_entry("Battalion", "營長")
        # 預設不區分大小寫，key 以小寫儲存
        assert g.get_entry("battalion").target == "營長"
        assert g.get_entry("BATTALION").target == "營長"

    def test_add_entry_case_sensitive_keeps_exact_key(self):
        g = Glossary(name="t", source_lang="", target_lang="")
        g.add_entry("iOS", "iOS", case_sensitive=True)
        # 區分大小寫時以原字串為 key，小寫查不到
        assert g.get_entry("iOS").target == "iOS"
        assert g.get_entry("ios") is None

    def test_remove_entry_by_lower_and_exact(self):
        g = Glossary(name="t", source_lang="", target_lang="")
        g.add_entry("Apple", "蘋果")
        assert g.remove_entry("apple") is True
        assert g.get_entry("Apple") is None
        assert g.remove_entry("missing") is False

    def test_apply_to_text_basic_replacement(self):
        g = Glossary(name="t", source_lang="", target_lang="")
        g.add_entry("battalion chief", "營長")
        assert g.apply_to_text("the battalion chief arrived") == "the 營長 arrived"

    def test_apply_to_text_longest_source_first(self):
        """長來源優先替換，避免短詞先替換破壞長詞（apply_to_text 的排序保證）。"""
        g = Glossary(name="t", source_lang="", target_lang="")
        g.add_entry("chief", "主管")
        g.add_entry("battalion chief", "營長")
        # 若短詞先替換會得到「營長」被拆解；長詞優先確保整段命中
        assert g.apply_to_text("battalion chief") == "營長"

    def test_apply_to_text_case_insensitive_default(self):
        g = Glossary(name="t", source_lang="", target_lang="")
        g.add_entry("radio", "無線電")
        assert g.apply_to_text("Turn on the RADIO now") == "Turn on the 無線電 now"

    def test_apply_to_text_case_sensitive_entry(self):
        g = Glossary(name="t", source_lang="", target_lang="")
        g.add_entry("US", "美國", case_sensitive=True)
        # 區分大小寫只替換完全相同的片段
        assert g.apply_to_text("US and us") == "美國 and us"

    def test_to_dict_from_dict_round_trip(self):
        g = Glossary(name="t", source_lang="英文", target_lang="繁體中文", description="d")
        g.add_entry("cortisol", "皮質醇", category="醫療", notes="n")
        restored = Glossary.from_dict(g.to_dict())
        assert restored.name == "t"
        assert restored.source_lang == "英文"
        assert restored.target_lang == "繁體中文"
        assert restored.description == "d"
        entry = restored.get_entry("cortisol")
        assert entry.target == "皮質醇"
        assert entry.category == "醫療"


class TestGlossaryManager:
    """GlossaryManager 生命週期，於暫存 cwd 隔離，避免動到真實 data/glossaries。"""

    @pytest.fixture
    def manager(self, tmp_path, monkeypatch):
        # GlossaryManager.__init__ 以相對路徑 data/glossaries 操作，切到暫存目錄即完全隔離
        monkeypatch.chdir(tmp_path)
        GlossaryManager.reset_instance()
        mgr = GlossaryManager()
        yield mgr
        GlossaryManager.reset_instance()

    def test_create_and_get(self, manager):
        manager.create_glossary("g1", "英文", "繁體中文", description="d")
        g = manager.get_glossary("g1")
        assert g is not None
        assert g.source_lang == "英文"
        assert manager.list_glossaries() == ["g1"]

    def test_create_duplicate_raises(self, manager):
        manager.create_glossary("g1", "英文", "繁體中文")
        with pytest.raises(ValueError):
            manager.create_glossary("g1", "英文", "繁體中文")

    def test_delete_glossary(self, manager):
        manager.create_glossary("g1", "", "")
        assert manager.delete_glossary("g1") is True
        assert manager.get_glossary("g1") is None
        assert manager.delete_glossary("g1") is False

    def test_add_and_remove_entry(self, manager):
        manager.create_glossary("g1", "", "")
        assert manager.add_entry_to_glossary("g1", "radio", "無線電") is True
        assert manager.get_glossary("g1").get_entry("radio").target == "無線電"
        assert manager.remove_entry_from_glossary("g1", "radio") is True
        assert manager.get_glossary("g1").get_entry("radio") is None
        # 對不存在的術語表操作回傳 False
        assert manager.add_entry_to_glossary("missing", "a", "b") is False
        assert manager.remove_entry_from_glossary("missing", "a") is False

    def test_activate_deactivate(self, manager):
        manager.create_glossary("g1", "", "")
        assert manager.activate_glossary("g1") is True
        assert manager.get_active_glossaries() == ["g1"]
        assert manager.deactivate_glossary("g1") is True
        assert manager.get_active_glossaries() == []
        # 啟用不存在的術語表回傳 False
        assert manager.activate_glossary("missing") is False

    def test_apply_glossaries_only_active(self, manager):
        manager.create_glossary("g1", "", "")
        manager.add_entry_to_glossary("g1", "收音機", "無線電")
        # 未啟用時不套用
        assert manager.apply_glossaries("打開收音機") == "打開收音機"
        manager.activate_glossary("g1")
        assert manager.apply_glossaries("打開收音機") == "打開無線電"

    def test_apply_glossaries_without_lang_applies_regardless(self, manager):
        """不帶語言參數時略過語言篩選、一律套用 —— 對應 `-g` 顯式啟用的輸出端字面替換設計。"""
        manager.create_glossary("g1", "英文", "繁體中文")
        manager.add_entry_to_glossary("g1", "收音機", "無線電")
        manager.activate_glossary("g1")
        # 呼叫端不傳 source/target lang（factory.py 的實際慣例）→ 語言不參與篩選
        assert manager.apply_glossaries("打開收音機") == "打開無線電"

    def test_apply_glossaries_language_filter_skips_mismatch(self, manager):
        """有指定語言且術語表語言不同時跳過該表。"""
        manager.create_glossary("g1", "英文", "繁體中文")
        manager.add_entry_to_glossary("g1", "收音機", "無線電")
        manager.activate_glossary("g1")
        # 指定日文來源，與術語表英文不符 → 跳過
        assert manager.apply_glossaries("打開收音機", source_lang="日文", target_lang="繁體中文") == "打開收音機"
        # 語言相符 → 套用
        assert manager.apply_glossaries("打開收音機", source_lang="英文", target_lang="繁體中文") == "打開無線電"

    def test_find_glossaries_for_languages(self, manager):
        manager.create_glossary("en", "英文", "繁體中文")
        manager.create_glossary("ja", "日文", "繁體中文")
        manager.create_glossary("wild", "", "")  # 空語言 = 適用所有
        names = {g.name for g in manager.find_glossaries_for_languages("英文", "繁體中文")}
        assert names == {"en", "wild"}

    def test_persistence_across_instances(self, manager, tmp_path):
        """建立後由新實例從磁碟載回，驗證 _save_glossary / _load_all_glossaries。"""
        manager.create_glossary("g1", "英文", "繁體中文")
        manager.add_entry_to_glossary("g1", "cortisol", "皮質醇")
        # cwd 仍為 tmp_path（fixture 已 chdir），新實例會從同一 data/glossaries 載入
        reloaded = GlossaryManager()
        g = reloaded.get_glossary("g1")
        assert g is not None
        assert g.get_entry("cortisol").target == "皮質醇"

    def test_export_import_json_round_trip(self, manager, tmp_path):
        manager.create_glossary("g1", "英文", "繁體中文")
        manager.add_entry_to_glossary("g1", "cortisol", "皮質醇")
        out = tmp_path / "exported.json"
        assert manager.export_glossary("g1", str(out), format="json") is True
        imported = manager.import_glossary(str(out), name="g2")
        assert imported is not None
        assert imported.name == "g2"
        assert imported.get_entry("cortisol").target == "皮質醇"

    def test_export_missing_glossary_returns_false(self, manager, tmp_path):
        out = tmp_path / "x.json"
        assert manager.export_glossary("missing", str(out)) is False
