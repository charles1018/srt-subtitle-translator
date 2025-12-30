#!/usr/bin/env python
"""
Netflix 字幕風格後處理器

此模組提供字幕文本的後處理功能，確保翻譯結果符合 Netflix 繁體中文字幕規範。
"""

import logging
import re
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ProcessingWarning:
    """處理警告資訊"""

    code: str
    message: str
    line_number: Optional[int] = None
    original_text: Optional[str] = None
    fixed_text: Optional[str] = None


@dataclass
class ProcessingResult:
    """處理結果"""

    text: str
    warnings: List[ProcessingWarning] = field(default_factory=list)
    auto_fixed: int = 0

    def add_warning(self, code: str, message: str, **kwargs):
        """添加警告"""
        self.warnings.append(ProcessingWarning(code=code, message=message, **kwargs))


class NetflixStylePostProcessor:
    """Netflix 字幕風格後處理器

    根據 Netflix 繁體中文字幕風格指南自動修正和驗證字幕文本。

    功能:
        - 自動修正標點符號格式
        - 轉換引號格式
        - 修正數字格式
        - 統一省略號使用
        - 驗證字符限制
        - 檢查連貫性規範
    """

    # 標點符號映射表
    PUNCTUATION_MAP: ClassVar[Dict[str, str]] = {
        ",": "，",
        ";": "；",
        ":": "：",
        "!": "！",
        "?": "？",
        # 省略號特殊處理
        "...": "⋯",
        "。。。": "⋯",
        "…": "⋯",  # U+2026 -> U+22EF
    }

    # 引號映射表
    QUOTE_MAP: ClassVar[Dict[str, Tuple[str, str]]] = {
        '"': ("「", "」"),
        "'": ("「", "」"),
        """: ('「', '」'),
        """: ("「", "」"),
    }

    # 全形數字轉半形
    FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

    def __init__(
        self, auto_fix: bool = True, strict_mode: bool = False, max_chars_per_line: int = 16, max_lines: int = 2
    ):
        """初始化後處理器

        參數:
            auto_fix: 是否自動修正可修正的問題
            strict_mode: 嚴格模式，不符合規範會報錯而非警告
            max_chars_per_line: 每行最大字符數
            max_lines: 最大行數
        """
        self.auto_fix = auto_fix
        self.strict_mode = strict_mode
        self.max_chars_per_line = max_chars_per_line
        self.max_lines = max_lines

    def process(self, text: str) -> ProcessingResult:
        """處理文本，應用所有 Netflix 規範

        參數:
            text: 原始翻譯文本

        回傳:
            ProcessingResult: 處理結果，包含處理後的文本和警告列表
        """
        result = ProcessingResult(text=text)

        if not text or not text.strip():
            return result

        # 1. 修正標點符號
        result.text = self._fix_punctuation(result.text, result)

        # 2. 修正引號
        result.text = self._fix_quotations(result.text, result)

        # 3. 修正數字格式
        result.text = self._fix_numbers(result.text, result)

        # 4. 修正省略號
        result.text = self._fix_ellipsis(result.text, result)

        # 5. 移除行尾標點
        result.text = self._remove_line_end_punctuation(result.text, result)

        # 6. 檢查並修正字符限制
        result.text = self._check_and_fix_character_limit(result.text, result)

        # 7. 檢查問號
        self._check_question_marks(result.text, result)

        logger.debug(f"後處理完成: {len(result.warnings)} 個警告, {result.auto_fixed} 個自動修正")

        return result

    def _fix_punctuation(self, text: str, result: ProcessingResult) -> str:
        """修正標點符號為全形中文標點

        參數:
            text: 輸入文本
            result: 處理結果對象

        回傳:
            修正後的文本
        """
        if not self.auto_fix:
            return text

        original = text

        # 替換常見的半形標點為全形
        for half, full in self.PUNCTUATION_MAP.items():
            if half == "..." or half == "。。。" or half == "…":
                continue  # 省略號在 _fix_ellipsis 中處理

            if half in text:
                text = text.replace(half, full)

        if text != original:
            result.auto_fixed += 1
            result.add_warning(
                "PUNCT_FIXED", "已自動轉換半形標點為全形中文標點", original_text=original, fixed_text=text
            )

        return text

    def _fix_quotations(self, text: str, result: ProcessingResult) -> str:
        """修正引號格式為中文引號

        參數:
            text: 輸入文本
            result: 處理結果對象

        回傳:
            修正後的文本
        """
        if not self.auto_fix:
            return text

        original = text

        # 處理成對的引號
        for western_quote, (open_quote, close_quote) in self.QUOTE_MAP.items():
            if western_quote not in text:
                continue

            # 簡單的配對算法：奇數位置為開引號，偶數位置為閉引號
            parts = text.split(western_quote)
            if len(parts) > 1:
                new_parts = [parts[0]]
                for i, part in enumerate(parts[1:], start=1):
                    # 奇數次出現 -> 開引號，偶數次 -> 閉引號
                    quote = open_quote if i % 2 == 1 else close_quote
                    new_parts.append(quote + part)
                text = "".join(new_parts)

        if text != original:
            result.auto_fixed += 1
            result.add_warning("QUOTE_FIXED", "已自動轉換引號為中文引號「」", original_text=original, fixed_text=text)

        return text

    def _fix_numbers(self, text: str, result: ProcessingResult) -> str:
        """修正數字格式（全形轉半形）

        參數:
            text: 輸入文本
            result: 處理結果對象

        回傳:
            修正後的文本
        """
        if not self.auto_fix:
            return text

        original = text

        # 先處理數字中的全形逗號（臨時轉為半形），然後轉換全形數字為半形
        # 這樣可以統一處理數字分隔符
        text = re.sub(r"([０-９])，([０-９])", r"\1,\2", text)

        # 轉換全形數字為半形
        text = text.translate(self.FULLWIDTH_TO_HALFWIDTH)

        # 移除四位數中的逗號分隔符（如 1,234 -> 1234，但保留五位數以上的）
        # 使用正則表達式匹配 1-3 位數字 + 逗號 + 3 位數字（共4位）
        # 只匹配沒有前後數字的情況（避免誤刪大數字中的逗號）
        text = re.sub(r"(?<!\d)(\d{1,3}),(\d{3})(?!\d)", r"\1\2", text)

        if text != original:
            result.auto_fixed += 1
            result.add_warning(
                "NUMBER_FIXED",
                "已自動轉換數字格式（全形轉半形，移除四位數逗號）",
                original_text=original,
                fixed_text=text,
            )

        return text

    def _fix_ellipsis(self, text: str, result: ProcessingResult) -> str:
        """修正省略號格式為 ⋯ (U+22EF)

        Netflix 規範要求使用 U+2026，但在此我們使用 U+22EF (⋯)
        因為它在繁體中文字幕中更常見

        參數:
            text: 輸入文本
            result: 處理結果對象

        回傳:
            修正後的文本
        """
        if not self.auto_fix:
            return text

        original = text

        # 替換各種省略號為統一格式
        # ... -> ⋯
        text = re.sub(r"\.{3,}", "⋯", text)
        # 。。。 -> ⋯
        text = text.replace("。。。", "⋯")
        # U+2026 (…) -> U+22EF (⋯)
        text = text.replace("…", "⋯")

        # 移除省略號後多餘的句號
        text = re.sub(r"⋯\.", "⋯", text)

        if text != original:
            result.auto_fixed += 1
            result.add_warning("ELLIPSIS_FIXED", "已自動統一省略號格式為 ⋯", original_text=original, fixed_text=text)

        return text

    def _remove_line_end_punctuation(self, text: str, result: ProcessingResult) -> str:
        """移除行尾的句號和逗號

        Netflix 規範: 不要在行尾使用任何句號或逗號

        參數:
            text: 輸入文本
            result: 處理結果對象

        回傳:
            修正後的文本
        """
        if not self.auto_fix:
            return text

        original = text
        lines = text.split("\n")
        fixed_lines = []

        for line in lines:
            stripped = line.rstrip()
            # 移除行尾的 。 或 ，
            if stripped.endswith("。") or stripped.endswith("，"):
                stripped = stripped[:-1]
                # 保留原始的尾隨空白（如果有）
                trailing_space = line[len(line.rstrip()) :]
                fixed_lines.append(stripped + trailing_space)
            else:
                fixed_lines.append(line)

        text = "\n".join(fixed_lines)

        if text != original:
            result.auto_fixed += 1
            result.add_warning(
                "LINE_END_PUNCT_REMOVED", "已自動移除行尾的句號和逗號", original_text=original, fixed_text=text
            )

        return text

    def _smart_split_line(self, line: str, max_chars: int) -> List[str]:
        """智慧分割長行

        優先在以下位置斷行:
        1. 逗號、頓號後
        2. 連接詞(和、與、或、但)前後
        3. 空格處
        4. 最後才考慮強制斷行

        參數:
            line: 要分割的行
            max_chars: 每行最大字符數

        回傳:
            分割後的行列表
        """
        if len(line) <= max_chars:
            return [line]

        # 定義斷行優先級 (pattern, offset)
        # offset: 0=在匹配字符前斷行, 1=在匹配字符後斷行
        split_points = [
            (r"[，、]", 1),  # 逗號、頓號後
            (r"[和與或但]", 0),  # 連接詞前
            (r"\s", 1),  # 空格後
        ]

        result = []
        remaining = line

        while len(remaining) > max_chars:
            best_pos = -1
            best_priority = float("inf")

            # 尋找最佳斷點(接近中間位置的優先)
            for pattern, offset in split_points:
                matches = list(re.finditer(pattern, remaining[:max_chars]))
                if matches:
                    # 選擇最後一個匹配(最接近行尾)
                    match = matches[-1]
                    pos = match.end() if offset else match.start()
                    # 計算與理想斷點(行的一半)的距離
                    distance = abs(pos - max_chars // 2)
                    if distance < best_priority:
                        best_pos = pos
                        best_priority = distance

            if best_pos > 0:
                # 在最佳位置斷行
                result.append(remaining[:best_pos].strip())
                remaining = remaining[best_pos:].lstrip()
            else:
                # 沒有找到好的斷點,強制斷行
                result.append(remaining[:max_chars].strip())
                remaining = remaining[max_chars:].lstrip()

        # 加入剩餘部分
        if remaining:
            result.append(remaining.strip())

        return result

    def _check_and_fix_character_limit(self, text: str, result: ProcessingResult) -> str:
        """檢查並修正字符限制

        Netflix 規範: 每行最多 16 個字符，最多 2 行

        參數:
            text: 輸入文本
            result: 處理結果對象

        回傳:
            修正後的文本(如果 auto_fix=True)
        """
        lines = text.split("\n")
        fixed_lines = []
        needs_fix = False

        # 處理每一行
        for i, line in enumerate(lines, start=1):
            line_stripped = line.strip()
            char_count = len(line_stripped)

            if char_count > self.max_chars_per_line:
                if self.auto_fix:
                    # 自動分割
                    split_lines = self._smart_split_line(line_stripped, self.max_chars_per_line)
                    fixed_lines.extend(split_lines)
                    needs_fix = True
                    result.auto_fixed += 1

                    result.add_warning(
                        "LINE_TOO_LONG_AUTO_FIXED",
                        f"第 {i} 行超過限制 ({char_count} 字符)，已自動分割為 {len(split_lines)} 行",
                        line_number=i,
                        original_text=line_stripped,
                        fixed_text="\n".join(split_lines),
                    )

                    logger.debug(
                        f"自動分割第 {i} 行: {char_count} 字符 -> {len(split_lines)} 行 "
                        f"({', '.join(str(len(line)) for line in split_lines)} 字符)"
                    )
                else:
                    # 不自動修正，只發出警告
                    fixed_lines.append(line_stripped)
                    result.add_warning(
                        "LINE_TOO_LONG",
                        f"第 {i} 行超過字符限制: {char_count} 字符 (最多 {self.max_chars_per_line} 字符)",
                        line_number=i,
                        original_text=line_stripped,
                    )
            else:
                fixed_lines.append(line_stripped)

        # 檢查行數(在分割後)
        if len(fixed_lines) > self.max_lines:
            result.add_warning(
                "TOO_MANY_LINES",
                f"超過最大行數限制: {len(fixed_lines)} 行 (最多 {self.max_lines} 行)",
                line_number=len(fixed_lines),
            )

        return "\n".join(fixed_lines) if needs_fix else text

    def _check_question_marks(self, text: str, result: ProcessingResult) -> None:
        """檢查問號使用

        Netflix 規範: 問號是必需的，不要省略；不要使用雙問號或雙驚嘆號

        參數:
            text: 輸入文本
            result: 處理結果對象
        """
        # 檢查雙問號
        if "？？" in text or "??" in text:
            result.add_warning("DOUBLE_QUESTION_MARK", "不應使用雙問號 (？？)", original_text=text)

        # 檢查雙驚嘆號
        if "！！" in text or "!!" in text:
            result.add_warning("DOUBLE_EXCLAMATION", "不應使用雙驚嘆號 (！！)", original_text=text)

        # 檢查混合標點 !?
        if "!?" in text or "！？" in text or "?!" in text or "？！" in text:
            result.add_warning("MIXED_PUNCTUATION", "不應使用混合驚嘆問號 (!? 或 ?!)", original_text=text)

    def format_warnings(self, result: ProcessingResult) -> str:
        """格式化警告訊息為可讀字符串

        參數:
            result: 處理結果對象

        回傳:
            格式化的警告訊息
        """
        if not result.warnings:
            return "無警告"

        lines = [f"共 {len(result.warnings)} 個警告，{result.auto_fixed} 個自動修正:\n"]

        for i, warning in enumerate(result.warnings, start=1):
            line_info = f" (第{warning.line_number}行)" if warning.line_number else ""
            lines.append(f"{i}. [{warning.code}]{line_info} {warning.message}")

            if warning.original_text and warning.fixed_text:
                lines.append(f"   原文: {warning.original_text[:50]}...")
                lines.append(f"   修正: {warning.fixed_text[:50]}...")

        return "\n".join(lines)
