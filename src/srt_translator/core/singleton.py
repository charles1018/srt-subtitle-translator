"""統一的單例模式實現

提供兩種方式實現單例：
1. SingletonMeta - 元類方式，適合簡單單例
2. SingletonMixin - 混入方式，適合需要 get_instance 參數的單例
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar


class SingletonMeta(type):
    """單例元類

    使用方式：
        class MyClass(metaclass=SingletonMeta):
            pass

    注意：使用此元類的類別會在第一次實例化時建立單例，
    後續所有實例化都會返回同一個實例。
    """

    _instances: ClassVar[dict[type, Any]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        """建立或返回單例實例"""
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
            return cls._instances[cls]

    def reset_instance(cls) -> None:
        """重置單例實例（僅用於測試）"""
        with cls._lock:
            if cls in cls._instances:
                del cls._instances[cls]


class SingletonMixin:
    """單例混入類別

    使用方式：
        class MyManager(SingletonMixin):
            def __init__(self, config_path: str):
                self.config_path = config_path

            @classmethod
            def get_instance(cls, config_path: Optional[str] = None) -> "MyManager":
                return cls._get_instance(config_path=config_path or "default.json")

    子類別需要實現 get_instance 類別方法，呼叫 _get_instance 傳入初始化參數。
    """

    _instance: ClassVar[Any | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def _get_instance(cls, **init_kwargs: Any) -> SingletonMixin:
        """內部方法：獲取或建立單例實例

        參數：
            **init_kwargs: 傳給 __init__ 的關鍵字參數

        回傳：
            單例實例
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(**init_kwargs)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置單例實例（僅用於測試）"""
        with cls._lock:
            cls._instance = None

    @classmethod
    def has_instance(cls) -> bool:
        """檢查是否已建立單例實例"""
        return cls._instance is not None


class KeyedSingletonMixin:
    """帶鍵值的單例混入類別

    用於需要根據不同參數建立不同單例的情況（如 ConfigManager 根據 config_type）。

    使用方式：
        class ConfigManager(KeyedSingletonMixin):
            @classmethod
            def get_instance(cls, config_type: str) -> "ConfigManager":
                return cls._get_keyed_instance(config_type, config_type=config_type)
    """

    _instances: ClassVar[dict[str, Any]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def _get_keyed_instance(cls, key: str, **init_kwargs: Any) -> KeyedSingletonMixin:
        """獲取或建立指定鍵值的單例實例

        參數：
            key: 用於識別實例的鍵值
            **init_kwargs: 傳給 __init__ 的關鍵字參數

        回傳：
            對應鍵值的單例實例
        """
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = cls(**init_kwargs)
            instance: KeyedSingletonMixin = cls._instances[key]
            return instance

    @classmethod
    def reset_instance(cls, key: str | None = None) -> None:
        """重置單例實例（僅用於測試）

        參數：
            key: 要重置的鍵值，若為 None 則重置所有實例
        """
        with cls._lock:
            if key is None:
                cls._instances.clear()
            elif key in cls._instances:
                del cls._instances[key]

    @classmethod
    def has_instance(cls, key: str) -> bool:
        """檢查指定鍵值是否已建立單例實例"""
        return key in cls._instances

    @classmethod
    def get_all_instances(cls) -> dict[str, Any]:
        """獲取所有已建立的單例實例"""
        return dict(cls._instances)
