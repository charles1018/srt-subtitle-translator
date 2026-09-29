#!/usr/bin/env python
"""產生 Rust 移植版的 golden parity 測試資料。

以 Python 實作（行為規格）跑一組固定輸入，將輸出寫成 JSON，
Rust 測試（rust/tests/golden_parity.rs）讀同一份 JSON 逐項比對。

用法（於 repo 根目錄）：
    .venv/bin/python rust/tools/gen_golden.py            # 產生 rust/tests/golden/*.json（進 git）
    .venv/bin/python rust/tools/gen_golden.py --local    # 另以 data/*.srt 產生 rust/tests/golden/local/（不進 git）
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from srt_translator.core.glossary import Glossary  # noqa: E402
from srt_translator.services.factory import TranslationService  # noqa: E402
from srt_translator.tools import srt_tools  # noqa: E402
from srt_translator.translation.client import TranslationClient  # noqa: E402
from srt_translator.utils.errors import AppError  # noqa: E402
from srt_translator.utils.post_processor import NetflixStylePostProcessor  # noqa: E402

GOLDEN_DIR = REPO / "rust" / "tests" / "golden"
FIXTURES = REPO / "tests" / "e2e" / "fixtures"

# ─── 手寫語料：涵蓋每條規則與邊界 ────────────────────────────

ZH_CASES = [
    "",
    "   ",
    "你好",
    '他說:"你好"!',
    "“真的”嗎?",
    "‘單引號’與'半形'",
    "價格１，２３４元",
    "共12,345人，還有1,234人",
    "１２３４５６",
    "等等.....",
    "嗯…。",
    "這個。。。那個",
    "結束了⋯.",
    "好的。\n走吧，",
    "尾端有空白。  \n下一行、",
    "我們今天一起去市場買菜，然後回家煮一頓豐盛的晚餐",
    "我和你還有他與她或者其他人但是沒有人來參加今天晚上的派對",
    "這是一個非常非常非常非常非常非常長而且沒有任何標點符號的句子",
    "Short English line",
    "This is a fairly long English subtitle line that should be split somewhere",
    "什麼？？",
    "真的!!",
    "你說什麼?!",
    "怎麼會！？",
    "第一行\n第二行\n第三行",
    "一行很長很長很長很長很長很長很長很長的字幕\n短行",
    "a,b;c:d!e?f",
    "“巢狀 ‘引號’ 測試”",
    '"未配對的引號',
    "１，２，３",
    "價值 ３，０００，０００ 美元",
    "tab\t分隔\t文字，以及全形　空白，然後還有更多更多的文字",
    "，開頭就是逗號的一句非常長的字幕內容測試用途",
    "和開頭的連接詞會讓斷點落在零的位置所以要強制斷行處理",
    "Ｗｉｄｅ字母不處理",
    "12,34,567",
    "約翰 • 威廉姆斯說美聯儲的通脹增長",
    "美國聯邦儲備銀行與聯邦儲備系統",
    "首席執行官在美東時間宣布招聘計畫",
    "瑪麗 · 安",
]

JA_CASES = [
    "メアちゃん、こっち来て",
    "「ゆいさんの」とメアちゃん",
    "ゆいちゃんってさ、かわいいね",
    "タナカ先生が来た",
    "お兄ちゃん",
    "さくら先輩！待って",
    "メアちゃんとゆいちゃんとメアちゃん",
    "アイ様のこと好き",
    "ハナコさんはどこ？",
    "こんにちは",
    "今日は天気がいい",
    "東京",
    "Hello there",
    "ユウキくん、ユウキくんってば",
    " カナさん",
    "（リンちゃん）",
    "ミサキ氏に",
    "あーちゃんね",
    "ゆいさんの",
]

REJECTION_TRANSLATIONS = [
    "",
    "  ",
    "你好",
    "[[JN0]]，過來",
    "JN0過來",
    "[ JN1 ]好可愛",
    "ABCJN0",
    "こんにちは",
    "你好ね",
    "メアちゃん，過來",
    "東京",
    "タナカ",
    "今日は天気がいい",
    "Hello there",
]

SOURCE_AWARE_PAIRS = [
    ("Straight ahead.", "直走"),
    ("straight   ahead", "繼續往前"),
    ("The oil shock.", "石油危機來了"),
    ("oil shock", "石油衝擊"),
    ("the oil shock is here", "石油危機"),
    ("Much more with John Smith.", "接下來我們將探討約翰·史密斯的更多觀點。"),
    ("Much more with the panel", "更多內容將與小組討論"),
    ("much more with", "更多"),
    ("Much more with Mary", "稍後請看瑪麗的看法！"),
    ("Much  more with  X", "  接下來是 X 的更多內容。 "),
    ("Hello", "  你好  "),
]

SINGLE_LINE_PAIRS = [
    ("one line", "第一\n第二 "),
    ("one line", "  前後空白  "),
    ("two\nlines", "第一\n第二"),
    ("x", "a\t\tb　c"),
]

LOCAL_OUTPUTS = [
    "你好",
    "  <think>推理</think>\n你好  ",
    "<|im_start|>assistant\n你好<|im_end|>",
    "<THINK>x</THINK>答案</think>",
    '{"translation": " 你好 "}',
    'reasoning {"translation":"嗨"}',
    '```json\n{"translation":"嗨"}\n```',
    '{"translation": 3}',
    '{"other": "x"}',
    "[1, 2]",
    "純文字",
    "",
    '<think>a</think>```\n{"translation":"b"}```',
]

RECORDS = ["a\nb", "back\\slash", "\\n literal", "trailing\\", "", "  spaced  ", "cr\r\nlf\rmix", "a\\tb"]


def post_processor_cases() -> list[dict]:
    configs = [
        {"auto_fix": True, "strict_mode": False, "max_chars_per_line": 16, "max_lines": 2},
        {"auto_fix": False, "strict_mode": False, "max_chars_per_line": 16, "max_lines": 2},
        {"auto_fix": True, "strict_mode": False, "max_chars_per_line": 22, "max_lines": 2},
    ]
    out = []
    for cfg in configs:
        processor = NetflixStylePostProcessor(**cfg)
        for text in ZH_CASES + JA_CASES + fixture_texts():
            result = processor.process(text)
            out.append(
                {
                    "config": cfg,
                    "input": text,
                    "text": result.text,
                    "auto_fixed": result.auto_fixed,
                    "warnings": [dataclasses.asdict(w) for w in result.warnings],
                    "formatted": processor.format_warnings(result),
                }
            )
    return out


def japanese_cases() -> dict:
    names = []
    for text in JA_CASES:
        candidates = TranslationClient._extract_japanese_name_candidates(text)
        protected, contexts, restore_map = TranslationClient._protect_japanese_names_in_inputs(
            TranslationClient.__new__(TranslationClient), text, [text + "？", "無關"]
        )
        mangled = protected.replace("[[JN0]]", "[ JN0 ]").replace("[[JN1]]", "JN1")
        names.append(
            {
                "input": text,
                "candidates": candidates,
                "protected": protected,
                "contexts": contexts,
                "restore_map": list(restore_map.items()),
                "restored": TranslationClient._restore_protected_japanese_names(protected, restore_map),
                "mangled": mangled,
                "mangled_restored": TranslationClient._restore_protected_japanese_names(mangled, restore_map),
            }
        )
    rejections = []
    for source in JA_CASES:
        for translated in [*REJECTION_TRANSLATIONS, source]:
            rejections.append(
                {
                    "source": source,
                    "translated": translated,
                    "reason": TranslationClient.get_cache_rejection_reason(source, translated),
                }
            )
    return {"names": names, "rejections": rejections}


def normalize_cases() -> dict:
    client = TranslationClient.__new__(TranslationClient)
    return {
        "taiwan_terms": [
            {"input": t, "output": TranslationClient.normalize_taiwan_subtitle_terminology(t)} for t in ZH_CASES
        ],
        "source_aware": [
            {
                "source": s,
                "translated": t,
                "output": TranslationService._normalize_source_aware_subtitle_phrases(s, t),
            }
            for s, t in SOURCE_AWARE_PAIRS
        ],
        "single_line": [
            {"source": s, "translated": t, "output": client._clean_single_line_translation(s, t)}
            for s, t in SINGLE_LINE_PAIRS
        ],
        "sanitize": [{"input": t, "output": client._sanitize_local_translation(t)} for t in LOCAL_OUTPUTS],
        "structured": [
            {"input": t, "output": client._extract_llamacpp_structured_translation(t)} for t in LOCAL_OUTPUTS
        ],
        "records": [
            {
                "input": r,
                "encoded": srt_tools._encode_text_record(r),
                "decoded": srt_tools._decode_text_record(r),
            }
            for r in RECORDS
        ],
    }


def glossary_cases() -> list[dict]:
    glossary = Glossary(name="g", source_lang="en", target_lang="zh-tw")
    glossary.add_entry("Fire", "火")
    glossary.add_entry("Fire Department", "消防局")
    glossary.add_entry("CPR", "心肺復甦術", case_sensitive=True)
    glossary.add_entry("ÉCOLE", "學校")
    glossary.add_entry("a.b", "點")
    texts = [
        "call the fire department, fire! CPR cpr",
        "FIRE DEPARTMENT",
        "école and École",
        "a.b axb",
        "",
    ]
    return [{"input": t, "output": glossary.apply_to_text(t)} for t in texts]


_FIXTURE_TEXTS: list[str] | None = None


def fixture_texts() -> list[str]:
    """已追蹤的 fixture 字幕文字（前 40 條，避免 golden 過大）。"""
    global _FIXTURE_TEXTS
    if _FIXTURE_TEXTS is None:
        texts: list[str] = []
        for name in ["sample.srt", "sample_japanese.srt", "special_chars.srt", "long_subtitle.srt"]:
            try:
                subs = srt_tools._open_srt(FIXTURES / name)
            except AppError:
                continue
            texts.extend(sub.text for sub in subs[:10])
        _FIXTURE_TEXTS = texts
    return _FIXTURE_TEXTS


def srt_file_case(path: Path, label: str) -> dict:
    case: dict = {"file": label}
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / path.name
        shutil.copy(path, copy)
        try:
            subs = srt_tools._open_srt(copy)
            case["items"] = [
                {"index": s.index, "start": str(s.start), "end": str(s.end), "text": s.text, "position": s.position}
                for s in subs
            ]
            buffer = []
            for s in subs:
                buffer.append(str(s))
                if not str(s).endswith("\n\n"):
                    buffer.append("\n")
            case["serialized"] = "".join(buffer)
        except AppError as e:
            case["open_error"] = e.error_code

        try:
            structure_path, text_path = srt_tools.extract(str(copy))
            case["extract"] = {
                "structure": Path(structure_path).read_text(encoding="utf-8"),
                "text": Path(text_path).read_text(encoding="utf-8"),
            }
            translated = Path(tmp) / (copy.stem + "_translated_text.txt")
            shutil.copy(text_path, translated)
            out = srt_tools.assemble(str(copy.with_suffix("")))
            case["assembled"] = Path(out).read_text(encoding="utf-8")
            qa = srt_tools.qa(str(copy), out)
            case["qa"] = dataclasses.asdict(qa)
        except AppError as e:
            case["extract_error"] = e.error_code

        try:
            case["cps_audit"] = dataclasses.asdict(srt_tools.cps_audit(str(copy)))
        except AppError as e:
            case["cps_audit_error"] = e.error_code
    return case


def srt_cases(paths: list[Path]) -> list[dict]:
    return [srt_file_case(p, p.name) for p in paths]


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"寫入 {path.relative_to(REPO)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--local", action="store_true", help="另以 data/*.srt（gitignored）產生本地 golden")
    args = parser.parse_args()

    write(GOLDEN_DIR / "post_processor.json", post_processor_cases())
    write(GOLDEN_DIR / "japanese.json", japanese_cases())
    write(GOLDEN_DIR / "normalize.json", normalize_cases())
    write(GOLDEN_DIR / "glossary.json", glossary_cases())
    fixture_paths = sorted(p for p in FIXTURES.glob("*.srt") if p.name != "very_large.srt")
    fixture_paths += sorted((FIXTURES / "batch").glob("*.srt"))
    write(GOLDEN_DIR / "srt_files.json", srt_cases(fixture_paths))

    if args.local:
        local_paths = sorted((REPO / "data").glob("*.srt"))
        write(GOLDEN_DIR / "local" / "srt_files.json", srt_cases(local_paths))
        texts = []
        for p in local_paths:
            texts.extend(s.text for s in srt_tools._open_srt(p))
        processor = NetflixStylePostProcessor()
        write(
            GOLDEN_DIR / "local" / "post_processor.json",
            [{"input": t, "text": processor.process(t).text} for t in texts],
        )


if __name__ == "__main__":
    main()
