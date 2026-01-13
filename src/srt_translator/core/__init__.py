"""核心模組

包含配置管理、緩存管理、模型管理、提示詞管理等核心功能。
"""

from srt_translator.core.singleton import (
    KeyedSingletonMixin,
    SingletonMeta,
    SingletonMixin,
)

__all__ = [
    "KeyedSingletonMixin",
    "SingletonMeta",
    "SingletonMixin",
]
