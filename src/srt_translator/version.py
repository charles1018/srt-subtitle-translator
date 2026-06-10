"""集中管理應用程式版本資訊。"""

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "srt-subtitle-translator"
APP_VERSION = "1.3.0"


def get_app_version() -> str:
    """取得目前應用程式版本。

    優先使用已安裝套件的 distribution metadata；
    若目前直接從 source tree 執行且尚未安裝，則退回 repo 內建版本常數。
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return APP_VERSION
