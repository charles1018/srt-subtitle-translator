#!/usr/bin/env python
"""實機對照工具（Python 版）：與 `cargo run --example live_client` 相同參數與上下文規則。

需在隔離的工作目錄執行（TranslationClient 會在 cwd 建立 data/ 快取），並以 CONFIG_DIR 指定設定目錄：

    CONFIG_DIR=<dir> python rust/tools/live_client.py <srt> <content_type> <language_pair> <model> <out.json> [concurrency] [netflix]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from srt_translator.tools.srt_tools import _open_srt
from srt_translator.translation.client import TranslationClient


async def run(argv: list[str]) -> None:
    srt, content_type, language_pair, model, out = argv[:5]
    concurrency = int(argv[5]) if len(argv) > 5 else 1
    netflix = len(argv) > 6 and argv[6] == "netflix"

    client = TranslationClient("llamacpp", "http://127.0.0.1:8080", netflix_style_config={"enabled": netflix})
    client.prompt_manager.set_content_type(content_type)
    client.prompt_manager.set_language_pair(language_pair)

    texts = [sub.text for sub in _open_srt(Path(srt))]
    items = []
    for i, text in enumerate(texts):
        start = max(0, i - 1)
        items.append((text, texts[start : i + 2], i - start))

    started = time.time()
    async with client:
        if concurrency <= 1:
            translations = []
            for text, context, idx in items:
                translations.append(
                    await client.translate_with_retry(text, context, model, current_index=idx, use_cache=False)
                )
        else:
            translations = await client.translate_batch(
                [(t, c) for t, c, _ in items],
                model,
                concurrent_limit=concurrency,
                current_indices=[i for _, _, i in items],
                use_cache=False,
            )
    elapsed = time.time() - started
    Path(out).write_text(
        json.dumps(
            {
                "elapsed": elapsed,
                "translations": translations,
                "total_tokens": client.metrics.total_tokens,
                "failed": client.metrics.failed_requests,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Python: {len(translations)} 條，{elapsed:.1f} 秒，失敗 {client.metrics.failed_requests}")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1:]))
