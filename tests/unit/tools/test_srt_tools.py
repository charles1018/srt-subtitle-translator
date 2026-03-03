"""tests/unit/tools/test_srt_tools.py — srt_tools 模組單元測試"""

import json
from pathlib import Path

import pysrt
import pytest

from srt_translator.tools.srt_tools import (
    CpsAuditReport,
    QAResult,
    assemble,
    batch_string_to_texts,
    cps_audit,
    extract,
    qa,
    texts_to_batch_string,
)
from srt_translator.utils.errors import FileError, ValidationError


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def multiline_srt_content() -> str:
    """包含多行字幕的 SRT 內容"""
    return """1
00:00:01,000 --> 00:00:03,000
Hello, world!

2
00:00:04,000 --> 00:00:06,000
This is line one.
This is line two.

3
00:00:07,000 --> 00:00:09,000
Single line subtitle.
"""


@pytest.fixture
def multiline_srt_file(temp_dir: Path, multiline_srt_content: str) -> Path:
    srt_file = temp_dir / "multiline.srt"
    srt_file.write_text(multiline_srt_content, encoding="utf-8")
    return srt_file


@pytest.fixture
def sample_structure(temp_dir: Path) -> Path:
    """建立範例 structure JSON"""
    structure = [
        {"index": 1, "start": "00:00:01,000", "end": "00:00:03,000", "line_count": 1},
        {"index": 2, "start": "00:00:04,000", "end": "00:00:06,000", "line_count": 1},
        {"index": 3, "start": "00:00:07,000", "end": "00:00:09,000", "line_count": 1},
    ]
    path = temp_dir / "test_structure.json"
    path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def sample_translated_text(temp_dir: Path) -> Path:
    """建立範例翻譯文本"""
    lines = ["你好，世界！", "這是一個測試字幕。", "測試 SRT 翻譯。"]
    path = temp_dir / "test_translated_text.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ─── TestExtract ─────────────────────────────────────────────


