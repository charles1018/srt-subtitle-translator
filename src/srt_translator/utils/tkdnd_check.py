"""tkinterdnd2 可用性檢測模組。

python-build-standalone 的 tcl/tk 執行緒初始化與 X11 不相容，
會導致載入 tkdnd 原生庫時 process abort（無法用 try/except 捕捉）。
此模組透過子程序預先測試，在模組載入時決定是否啟用拖放功能。
"""

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

TKDND_AVAILABLE = False


def _check_tkdnd_available() -> bool:
    """在子程序中測試 tkinterdnd2 是否能正常運作。"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from tkinterdnd2 import TkinterDnD; root = TkinterDnD.Tk(); root.destroy()"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


try:
    import tkinterdnd2  # noqa: F401

    if _check_tkdnd_available():
        TKDND_AVAILABLE = True
    else:
        logger.warning(
            "tkinterdnd2 因 X11/XCB 相容性問題無法使用，拖放功能已停用。"
            "這是 python-build-standalone 的已知問題，不影響其他功能。"
        )
except ImportError:
    pass
