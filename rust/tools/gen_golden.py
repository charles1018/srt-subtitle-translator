#!/usr/bin/env python
"""產生 Rust 移植版的 golden parity 測試資料。

以 Python 實作（行為規格）跑一組固定輸入，將輸出寫成 JSON，
Rust 測試（rust/tests/golden_parity.rs）讀同一份 JSON 逐項比對。

用法（於 repo 根目錄）：
    .venv/bin/python rust/tools/gen_golden.py            # 產生 rust/tests/golden/*.json（進 git）
    .venv/bin/python rust/tools/gen_golden.py --local    # 另以 data/*.srt 產生 rust/tests/golden/local/（不進 git）
    .venv/bin/python rust/tools/gen_golden.py --check    # 只檢查是否過期（CI 用）
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# 隔離設定目錄，避免 ConfigManager / PromptManager 讀寫真實的 config/
os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="golden-config-")

from srt_translator.core.cache import CacheManager  # noqa: E402
from srt_translator.core.glossary import Glossary  # noqa: E402
from srt_translator.core.prompt import PromptManager  # noqa: E402
from srt_translator.services.factory import TranslationService  # noqa: E402
from srt_translator.tools import srt_tools  # noqa: E402
from srt_translator.translation.client import TranslationClient  # noqa: E402
from srt_translator.utils.errors import AppError  # noqa: E402
from srt_translator.utils.post_processor import NetflixStylePostProcessor  # noqa: E402

GOLDEN_DIR = REPO / "rust" / "tests" / "golden"
PROMPT_ASSET = REPO / "rust" / "src" / "prompt" / "default_prompts.json"
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


# ─── Prompt ─────────────────────────────────────────────────

PROMPT_LLM_TYPES = ["llamacpp", "openai", "google"]
PROMPT_CONTENT_TYPES = ["general", "adult", "anime", "movie", "english_drama"]
PROMPT_STYLES = ["standard", "literal", "localized", "specialized"]
PROMPT_MODELS = ["", "Hy-MT2-7B-Q4_K_M.gguf", "Qwen3.6-27B-UD-Q4_K_XL", "qwen3.5-9b", "gpt-4.1-mini"]
PROMPT_LANGUAGE_PAIRS = ["日文→繁體中文", "英文→繁體中文", "繁體中文→日文", "韓文→繁體中文"]

MESSAGE_CASES: list[tuple[str, list[str], int | None]] = [
    ("こんにちは", ["前の文", "こんにちは", "次の文"], None),
    ("I went there when", ["Hi.", "I went there when", "it rained."], None),
    ("Wait,", ["Okay.", "Wait,", "what?"], None),
    ("Something is off...", ["Something is off..."], None),
    ("はい", ["はい", "舐めて", "はい", "もっと"], 2),
    ("はい", ["はい", "x", "はい"], None),
    ("はい", ["はい", "x", "はい"], 7),
    ("missing", ["a", "b"], None),
    ("舐めて", ["前", "舐めて", "後"], None),
    ("[BATCH: 2 lines]\nline1\nline2", [], None),
    ("single", ["single"], None),
    ("メアちゃん、こっち", ["うん", "メアちゃん、こっち", "え？"], None),
    ("Line one\nline two", ["prev", "Line one\nline two"], None),
    ("行くよ？", ["イク", "行くよ？", "うん"], None),
    ("あ", ["どう？", "あ", "ね"], None),
]


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def new_prompt_manager(language_pair: str, compact: bool) -> PromptManager:
    config_dir = Path(tempfile.mkdtemp(prefix="golden-prompt-"))
    manager = PromptManager(config_file=str(config_dir / "prompt_config.json"))
    manager.user_config_manager.set_value("translation.compact_prompt_enabled", compact)
    manager.set_language_pair(language_pair)
    return manager


def prompt_cases() -> dict:
    texts: dict[str, str] = {}

    def ref(text: str) -> str:
        key = md5(text)
        texts[key] = text
        return key

    cases = []
    for language_pair in PROMPT_LANGUAGE_PAIRS:
        for compact in (True, False):
            manager = new_prompt_manager(language_pair, compact)
            for content_type in PROMPT_CONTENT_TYPES:
                manager.set_content_type(content_type)
                for style in PROMPT_STYLES:
                    manager.set_translation_style(style)
                    for llm_type in PROMPT_LLM_TYPES:
                        for model in PROMPT_MODELS:
                            cases.append(
                                {
                                    "language_pair": language_pair,
                                    "compact": compact,
                                    "content_type": content_type,
                                    "style": style,
                                    "llm_type": llm_type,
                                    "model": model,
                                    "prompt": ref(manager.get_prompt(llm_type, model_name=model)),
                                    "version": manager.get_prompt_version(llm_type, model_name=model),
                                    "batch_prompt": ref(
                                        manager.get_batch_translation_prompt(llm_type, model_name=model)
                                    ),
                                    "batch_version": manager.get_prompt_version(
                                        llm_type, model_name=model, batch_request=True
                                    ),
                                }
                            )

    messages = []
    for language_pair in ["日文→繁體中文", "英文→繁體中文"]:
        for compact in (True, False):
            manager = new_prompt_manager(language_pair, compact)
            for content_type in ["general", "adult"]:
                manager.set_content_type(content_type)
                for llm_type in PROMPT_LLM_TYPES:
                    for model in PROMPT_MODELS:
                        for text, context, index in MESSAGE_CASES:
                            result = manager.get_optimized_message(text, context, llm_type, model, current_index=index)
                            messages.append(
                                {
                                    "language_pair": language_pair,
                                    "compact": compact,
                                    "content_type": content_type,
                                    "llm_type": llm_type,
                                    "model": model,
                                    "text": text,
                                    "context": context,
                                    "current_index": index,
                                    "system": ref(result[0]["content"]),
                                    "roles": [m["role"] for m in result],
                                    "user": result[1]["content"],
                                    "effective_context": manager.get_effective_context_texts(
                                        text, context, llm_type, model, current_index=index
                                    ),
                                    "cache_context": manager.get_effective_cache_context_texts(
                                        text, context, llm_type, model, current_index=index
                                    ),
                                }
                            )
    return {"texts": texts, "cases": cases, "messages": messages, "custom": custom_prompt_case()}


def custom_prompt_case() -> dict:
    """自訂 prompt、模板檔載入、重置與設定檔寫出格式。"""
    config_dir = Path(tempfile.mkdtemp(prefix="golden-custom-"))
    templates = config_dir / "prompt_templates"
    templates.mkdir()
    (templates / "anime_template.json").write_text(
        json.dumps({"openai": "ANIME TEMPLATE"}, ensure_ascii=False), encoding="utf-8"
    )
    manager = PromptManager(config_file=str(config_dir / "prompt_config.json"))
    result = {"after_load": {"anime_openai": manager.get_prompt("openai", "anime", "standard")}}
    manager.set_prompt("CUSTOM ONE\n", "openai", "adult")
    manager.set_prompt("CUSTOM TWO", "openai", "adult")
    result["after_set"] = {
        "adult_openai": manager.get_prompt("openai", "adult", "literal"),
        "adult_google": manager.get_prompt("google", "adult", "standard"),
        "version": manager.get_prompt_version("openai", "adult", "standard"),
    }
    manager.reset_to_default("openai", "adult")
    result["after_reset"] = {"adult_openai": md5(manager.get_prompt("openai", "adult", "standard"))}
    config = json.loads((config_dir / "prompt_config.json").read_text(encoding="utf-8"))
    config.pop("last_updated", None)
    for history in config.get("version_history", {}).values():
        for entries in history.values():
            for entry in entries:
                entry.pop("timestamp", None)
    result["config"] = config
    result["adult_template"] = (templates / "adult_template.json").read_text(encoding="utf-8")
    return result


def default_prompts_asset() -> dict:
    manager = new_prompt_manager("日文→繁體中文", True)
    return manager._get_default_prompts()


# ─── Config ─────────────────────────────────────────────────


def config_cases() -> dict:
    """各設定檔的預設內容原文（app 的 last_update 以固定值取代）。"""
    from srt_translator.core.config import ConfigManager

    config_dir = Path(tempfile.mkdtemp(prefix="golden-defaults-"))
    files = {}
    for config_type in ["app", "user", "model", "prompt", "file", "cache", "theme"]:
        manager = ConfigManager(config_type, config_dir=str(config_dir))
        path = Path(manager.get_config_path())
        text = path.read_text(encoding="utf-8")
        if config_type == "app":
            data = json.loads(text)
            data["last_update"] = "FIXED"
            text = json.dumps(data, ensure_ascii=False, indent=4)
        files[path.name] = text
    user = ConfigManager("user", config_dir=str(config_dir))
    user.set_value("translation.batch_size", 5)
    user.set_value("llm_type.nested", 1)
    files["user_after_set"] = (config_dir / "user_settings.json").read_text(encoding="utf-8")
    return files


# ─── Cache ──────────────────────────────────────────────────


def cache_cases() -> dict:
    contexts = [[], ["", "  "], ["前の文", "こんにちは", "次の文"], [" 日本 ", "ab"], ["[CURRENT_INDEX]1", "a", "b"]]
    with tempfile.TemporaryDirectory() as tmp:
        cache = CacheManager(str(Path(tmp) / "c.db"))
        hashes = [{"context": c, "hash": cache._compute_context_hash(tuple(c))} for c in contexts]
        cache.store_translation("こんにちは", "你好", contexts[2], "model-x", "standard", "abcd1234")
        with sqlite3.connect(str(Path(tmp) / "c.db")) as conn:
            schema = sorted(row[0] for row in conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
            rows = [
                list(r)
                for r in conn.execute(
                    "SELECT source_text, target_text, context_hash, model_name, style, prompt_version, usage_count FROM translations"
                )
            ]
    return {"hashes": hashes, "schema": schema, "rows": rows}


STALE: list[str] = []
CHECK_ONLY = False


def read_existing(path: Path) -> str | None:
    if not path.exists():
        return None
    raw = path.read_bytes()
    return (gzip.decompress(raw) if path.suffix == ".gz" else raw).decode("utf-8")


def write(path: Path, data: object) -> None:
    """寫出 golden；`--check` 模式下只比對內容（gzip 以解壓後文字比對，避免 zlib 版本差異誤報）。"""
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if CHECK_ONLY:
        if read_existing(path) != text:
            STALE.append(str(path.relative_to(REPO)))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        path.write_text(text, encoding="utf-8")
    print(f"寫入 {path.relative_to(REPO)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--local", action="store_true", help="另以 data/*.srt（gitignored）產生本地 golden")
    parser.add_argument("--check", action="store_true", help="只檢查 golden 是否與 Python 目前行為一致（CI 用）")
    args = parser.parse_args()
    global CHECK_ONLY
    CHECK_ONLY = args.check

    write(GOLDEN_DIR / "post_processor.json", post_processor_cases())
    write(GOLDEN_DIR / "japanese.json", japanese_cases())
    write(GOLDEN_DIR / "normalize.json", normalize_cases())
    write(GOLDEN_DIR / "glossary.json", glossary_cases())
    fixture_paths = sorted(p for p in FIXTURES.glob("*.srt") if p.name != "very_large.srt")
    fixture_paths += sorted((FIXTURES / "batch").glob("*.srt"))
    write(GOLDEN_DIR / "srt_files.json", srt_cases(fixture_paths))
    write(GOLDEN_DIR / "prompt.json.gz", prompt_cases())
    write(GOLDEN_DIR / "cache.json", cache_cases())
    write(GOLDEN_DIR / "config.json", config_cases())
    write(PROMPT_ASSET, default_prompts_asset())

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

    if STALE:
        print("golden 已過期（Python 行為已變更），請執行 rust/tools/gen_golden.py 並同步 Rust 實作：")
        for path in STALE:
            print(f"  - {path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