class TestExtract:
    """extract 函式測試"""

    def test_extract_basic(self, sample_srt_file: Path):
        """基本提取產生 structure JSON 和 text 檔案"""
        struct_path, text_path = extract(str(sample_srt_file))

        assert Path(struct_path).exists()
        assert Path(text_path).exists()

        structure = json.loads(Path(struct_path).read_text(encoding="utf-8"))
        assert len(structure) == 3
        assert structure[0]["index"] == 1
        assert structure[0]["start"] == "00:00:01,000"
        assert structure[0]["end"] == "00:00:03,000"

        text_lines = Path(text_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(text_lines) == 3
        assert text_lines[0] == "Hello, world!"

    def test_extract_multiline_subtitle(self, multiline_srt_file: Path):
        """多行字幕以 literal \\n 合併為單行"""
        struct_path, text_path = extract(str(multiline_srt_file))

        text_lines = Path(text_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(text_lines) == 3
        # 第二個字幕是多行的，應以 literal \n 合併
        assert text_lines[1] == "This is line one.\\nThis is line two."

        structure = json.loads(Path(struct_path).read_text(encoding="utf-8"))
        assert structure[1]["line_count"] == 2

    def test_extract_custom_prefix(self, sample_srt_file: Path, temp_dir: Path):
        """自訂輸出前綴"""
        prefix = str(temp_dir / "custom_output")
        struct_path, text_path = extract(str(sample_srt_file), output_prefix=prefix)

        assert "custom_output_structure.json" in struct_path
        assert "custom_output_text.txt" in text_path

    def test_extract_nonexistent_file(self):
        """不存在的檔案應拋出 FileError"""
        with pytest.raises(FileError):
            extract("/nonexistent/path.srt")

    def test_extract_preserves_timestamps(self, sample_srt_file: Path):
        """timestamp 完全保留"""
        struct_path, _ = extract(str(sample_srt_file))
        structure = json.loads(Path(struct_path).read_text(encoding="utf-8"))

        assert structure[0]["start"] == "00:00:01,000"
        assert structure[0]["end"] == "00:00:03,000"
        assert structure[1]["start"] == "00:00:04,000"
        assert structure[1]["end"] == "00:00:06,000"
        assert structure[2]["start"] == "00:00:07,000"
        assert structure[2]["end"] == "00:00:09,000"

    def test_extract_line_count_matches_text(self, sample_srt_file: Path):
        """structure 的字幕數量與 text 的行數一致"""
        struct_path, text_path = extract(str(sample_srt_file))
        structure = json.loads(Path(struct_path).read_text(encoding="utf-8"))
        text_lines = Path(text_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(structure) == len(text_lines)


# ─── TestAssemble ────────────────────────────────────────────


class TestAssemble:
    """assemble 函式測試"""

    def test_assemble_basic(self, temp_dir: Path, sample_structure: Path, sample_translated_text: Path):
        """基本組合產生 SRT 檔案"""
        prefix = str(temp_dir / "test")
        output = assemble(prefix)

        assert Path(output).exists()
        subs = pysrt.open(output, encoding="utf-8")
        assert len(subs) == 3
        assert subs[0].text == "你好，世界！"
        assert str(subs[0].start) == "00:00:01,000"

    def test_assemble_multiline_restoration(self, temp_dir: Path):
        """literal \\n 被還原為真實換行"""
        structure = [
            {"index": 1, "start": "00:00:01,000", "end": "00:00:03,000", "line_count": 2},
        ]
        struct_path = temp_dir / "multi_structure.json"
        struct_path.write_text(json.dumps(structure), encoding="utf-8")

        text_path = temp_dir / "multi_translated_text.txt"
        text_path.write_text("第一行\\n第二行\n", encoding="utf-8")

        output = assemble(str(temp_dir / "multi"))
        subs = pysrt.open(output, encoding="utf-8")
        assert subs[0].text == "第一行\n第二行"

    def test_assemble_line_count_mismatch(self, temp_dir: Path, sample_structure: Path):
        """行數不匹配應拋出 ValidationError"""
        text_path = temp_dir / "test_translated_text.txt"
        text_path.write_text("只有一行\n", encoding="utf-8")

        with pytest.raises(ValidationError, match="行數不匹配"):
            assemble(str(temp_dir / "test"))

    def test_assemble_missing_structure(self, temp_dir: Path):
        """缺少結構檔案應拋出 FileError"""
        text_path = temp_dir / "missing_translated_text.txt"
        text_path.write_text("test\n", encoding="utf-8")

        with pytest.raises(FileError, match="結構檔案不存在"):
            assemble(str(temp_dir / "missing"))

    def test_assemble_missing_text(self, temp_dir: Path, sample_structure: Path):
        """缺少文本檔案應拋出 FileError"""
        # 把 translated text 改名，讓它找不到
        with pytest.raises(FileError, match="文本檔案不存在"):
            assemble(str(temp_dir / "test"), text_suffix="_nonexistent.txt")

    def test_assemble_custom_output_path(self, temp_dir: Path, sample_structure: Path, sample_translated_text: Path):
        """自訂輸出路徑"""
        custom_path = str(temp_dir / "custom_output.srt")
        output = assemble(str(temp_dir / "test"), output_path=custom_path)
        assert output == custom_path
        assert Path(custom_path).exists()

    def test_roundtrip_extract_assemble(self, sample_srt_file: Path, temp_dir: Path):
        """extract → assemble roundtrip 產生等效 SRT"""
        prefix = str(sample_srt_file.with_suffix(""))
        struct_path, text_path = extract(str(sample_srt_file))

        # 用原始文本（非翻譯）做 assemble
        output = assemble(prefix, text_suffix="_text.txt")

        src_subs = pysrt.open(str(sample_srt_file), encoding="utf-8")
        out_subs = pysrt.open(output, encoding="utf-8")

        assert len(src_subs) == len(out_subs)
        for src, out in zip(src_subs, out_subs, strict=True):
            assert src.index == out.index
            assert str(src.start) == str(out.start)
            assert str(src.end) == str(out.end)
            assert src.text == out.text

    def test_roundtrip_multiline(self, multiline_srt_file: Path):
        """extract → assemble roundtrip 多行字幕也能保留"""
        prefix = str(multiline_srt_file.with_suffix(""))
        extract(str(multiline_srt_file))
        output = assemble(prefix, text_suffix="_text.txt")

        src_subs = pysrt.open(str(multiline_srt_file), encoding="utf-8")
        out_subs = pysrt.open(output, encoding="utf-8")

        assert len(src_subs) == len(out_subs)
        for src, out in zip(src_subs, out_subs, strict=True):
            assert src.text == out.text


# ─── TestQA ──────────────────────────────────────────────────


class TestQA:
    """qa 函式測試"""

    def test_qa_identical_files(self, sample_srt_file: Path):
        """相同檔案 QA 通過"""
        result = qa(str(sample_srt_file), str(sample_srt_file))
        assert result.is_valid is True
        assert result.source_count == 3
        assert result.target_count == 3
        assert len(result.errors) == 0

    def test_qa_count_mismatch(self, temp_dir: Path, sample_srt_file: Path):
        """字幕數量不匹配 QA 失敗"""
        short_srt = temp_dir / "short.srt"
        short_srt.write_text("""1
00:00:01,000 --> 00:00:03,000
Hello
""", encoding="utf-8")

        result = qa(str(sample_srt_file), str(short_srt))
        assert result.is_valid is False
        assert any("數量不匹配" in e for e in result.errors)

    def test_qa_timestamp_mismatch(self, temp_dir: Path, sample_srt_file: Path):
        """timestamp 不匹配產生錯誤"""
        modified_srt = temp_dir / "modified.srt"
        modified_srt.write_text("""1
00:00:01,000 --> 00:00:03,000
Hello, world!

2
00:00:04,500 --> 00:00:06,500
This is a test subtitle.

3
00:00:07,000 --> 00:00:09,000
Testing SRT translation.
""", encoding="utf-8")

        result = qa(str(sample_srt_file), str(modified_srt))
        assert result.is_valid is False
        assert any("timestamp" in e.lower() for e in result.errors)

    def test_qa_nonexistent_source(self, sample_srt_file: Path):
        """來源不存在應拋出 FileError"""
        with pytest.raises(FileError):
            qa("/nonexistent.srt", str(sample_srt_file))

    def test_qa_nonexistent_target(self, sample_srt_file: Path):
        """目標不存在應拋出 FileError"""
        with pytest.raises(FileError):
            qa(str(sample_srt_file), "/nonexistent.srt")

    def test_qa_after_roundtrip(self, sample_srt_file: Path):
        """extract → assemble roundtrip 後 QA 應通過"""
        prefix = str(sample_srt_file.with_suffix(""))
        extract(str(sample_srt_file))
        output = assemble(prefix, text_suffix="_text.txt")

        result = qa(str(sample_srt_file), output)
        assert result.is_valid is True


# ─── TestCpsAudit ────────────────────────────────────────────


class TestCpsAudit:
    """cps_audit 函式測試"""

    def test_clean_file_no_issues(self, sample_srt_file: Path):
        """正常檔案不應有問題"""
        report = cps_audit(str(sample_srt_file))
        assert isinstance(report, CpsAuditReport)
        assert report.total_subtitles == 3
        # 2 秒顯示短文字，CPS 應該很低
        assert report.avg_cps < 17.0

    def test_flags_high_cps(self, temp_dir: Path):
        """高 CPS 字幕被標記"""
        # 0.5 秒顯示 20 個字 → CPS = 40
        srt = temp_dir / "fast.srt"
        srt.write_text("""1
00:00:00,000 --> 00:00:00,500
這是一段非常長的字幕文字用來測試每秒字元數的計算是否正確
""", encoding="utf-8")

        report = cps_audit(str(srt), max_cps=17.0)
        assert report.problematic_count >= 1
        assert report.summary["high_cps"] >= 1

    def test_flags_long_lines(self, temp_dir: Path):
        """過長行被標記"""
        srt = temp_dir / "long.srt"
        srt.write_text("""1
00:00:00,000 --> 00:00:05,000
這是一段超過二十二個字元的非常非常非常非常長的字幕文字行
""", encoding="utf-8")

        report = cps_audit(str(srt), max_line_length=22)
        assert report.problematic_count >= 1
        assert report.summary["long_line"] >= 1

    def test_flags_too_many_lines(self, temp_dir: Path):
        """超過行數上限被標記"""
        srt = temp_dir / "lines.srt"
        srt.write_text("""1
00:00:00,000 --> 00:00:05,000
第一行
第二行
第三行
""", encoding="utf-8")

        report = cps_audit(str(srt), max_lines=2)
        assert report.problematic_count >= 1
        assert report.summary["too_many_lines"] >= 1

    def test_flags_short_duration(self, temp_dir: Path):
        """過短持續時間被標記"""
        srt = temp_dir / "short.srt"
        srt.write_text("""1
00:00:00,000 --> 00:00:00,500
Hi
""", encoding="utf-8")

        report = cps_audit(str(srt), min_duration_ms=1000)
        assert report.problematic_count >= 1
        assert report.summary["short_duration"] >= 1

    def test_custom_thresholds(self, sample_srt_file: Path):
        """自訂閾值生效"""
        # 極嚴格的閾值：CPS > 1 就標記
        report = cps_audit(str(sample_srt_file), max_cps=1.0)
        assert report.problematic_count >= 1

    def test_nonexistent_file(self):
        """不存在的檔案應拋出 FileError"""
        with pytest.raises(FileError):
            cps_audit("/nonexistent.srt")

    def test_report_summary_counts(self, temp_dir: Path):
        """summary 統計正確"""
        srt = temp_dir / "mixed.srt"
        srt.write_text("""1
00:00:00,000 --> 00:00:05,000
正常字幕

2
00:00:05,500 --> 00:00:06,000
這是一段非常長的字幕文字用來測試每秒字元數的計算
""", encoding="utf-8")

        report = cps_audit(str(srt))
        total_issues = sum(report.summary.values())
        assert total_issues >= 1


# ─── TestBatchHelpers ────────────────────────────────────────


class TestTextsToBatchString:
    """texts_to_batch_string 函式測試"""

    def test_basic_conversion(self):
        texts = ["你好", "世界", "測試"]
        result = texts_to_batch_string(texts)
        assert result == "你好\n世界\n測試"

    def test_multiline_escaping(self):
        texts = ["第一行\n第二行", "單行"]
        result = texts_to_batch_string(texts)
        assert result == "第一行\\n第二行\n單行"

    def test_empty_list(self):
        result = texts_to_batch_string([])
        assert result == ""

    def test_single_item(self):
        result = texts_to_batch_string(["Hello"])
        assert result == "Hello"


class TestBatchStringToTexts:
    """batch_string_to_texts 函式測試"""

    def test_basic_parsing(self):
        batch = "你好\n世界\n測試"
        result = batch_string_to_texts(batch, expected_count=3)
        assert result == ["你好", "世界", "測試"]

    def test_multiline_restoration(self):
        batch = "第一行\\n第二行\n單行"
        result = batch_string_to_texts(batch, expected_count=2)
        assert result[0] == "第一行\n第二行"
        assert result[1] == "單行"

    def test_count_mismatch_raises(self):
        batch = "一行\n兩行"
        with pytest.raises(ValidationError, match="行數不匹配"):
            batch_string_to_texts(batch, expected_count=3)

    def test_trailing_newline_handling(self):
        batch = "你好\n世界\n"
        result = batch_string_to_texts(batch, expected_count=2)
        assert result == ["你好", "世界"]

    def test_roundtrip(self):
        """texts_to_batch_string → batch_string_to_texts roundtrip"""
        original = ["Hello\nWorld", "單行", "第三行\n第四行"]
        batch = texts_to_batch_string(original)
        restored = batch_string_to_texts(batch, expected_count=3)
        assert restored == original
