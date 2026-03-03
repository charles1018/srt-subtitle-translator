"""SRT 字幕工具 — 結構-文本分離工作流

提供 extract / assemble / qa / cps-audit 功能，
將字幕的不可變結構（index、timestamp）與可翻譯文本分離處理，
消除 LLM 翻譯時損壞結構的風險。

工作流:
    1. extract  — SRT → _structure.json + _text.txt
    2. 翻譯     — 只翻譯純文本（LLM 或其他工具）
    3. assemble — _structure.json + _translated_text.txt → 翻譯後 SRT
    4. qa       — 驗證源檔與翻譯檔的結構完整性
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import chardet
import pysrt

from srt_translator.utils.errors import FileError, ValidationError

logger = logging.getLogger(__name__)


# ─── 資料結構 ───────────────────────────────────────────────


@dataclass
class SubtitleStructure:
    """單一字幕的結構資訊（不含文本）"""

    index: int
    start: str  # SRT 時間格式 "HH:MM:SS,mmm"
    end: str  # SRT 時間格式 "HH:MM:SS,mmm"
    line_count: int  # 原始文本行數（審計用）


@dataclass
class QAResult:
    """QA 比對結果"""

    is_valid: bool
    source_count: int
    target_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SubtitleAuditEntry:
    """單一字幕的 CPS 審計資訊"""

    index: int
    text: str
    duration_ms: int
    char_count: int
    cps: float
    line_count: int
    max_line_length: int
    issues: list[str] = field(default_factory=list)


@dataclass
class CpsAuditReport:
    """CPS 審計報告"""

    total_subtitles: int
    problematic_count: int
    entries: list[SubtitleAuditEntry] = field(default_factory=list)
    avg_cps: float = 0.0
    max_cps: float = 0.0
    summary: dict[str, int] = field(default_factory=dict)


# ─── 內部輔助 ───────────────────────────────────────────────


def _detect_encoding(file_path: Path) -> str:
    """偵測檔案編碼，失敗時退回 utf-8"""
    raw = file_path.read_bytes()
    result = chardet.detect(raw)
    encoding = result.get("encoding") or "utf-8"
    # chardet 常回傳 'ascii'，但 utf-8 是更安全的超集
    if encoding.lower() in ("ascii", "windows-1252"):
        encoding = "utf-8"
    return encoding


def _open_srt(srt_path: Path) -> pysrt.SubRipFile:
    """以偵測的編碼開啟 SRT 檔案"""
    encoding = _detect_encoding(srt_path)
    try:
        return pysrt.open(str(srt_path), encoding=encoding)
    except Exception as e:
        raise FileError(f"無法解析 SRT 檔案: {srt_path}", details={"error": str(e)}) from e


# ─── 核心功能: extract ──────────────────────────────────────


def extract(srt_path: str, output_prefix: str | None = None) -> tuple[str, str]:
    """將 SRT 拆分為 _structure.json + _text.txt

    Args:
        srt_path: 輸入 SRT 檔案路徑
        output_prefix: 輸出檔案前綴，None 時自動從輸入路徑產生

    Returns:
        (structure_json_path, text_txt_path)

    Raises:
        FileError: 檔案不存在或無法解析
    """
    path = Path(srt_path)
    if not path.exists():
        raise FileError(f"檔案不存在: {srt_path}")

    subs = _open_srt(path)
    if len(subs) == 0:
        raise FileError(f"SRT 檔案為空或無法解析: {srt_path}")

    # 計算輸出前綴
    if output_prefix is None:
        output_prefix = str(path.with_suffix(""))
    prefix = Path(output_prefix)

    # 建立結構 JSON
    structure: list[dict] = []
    text_lines: list[str] = []

    for sub in subs:
        text = sub.text
        # 計算原始行數
        lines = text.split("\n")
        line_count = len(lines)

        structure.append({
            "index": sub.index,
            "start": str(sub.start),
            "end": str(sub.end),
            "line_count": line_count,
        })

        # 多行文本用 literal \n 合併為單行
        escaped = text.replace("\n", "\\n")
        text_lines.append(escaped)

    # 寫入結構 JSON
    structure_path = Path(f"{prefix}_structure.json")
    structure_path.write_text(
        json.dumps(structure, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 寫入文本檔（一行一字幕）
    text_path = Path(f"{prefix}_text.txt")
    text_path.write_text("\n".join(text_lines) + "\n", encoding="utf-8")

    logger.info("提取完成: %d 個字幕 → %s, %s", len(subs), structure_path, text_path)
    return str(structure_path), str(text_path)


# ─── 核心功能: assemble ─────────────────────────────────────


def assemble(
    base_prefix: str,
    text_suffix: str = "_translated_text.txt",
    output_path: str | None = None,
) -> str:
    """將 _structure.json + 翻譯文本組合為 SRT

    Args:
        base_prefix: 檔案前綴（與 extract 輸出的相同）
        text_suffix: 翻譯文本檔案後綴
        output_path: 輸出 SRT 路徑，None 時自動產生

    Returns:
        輸出 SRT 路徑

    Raises:
        FileError: 必要檔案不存在
        ValidationError: 行數不匹配
    """
    prefix = Path(base_prefix)
    structure_path = Path(f"{prefix}_structure.json")
    text_path = Path(f"{prefix}{text_suffix}")

    if not structure_path.exists():
        raise FileError(f"結構檔案不存在: {structure_path}")
    if not text_path.exists():
        raise FileError(f"文本檔案不存在: {text_path}")

    # 讀取結構
    structure: list[dict] = json.loads(structure_path.read_text(encoding="utf-8"))

    # 讀取翻譯文本
    translated_lines = text_path.read_text(encoding="utf-8").strip().splitlines()

    # 嚴格 1:1 行數驗證
    if len(structure) != len(translated_lines):
        diff = len(translated_lines) - len(structure)
        error_msg = (
            f"行數不匹配: 結構有 {len(structure)} 個字幕，"
            f"翻譯文本有 {len(translated_lines)} 行 (差異: {diff:+d})"
        )

        # 顯示錯誤上下文（與 subtitle-workbench 相同的診斷方式）
        min_len = min(len(structure), len(translated_lines))
        details: dict = {
            "structure_count": len(structure),
            "translated_count": len(translated_lines),
            "diff": diff,
        }
        if min_len > 0:
            start = max(0, min_len - 3)
            context_lines = []
            for j in range(start, min_len):
                context_lines.append(f"  [{j + 1}] {translated_lines[j][:60]}")
            details["last_aligned"] = context_lines

            if len(translated_lines) > len(structure):
                overflow = []
                for j in range(len(structure), min(len(translated_lines), len(structure) + 5)):
                    overflow.append(f"  [{j + 1}] {translated_lines[j][:60]}")
                details["overflow_lines"] = overflow

        raise ValidationError(error_msg, details=details)

    # 組合 SRT
    srt_file = pysrt.SubRipFile()
    for entry, trans_line in zip(structure, translated_lines, strict=True):
        # literal \n → 真實換行
        text = trans_line.replace("\\n", "\n")

        item = pysrt.SubRipItem(
            index=entry["index"],
            start=pysrt.SubRipTime.from_string(entry["start"]),
            end=pysrt.SubRipTime.from_string(entry["end"]),
            text=text,
        )
        srt_file.append(item)

    # 決定輸出路徑
    if output_path is None:
        output_path = f"{prefix}.zh-TW.srt"
    out = Path(output_path)

    srt_file.save(str(out), encoding="utf-8")
    logger.info("組合完成: %d 個字幕 → %s", len(structure), out)
    return str(out)


# ─── 核心功能: qa ───────────────────────────────────────────


def qa(source_srt_path: str, target_srt_path: str) -> QAResult:
    """驗證源檔與翻譯檔的結構完整性

    Args:
        source_srt_path: 原始 SRT 檔案路徑
        target_srt_path: 翻譯後 SRT 檔案路徑

    Returns:
        QAResult

    Raises:
        FileError: 檔案不存在
    """
    src_path = Path(source_srt_path)
    tgt_path = Path(target_srt_path)

    if not src_path.exists():
        raise FileError(f"來源檔案不存在: {source_srt_path}")
    if not tgt_path.exists():
        raise FileError(f"目標檔案不存在: {target_srt_path}")

    src_subs = _open_srt(src_path)
    tgt_subs = _open_srt(tgt_path)

    errors: list[str] = []
    warnings: list[str] = []

    # 1. 字幕數量比對
    if len(src_subs) != len(tgt_subs):
        errors.append(
            f"字幕數量不匹配: 來源 {len(src_subs)} 個，目標 {len(tgt_subs)} 個"
        )
        return QAResult(
            is_valid=False,
            source_count=len(src_subs),
            target_count=len(tgt_subs),
            errors=errors,
        )

    # 2. 逐一比對 timestamp 和 index
    ts_mismatches = 0
    idx_mismatches = 0
    for i, (src, tgt) in enumerate(zip(src_subs, tgt_subs, strict=True)):
        if src.index != tgt.index:
            idx_mismatches += 1
            if idx_mismatches <= 5:
                warnings.append(
                    f"Index 不匹配 #{i + 1}: 來源={src.index}, 目標={tgt.index}"
                )

        if str(src.start) != str(tgt.start) or str(src.end) != str(tgt.end):
            ts_mismatches += 1
            if ts_mismatches <= 5:
                warnings.append(
                    f"Timestamp 不匹配 #{src.index}: "
                    f"來源={src.start} --> {src.end}, "
                    f"目標={tgt.start} --> {tgt.end}"
                )

    if ts_mismatches > 5:
        warnings.append(f"... 共 {ts_mismatches} 個 timestamp 不匹配")
    if idx_mismatches > 5:
        warnings.append(f"... 共 {idx_mismatches} 個 index 不匹配")

    if ts_mismatches > 0:
        errors.append(f"共 {ts_mismatches} 個 timestamp 不匹配")
    if idx_mismatches > 0:
        errors.append(f"共 {idx_mismatches} 個 index 不匹配")

    is_valid = len(errors) == 0
    logger.info(
        "QA %s: 來源 %d 個字幕，目標 %d 個字幕，%d 個錯誤，%d 個警告",
        "通過" if is_valid else "失敗",
        len(src_subs),
        len(tgt_subs),
        len(errors),
        len(warnings),
    )

    return QAResult(
        is_valid=is_valid,
        source_count=len(src_subs),
        target_count=len(tgt_subs),
        errors=errors,
        warnings=warnings,
    )


# ─── CPS 可讀性審計 ─────────────────────────────────────────


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    """移除 HTML/ASS 標籤，回傳純顯示文字"""
    return _TAG_RE.sub("", text)


def cps_audit(
    srt_path: str,
    max_cps: float = 17.0,
    max_line_length: int = 22,
    max_lines: int = 2,
    min_duration_ms: int = 1000,
) -> CpsAuditReport:
    """CPS / 可讀性審計

    標記超過閾值的字幕條目:
    - CPS > max_cps
    - 單行超過 max_line_length 字元
    - 行數 > max_lines
    - 持續時間 < min_duration_ms 毫秒

    Args:
        srt_path: SRT 檔案路徑
        max_cps: CPS 上限（預設 17.0）
        max_line_length: 單行字元上限（預設 22）
        max_lines: 行數上限（預設 2）
        min_duration_ms: 最短持續時間毫秒（預設 1000）

    Returns:
        CpsAuditReport

    Raises:
        FileError: 檔案不存在或無法解析
    """
    path = Path(srt_path)
    if not path.exists():
        raise FileError(f"檔案不存在: {srt_path}")

    subs = _open_srt(path)
    if len(subs) == 0:
        raise FileError(f"SRT 檔案為空或無法解析: {srt_path}")

    problematic: list[SubtitleAuditEntry] = []
    all_cps: list[float] = []
    summary: dict[str, int] = {
        "high_cps": 0,
        "long_line": 0,
        "too_many_lines": 0,
        "short_duration": 0,
    }

    for sub in subs:
        text = sub.text
        plain = _strip_tags(text)
        display_lines = text.split("\n")
        line_count = len(display_lines)
        max_len = max((len(_strip_tags(line)) for line in display_lines), default=0)

        duration_ms = sub.end.ordinal - sub.start.ordinal
        duration_sec = max(duration_ms / 1000.0, 0.001)
        char_count = len(plain)
        cps = char_count / duration_sec
        all_cps.append(cps)

        issues: list[str] = []
        if cps > max_cps:
            issues.append(f"CPS={cps:.1f} (>{max_cps})")
            summary["high_cps"] += 1
        if max_len > max_line_length:
            issues.append(f"行長={max_len} (>{max_line_length})")
            summary["long_line"] += 1
        if line_count > max_lines:
            issues.append(f"行數={line_count} (>{max_lines})")
            summary["too_many_lines"] += 1
        if duration_ms < min_duration_ms:
            issues.append(f"持續={duration_ms}ms (<{min_duration_ms}ms)")
            summary["short_duration"] += 1

        if issues:
            problematic.append(SubtitleAuditEntry(
                index=sub.index,
                text=plain[:60],
                duration_ms=duration_ms,
                char_count=char_count,
                cps=round(cps, 2),
                line_count=line_count,
                max_line_length=max_len,
                issues=issues,
            ))

    avg_cps = sum(all_cps) / len(all_cps) if all_cps else 0.0
    max_cps_val = max(all_cps) if all_cps else 0.0

    report = CpsAuditReport(
        total_subtitles=len(subs),
        problematic_count=len(problematic),
        entries=problematic,
        avg_cps=round(avg_cps, 2),
        max_cps=round(max_cps_val, 2),
        summary=summary,
    )

    logger.info(
        "CPS 審計: %d/%d 個字幕有問題 (平均 CPS=%.1f, 最高=%.1f)",
        len(problematic),
        len(subs),
        avg_cps,
        max_cps_val,
    )
    return report


# ─── 批次文本輔助函式 ────────────────────────────────────────


def texts_to_batch_string(texts: list[str]) -> str:
    """將字幕文本列表轉換為批次字串

    每個字幕成為一行，內部換行以 literal \\n 跳脫。

    Args:
        texts: 字幕文本列表（可含真實換行）

    Returns:
        批次字串（以真實換行分隔各字幕）
    """
    escaped = [text.replace("\n", "\\n") for text in texts]
    return "\n".join(escaped)


def batch_string_to_texts(batch_string: str, expected_count: int) -> list[str]:
    """將 LLM 批次翻譯輸出轉回字幕文本列表

    Args:
        batch_string: LLM 輸出（每行一字幕）
        expected_count: 預期行數

    Returns:
        翻譯後的字幕文本列表（已還原真實換行）

    Raises:
        ValidationError: 行數不匹配
    """
    lines = batch_string.strip().splitlines()
    if len(lines) != expected_count:
        raise ValidationError(
            f"行數不匹配: 預期 {expected_count} 行，實際 {len(lines)} 行",
            details={"expected": expected_count, "actual": len(lines)},
        )
    return [line.replace("\\n", "\n") for line in lines]
