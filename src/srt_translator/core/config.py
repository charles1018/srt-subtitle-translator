import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from srt_translator.utils.logging_config import setup_logger

# 使用集中化日誌配置
logger = setup_logger(__name__, "config_manager.log")


class ConfigManager:
    """配置管理器，統一管理系統的各種配置"""

    # 類變量，儲存已建立的配置管理器實例（單例模式）
    _instances: Dict[str, "ConfigManager"] = {}

    @classmethod
    def get_instance(cls, config_type: str = "app") -> "ConfigManager":
        """獲取配置管理器實例（單例模式）

        參數:
            config_type: 配置類型，用於區分不同的配置管理器實例

        回傳:
            配置管理器實例
        """
        if config_type not in cls._instances:
            cls._instances[config_type] = ConfigManager(config_type)
        return cls._instances[config_type]

    def __init__(self, config_type: str = "app"):
        """初始化配置管理器

        參數:
            config_type: 配置類型，影響配置檔案的路徑和預設值
        """
        self.config_type = config_type
        env_config_dir = os.environ.get("CONFIG_DIR", "").strip()
        self.config_dir = env_config_dir or "config"

        # 確保配置目錄存在
        os.makedirs(self.config_dir, exist_ok=True)

        # 設定配置檔案路徑
        self.config_paths = {
            "app": os.path.join(self.config_dir, "app_config.json"),
            "user": os.path.join(self.config_dir, "user_settings.json"),
            "model": os.path.join(self.config_dir, "model_config.json"),
            "prompt": os.path.join(self.config_dir, "prompt_config.json"),
            "file": os.path.join(self.config_dir, "file_handler_config.json"),
            "cache": os.path.join(self.config_dir, "cache_config.json"),
            "theme": os.path.join(self.config_dir, "theme_settings.json"),
        }

        # 設定預設配置值
        self.default_configs = self._get_default_configs()

        # 先初始化監聽器列表，避免在 load_config 呼叫儲存時未定義 listeners
        self.listeners = []

        # 載入配置
        self.configs = {}
        self.load_config()

        logger.info(f"配置管理器初始化完成: {config_type}")

    def _get_default_configs(self) -> Dict[str, Dict[str, Any]]:
        """獲取預設配置值

        回傳:
            包含各類型預設配置的字典
        """
        return {
            "app": {
                "version": "1.0.0",
                "debug_mode": False,
                "data_dir": "data",
                "checkpoints_dir": "data/checkpoints",
                "logs_dir": "logs",
                "cache_expiry": 30,  # 天數
                "last_update": datetime.now().isoformat(),
            },
            "user": {
                "source_lang": "日文",
                "target_lang": "繁體中文",
                "llm_type": "ollama",
                "model_name": "",
                "parallel_requests": 3,
                "display_mode": "雙語對照",
                "theme": "default",
                "play_sound": True,
                "auto_save": True,
                "last_directory": "",
            },
            "model": {
                "ollama_url": "http://localhost:11434",
                "default_ollama_model": "llama3",
                "cache_expiry": 600,  # 秒數
                "connect_timeout": 5,
                "request_timeout": 10,
                "model_patterns": [
                    "llama",
                    "mixtral",
                    "aya",
                    "yi",
                    "qwen",
                    "solar",
                    "mistral",
                    "openchat",
                    "neural",
                    "phi",
                    "stable",
                    "dolphin",
                    "vicuna",
                    "zephyr",
                    "gemma",
                    "deepseek",
                ],
                "default_providers": ["ollama", "openai"],
                "translation_capability_weight": {"translation": 0.7, "multilingual": 0.2, "context_handling": 0.1},
            },
            "prompt": {
                "current_content_type": "general",
                "current_style": "standard",
                "current_language_pair": "日文→繁體中文",
                "custom_prompts": {},
                "version_history": {},
            },
            "file": {
                "lang_suffix": {
                    "繁體中文": ".zh_tw",
                    "簡體中文": ".zh_cn",
                    "英文": ".en",
                    "日文": ".jp",
                    "韓文": ".kr",
                    "法文": ".fr",
                    "德文": ".de",
                    "西班牙文": ".es",
                    "俄文": ".ru",
                },
                "supported_formats": [
                    (".srt", "SRT字幕檔"),
                    (".vtt", "WebVTT字幕檔"),
                    (".ass", "ASS字幕檔"),
                    (".ssa", "SSA字幕檔"),
                    (".sub", "SUB字幕檔"),
                ],
                "batch_settings": {
                    "name_pattern": "{filename}_{language}{ext}",
                    "overwrite_mode": "ask",
                    "output_directory": "",
                    "preserve_folder_structure": True,
                },
            },
            "cache": {"db_path": "data/translation_cache.db", "max_memory_cache": 1000, "auto_cleanup_days": 30},
            "theme": {
                "colors": {
                    "primary": "#3498db",
                    "secondary": "#2ecc71",
                    "background": "#f0f0f0",
                    "text": "#333333",
                    "accent": "#e74c3c",
                    "button": "#3498db",
                    "button_hover": "#2980b9",
                },
                "font_size": "medium",
                "font_family": "Default",
            },
        }

    def load_config(self) -> None:
        """載入配置檔案，如果檔案不存在則使用預設值"""
        if self.config_type == "all":
            # 載入所有配置
            for config_type in self.config_paths.keys():
                self._load_specific_config(config_type)
        else:
            # 載入特定配置
            self._load_specific_config(self.config_type)

    def _load_specific_config(self, config_type: str) -> None:
        """載入特定類型的配置

        參數:
            config_type: 配置類型
        """
        config_path = self.config_paths.get(config_type)
        if not config_path:
            logger.warning(f"未知的配置類型: {config_type}")
            return

        # 取得預設配置（深拷貝避免修改預設值）
        default_config = copy.deepcopy(self.default_configs.get(config_type, {}))

        try:
            if os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as f:
                    loaded_config = json.load(f)

                # 將預設配置與載入的配置合併
                merged_config = self._merge_configs(default_config, loaded_config)
                self.configs[config_type] = merged_config
                logger.debug(f"已載入配置: {config_path}")
            else:
                # 如果檔案不存在，使用預設配置並儲存
                self.configs[config_type] = default_config
                self._save_specific_config(config_type)
                logger.info(f"已建立預設配置: {config_path}")
        except Exception as e:
            logger.error(f"載入配置失敗 {config_path}: {e!s}")
            # 使用預設配置
            self.configs[config_type] = default_config

    def _merge_configs(self, default_config: Dict[str, Any], loaded_config: Dict[str, Any]) -> Dict[str, Any]:
        """合併預設配置和載入的配置，確保所有必要的配置項都存在

        參數:
            default_config: 預設配置
            loaded_config: 從檔案載入的配置

        回傳:
            合併後的配置
        """
        result = copy.deepcopy(default_config)

        # 遞迴合併配置
        def merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> None:
            for key, value in override.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    # 遞迴合併嵌套字典
                    merge_dict(base[key], value)
                else:
                    # 直接覆蓋非字典值或新增不存在的項目
                    base[key] = value

        merge_dict(result, loaded_config)
        return result

    def save_config(self) -> bool:
        """儲存當前配置

        回傳:
            是否儲存成功
        """
        if self.config_type == "all":
            # 儲存所有配置
            success = True
            for config_type in self.configs.keys():
                if not self._save_specific_config(config_type):
                    success = False
            return success
        else:
            # 儲存特定配置
            return self._save_specific_config(self.config_type)

    def _save_specific_config(self, config_type: str) -> bool:
        """儲存特定類型的配置

        參數:
            config_type: 配置類型

        回傳:
            是否儲存成功
        """
        config_path = self.config_paths.get(config_type)
        if not config_path:
            logger.warning(f"儲存失敗：未知的配置類型 {config_type}")
            return False

        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(config_path), exist_ok=True)

            # 取得要儲存的配置
            config = self.configs.get(config_type, self.default_configs.get(config_type, {}))

            # 更新最後修改時間（僅適用於某些類型）
            if "last_update" in config:
                config["last_update"] = datetime.now().isoformat()

            # 儲存到檔案
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)

            logger.debug(f"已儲存配置: {config_path}")

            # 通知監聽器
            for listener in self.listeners:
                try:
                    listener(config_type, config)
                except Exception as e:
                    logger.error(f"通知配置監聽器時發生錯誤: {e!s}")

            return True
        except Exception as e:
            logger.error(f"儲存配置失敗 {config_path}: {e!s}")
            return False

    def get_config(self, config_type: str = None) -> Dict[str, Any]:
        """獲取完整配置

        參數:
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            配置字典，若不存在則回傳空字典
        """
        config_type = config_type or self.config_type

        if config_type == "all":
            # 回傳合併後的所有配置
            all_configs = {}
            for typ, config in self.configs.items():
                all_configs[typ] = copy.deepcopy(config)
            return all_configs

        return copy.deepcopy(self.configs.get(config_type, {}))

    def get_value(self, key: str, config_type: str = None, default: Any = None) -> Any:
        """獲取特定配置值

        參數:
            key: 配置鍵，支援點號分隔的路徑（如 "theme.colors.primary"）
            config_type: 配置類型，若為None則使用當前實例的類型
            default: 若配置不存在時的預設回傳值

        回傳:
            配置值，若不存在則回傳 default
        """
        config_type = config_type or self.config_type
        # 如果 config_type 不是字串，則使用預設值
        if not isinstance(config_type, str):
            config_type = self.config_type

        if config_type not in self.configs:
            return default

        # 支援點號分隔的路徑
        keys = key.split(".")
        value = self.configs[config_type]

        try:
            for k in keys:
                value = value[k]
            return copy.deepcopy(value)
        except (KeyError, TypeError):
            return default

    def set_value(self, key: str, value: Any, config_type: str = None, auto_save: bool = True) -> bool:
        """設置特定配置值

        參數:
            key: 配置鍵，支援點號分隔的路徑
            value: 配置值
            config_type: 配置類型，若為None則使用當前實例的類型
            auto_save: 是否自動儲存配置

        回傳:
            是否設置成功
        """
        config_type = config_type or self.config_type

        if config_type not in self.configs:
            if config_type in self.default_configs:
                self.configs[config_type] = copy.deepcopy(self.default_configs[config_type])
            else:
                logger.warning(f"設置失敗：未知的配置類型 {config_type}")
                return False

        # 支援點號分隔的路徑
        keys = key.split(".")
        config = self.configs[config_type]

        # 循環到倒數第二個鍵
        parent = config
        for i in range(len(keys) - 1):
            k = keys[i]
            if k not in parent or not isinstance(parent[k], dict):
                parent[k] = {}
            parent = parent[k]

        # 設置最後一個鍵對應的值
        parent[keys[-1]] = value

        # 是否自動儲存
        if auto_save:
            return self._save_specific_config(config_type)

        return True

    def add_listener(self, listener_func: callable) -> None:
        """添加配置變更監聽器

        參數:
            listener_func: 監聽器函數，接收參數 (config_type, config)
        """
        if listener_func not in self.listeners:
            self.listeners.append(listener_func)

    def remove_listener(self, listener_func: callable) -> None:
        """移除配置變更監聽器

        參數:
            listener_func: 要移除的監聽器函數
        """
        if listener_func in self.listeners:
            self.listeners.remove(listener_func)

    def reset_to_default(self, config_type: str = None, keys: List[str] = None) -> bool:
        """重置配置為預設值

        參數:
            config_type: 配置類型，若為None則使用當前實例的類型
            keys: 要重置的特定鍵列表，若為None則重置整個配置

        回傳:
            是否重置成功
        """
        config_type = config_type or self.config_type

        if config_type not in self.default_configs:
            logger.warning(f"重置失敗：無預設配置類型 {config_type}")
            return False

        if keys is None:
            # 重置整個配置
            self.configs[config_type] = copy.deepcopy(self.default_configs[config_type])
        else:
            # 只重置特定鍵
            for key in keys:
                default_value = self.get_value(key, "default_" + config_type)
                self.set_value(key, default_value, config_type, auto_save=False)

        # 儲存變更
        return self._save_specific_config(config_type)

    def export_config(self, export_path: str, config_type: str = None) -> bool:
        """匯出配置到指定路徑

        參數:
            export_path: 匯出路徑
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            是否匯出成功
        """
        config_type = config_type or self.config_type

        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(export_path), exist_ok=True)

            # 準備匯出資料
            export_data = {
                "metadata": {"exported_at": datetime.now().isoformat(), "config_type": config_type, "version": "1.0.0"},
                "config": self.get_config(config_type),
            }

            # 寫入檔案
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)

            logger.info(f"已匯出配置至: {export_path}")
            return True
        except Exception as e:
            logger.error(f"匯出配置失敗: {e!s}")
            return False

    def import_config(self, import_path: str, config_type: str = None, merge: bool = True) -> bool:
        """從檔案匯入配置

        參數:
            import_path: 匯入路徑
            config_type: 配置類型，若為None則使用當前實例的類型
            merge: 是否合併現有配置，若為False則完全替換

        回傳:
            是否匯入成功
        """
        config_type = config_type or self.config_type

        try:
            with open(import_path, encoding="utf-8") as f:
                import_data = json.load(f)

            # 驗證匯入資料格式
            if "config" not in import_data:
                logger.warning(f"匯入失敗：無效的配置檔案格式 {import_path}")
                return False

            imported_type = import_data.get("metadata", {}).get("config_type", config_type)
            imported_config = import_data["config"]

            if merge:
                # 合併現有配置
                current_config = self.get_config(config_type)
                merged_config = self._merge_configs(current_config, imported_config)
                self.configs[imported_type] = merged_config
            else:
                # 完全替換
                self.configs[imported_type] = imported_config

            # 儲存變更
            success = self._save_specific_config(imported_type)

            if success:
                logger.info(f"已從 {import_path} 匯入配置")

            return success
        except Exception as e:
            logger.error(f"匯入配置失敗: {e!s}")
            return False

    def validate_config(self, config_type: str = None) -> Dict[str, List[str]]:
        """驗證配置是否符合預期格式和規則

        參數:
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            錯誤訊息字典，鍵為配置路徑，值為錯誤訊息列表，空字典表示驗證通過
        """
        config_type = config_type or self.config_type
        errors = {}

        # 配置類型特定的驗證規則
        validators = {
            "app": self._validate_app_config,
            "user": self._validate_user_config,
            "model": self._validate_model_config,
            "prompt": self._validate_prompt_config,
            "file": self._validate_file_config,
            "cache": self._validate_cache_config,
            "theme": self._validate_theme_config,
        }

        # 執行驗證
        if config_type in validators:
            validator = validators[config_type]
            config = self.get_config(config_type)
            validator_errors = validator(config)
            if validator_errors:
                errors.update(validator_errors)
        elif config_type == "all":
            # 驗證所有配置
            for typ in self.configs.keys():
                if typ in validators:
                    validator = validators[typ]
                    config = self.get_config(typ)
                    validator_errors = validator(config)
                    if validator_errors:
                        for key, msgs in validator_errors.items():
                            errors[f"{typ}.{key}"] = msgs
        else:
            errors["config_type"] = [f"未知的配置類型: {config_type}"]

        return errors

    def _validate_app_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證應用程式配置"""
        errors = {}

        # 版本號格式
        version = config.get("version", "")
        if not isinstance(version, str) or not re.match(r"^\d+\.\d+\.\d+$", version):
            errors["version"] = ["版本號必須符合 'x.y.z' 格式"]

        # 目錄路徑
        for path_key in ["data_dir", "checkpoints_dir", "logs_dir"]:
            path = config.get(path_key, "")
            if not isinstance(path, str) or not path:
                errors[path_key] = ["必須為有效的目錄路徑"]

        # 快取過期時間
        cache_expiry = config.get("cache_expiry", 0)
        if not isinstance(cache_expiry, int) or cache_expiry <= 0:
            errors["cache_expiry"] = ["快取過期時間必須為正整數"]

        return errors

    def _validate_user_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證使用者配置"""
        errors = {}

        # 語言設定
        valid_langs = ["日文", "英文", "韓文", "簡體中文", "繁體中文", "法文", "德文", "西班牙文", "俄文"]
        source_lang = config.get("source_lang", "")
        target_lang = config.get("target_lang", "")

        if source_lang not in valid_langs:
            errors["source_lang"] = [f"無效的來源語言，有效選項: {', '.join(valid_langs)}"]

        if target_lang not in valid_langs:
            errors["target_lang"] = [f"無效的目標語言，有效選項: {', '.join(valid_langs)}"]

        # LLM 類型
        llm_type = config.get("llm_type", "")
        if llm_type not in ["ollama", "openai"]:
            errors["llm_type"] = ["無效的 LLM 類型，有效選項: ollama, openai"]

        # 並行請求數
        parallel = config.get("parallel_requests", 0)
        if not isinstance(parallel, int) or parallel <= 0 or parallel > 50:
            errors["parallel_requests"] = ["並行請求數必須為 1-50 的整數"]

        # 顯示模式
        display_mode = config.get("display_mode", "")
        valid_modes = ["雙語對照", "僅顯示翻譯", "翻譯在上", "原文在上"]
        if display_mode not in valid_modes:
            errors["display_mode"] = [f"無效的顯示模式，有效選項: {', '.join(valid_modes)}"]

        return errors

    def _validate_model_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證模型配置"""
        errors = {}

        # Ollama URL
        ollama_url = config.get("ollama_url", "")
        if not isinstance(ollama_url, str) or not (
            ollama_url.startswith("http://") or ollama_url.startswith("https://")
        ):
            errors["ollama_url"] = ["必須為有效的 HTTP/HTTPS URL"]

        # 逾時設定
        for timeout_key in ["connect_timeout", "request_timeout"]:
            timeout = config.get(timeout_key, 0)
            if not isinstance(timeout, int) or timeout <= 0 or timeout > 300:
                errors[timeout_key] = ["逾時設定必須為 1-300 的整數（秒）"]

        # 模型模式列表
        model_patterns = config.get("model_patterns", [])
        if not isinstance(model_patterns, list) or not all(isinstance(p, str) for p in model_patterns):
            errors["model_patterns"] = ["必須為字串列表"]

        # 能力權重
        weights = config.get("translation_capability_weight", {})
        if not isinstance(weights, dict):
            errors["translation_capability_weight"] = ["必須為字典格式"]
        else:
            total = sum(weights.values())
            if abs(total - 1.0) > 0.01:
                errors["translation_capability_weight"] = [f"權重總和必須為 1.0，目前為 {total}"]

        return errors

    def _validate_prompt_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證提示詞配置"""
        errors = {}

        # 內容類型
        content_type = config.get("current_content_type", "")
        if content_type not in ["general", "adult", "anime", "movie", "english_drama"]:
            errors["current_content_type"] = ["無效的內容類型，有效選項: general, adult, anime, movie, english_drama"]

        # 風格
        style = config.get("current_style", "")
        if style not in ["standard", "literal", "localized", "specialized"]:
            errors["current_style"] = ["無效的翻譯風格，有效選項: standard, literal, localized, specialized"]

        # 語言對
        language_pair = config.get("current_language_pair", "")
        valid_lang_pairs = [
            "日文→繁體中文",
            "英文→繁體中文",
            "繁體中文→英文",
            "簡體中文→繁體中文",
            "韓文→繁體中文",
            "法文→繁體中文",
            "德文→繁體中文",
            "西班牙文→繁體中文",
            "俄文→繁體中文",
        ]
        if language_pair not in valid_lang_pairs:
            errors["current_language_pair"] = [f"無效的語言對，有效選項: {', '.join(valid_lang_pairs)}"]

        # 自訂提示詞結構
        custom_prompts = config.get("custom_prompts", {})
        if not isinstance(custom_prompts, dict):
            errors["custom_prompts"] = ["必須為字典格式"]
        else:
            for content_type, prompts in custom_prompts.items():
                if not isinstance(prompts, dict):
                    errors[f"custom_prompts.{content_type}"] = ["必須為字典格式"]

        return errors

    def _validate_file_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證檔案處理配置"""
        errors = {}

        # 語言後綴
        lang_suffix = config.get("lang_suffix", {})
        if not isinstance(lang_suffix, dict):
            errors["lang_suffix"] = ["必須為字典格式"]
        else:
            for lang, suffix in lang_suffix.items():
                if not isinstance(suffix, str) or not suffix.startswith("."):
                    errors[f"lang_suffix.{lang}"] = ["後綴必須為字串並以 '.' 開頭"]

        # 支援的檔案格式
        formats = config.get("supported_formats", [])
        if not isinstance(formats, list):
            errors["supported_formats"] = ["必須為列表格式"]
        else:
            for i, fmt in enumerate(formats):
                if (
                    not isinstance(fmt, (list, tuple))
                    or len(fmt) != 2
                    or not isinstance(fmt[0], str)
                    or not isinstance(fmt[1], str)
                ):
                    errors[f"supported_formats[{i}]"] = ["必須為 (副檔名, 描述) 的二元組"]

        # 批次設定
        batch_settings = config.get("batch_settings", {})
        if not isinstance(batch_settings, dict):
            errors["batch_settings"] = ["必須為字典格式"]
        else:
            if "name_pattern" in batch_settings:
                pattern = batch_settings["name_pattern"]
                if not isinstance(pattern, str) or not any(x in pattern for x in ["{filename}", "{language}", "{ext}"]):
                    errors["batch_settings.name_pattern"] = ["必須包含至少一個 {filename}, {language}, {ext} 預留位置"]

            if "overwrite_mode" in batch_settings:
                mode = batch_settings["overwrite_mode"]
                if mode not in ["ask", "overwrite", "rename", "skip"]:
                    errors["batch_settings.overwrite_mode"] = ["必須為 ask, overwrite, rename, skip 其中之一"]

        return errors

    def _validate_cache_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證快取配置"""
        errors = {}

        # 資料庫路徑
        db_path = config.get("db_path", "")
        if not isinstance(db_path, str) or not db_path:
            errors["db_path"] = ["必須為有效的檔案路徑"]

        # 記憶體快取大小
        max_cache = config.get("max_memory_cache", 0)
        if not isinstance(max_cache, int) or max_cache <= 0:
            errors["max_memory_cache"] = ["必須為正整數"]

        # 自動清理天數
        cleanup_days = config.get("auto_cleanup_days", 0)
        if not isinstance(cleanup_days, int) or cleanup_days <= 0:
            errors["auto_cleanup_days"] = ["必須為正整數"]

        return errors

    def _validate_theme_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """驗證主題配置"""
        errors = {}

        # 色彩配置
        colors = config.get("colors", {})
        if not isinstance(colors, dict):
            errors["colors"] = ["必須為字典格式"]
        else:
            for key, color in colors.items():
                if not isinstance(color, str) or not color.startswith("#") or not re.match(r"^#[0-9A-Fa-f]{6}$", color):
                    errors[f"colors.{key}"] = ["必須為有效的十六進位色碼 (#RRGGBB)"]

        # 字型大小
        font_size = config.get("font_size", "")
        if font_size not in ["small", "medium", "large"]:
            errors["font_size"] = ["必須為 small, medium, large 其中之一"]

        return errors

    def create_backup(self, config_type: str = None) -> Optional[str]:
        """建立配置備份

        參數:
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            備份檔案路徑，若失敗則回傳 None
        """
        config_type = config_type or self.config_type

        try:
            # 確保備份目錄存在
            backup_dir = os.path.join(self.config_dir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            # 建立備份檔案名稱
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"{config_type}_config_{timestamp}.json")

            # 導出配置到備份檔案
            if self.export_config(backup_file, config_type):
                logger.info(f"已建立配置備份: {backup_file}")
                return backup_file

            return None
        except Exception as e:
            logger.error(f"建立配置備份失敗: {e!s}")
            return None

    def restore_backup(self, backup_path: str, config_type: str = None) -> bool:
        """從備份還原配置

        參數:
            backup_path: 備份檔案路徑
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            是否還原成功
        """
        config_type = config_type or self.config_type

        try:
            # 驗證備份檔案
            if not os.path.exists(backup_path):
                logger.warning(f"還原失敗：備份檔案不存在 {backup_path}")
                return False

            # 先建立當前配置的備份
            self.create_backup(config_type)

            # 匯入備份
            return self.import_config(backup_path, config_type, merge=False)

        except Exception as e:
            logger.error(f"還原配置備份失敗: {e!s}")
            return False

    def list_backups(self, config_type: str = None) -> List[Dict[str, Any]]:
        """列出可用的配置備份

        參數:
            config_type: 配置類型，若為None則列出所有備份

        回傳:
            備份資訊列表，每個項目包含路徑、類型、時間等資訊
        """
        try:
            backup_dir = os.path.join(self.config_dir, "backups")
            if not os.path.exists(backup_dir):
                return []

            backups = []

            # 搜尋備份檔案
            backup_pattern = f"{config_type}_config_*.json" if config_type else "*_config_*.json"
            for file in Path(backup_dir).glob(backup_pattern):
                try:
                    with open(file, encoding="utf-8") as f:
                        data = json.load(f)

                    metadata = data.get("metadata", {})

                    backup_info = {
                        "path": str(file),
                        "filename": file.name,
                        "config_type": metadata.get("config_type", "unknown"),
                        "exported_at": metadata.get("exported_at", "unknown"),
                        "size": file.stat().st_size,
                        "last_modified": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
                    }

                    backups.append(backup_info)
                except Exception as e:
                    logger.warning(f"讀取備份檔案 {file} 失敗: {e!s}")

            # 按時間排序
            backups.sort(key=lambda x: x["exported_at"], reverse=True)
            return backups

        except Exception as e:
            logger.error(f"列出配置備份失敗: {e!s}")
            return []

    def is_config_valid(self, config_type: str = None) -> bool:
        """檢查配置是否有效

        參數:
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            配置是否有效
        """
        errors = self.validate_config(config_type)
        return len(errors) == 0

    def get_config_path(self, config_type: str = None) -> str:
        """獲取配置檔案路徑

        參數:
            config_type: 配置類型，若為None則使用當前實例的類型

        回傳:
            配置檔案路徑
        """
        config_type = config_type or self.config_type
        return self.config_paths.get(config_type, "")


# 全域函數：快速存取配置
def get_config(config_type: str = "app", key: str = None, default: Any = None) -> Any:
    """全域函數：快速存取配置

    參數:
        config_type: 配置類型
        key: 配置鍵，若為None則回傳整個配置
        default: 若配置不存在時的預設回傳值

    回傳:
        配置值或整個配置字典
    """
    manager = ConfigManager.get_instance(config_type)
    if key is None:
        return manager.get_config()
    return manager.get_value(key, default=default)


def set_config(config_type: str, key: str, value: Any, auto_save: bool = True) -> bool:
    """全域函數：快速設置配置

    參數:
        config_type: 配置類型
        key: 配置鍵
        value: 配置值
        auto_save: 是否自動儲存配置

    回傳:
        是否設置成功
    """
    manager = ConfigManager.get_instance(config_type)
    return manager.set_value(key, value, auto_save=auto_save)


# 測試程式碼
if __name__ == "__main__":
    # 設定控制台日誌
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(console_handler)

    print("===== 配置管理器測試 =====")

    # 初始化配置管理器
    config_manager = ConfigManager.get_instance("app")
    user_config = ConfigManager.get_instance("user")

    # 設置並獲取配置
    config_manager.set_value("version", "1.1.0")
    print(f"應用程式版本: {config_manager.get_value('version')}")

    # 設置並獲取巢狀配置
    user_config.set_value("theme.colors.primary", "#FF5733")
    print(f"主題主色: {user_config.get_value('theme.colors.primary')}")

    # 驗證配置
    errors = user_config.validate_config()
    if errors:
        print("配置驗證失敗:")
        for key, msgs in errors.items():
            print(f"  {key}: {', '.join(msgs)}")
    else:
        print("配置驗證通過")

    # 測試備份和還原
    backup_path = config_manager.create_backup()
    if backup_path:
        print(f"已建立配置備份: {backup_path}")

    # 列出備份
    backups = config_manager.list_backups()
    print(f"找到 {len(backups)} 個備份檔案")

    # 全域函數測試
    app_debug = get_config("app", "debug_mode", False)
    print(f"應用程式除錯模式: {app_debug}")

    set_config("app", "debug_mode", True)
    app_debug = get_config("app", "debug_mode", False)
    print(f"更新後的除錯模式: {app_debug}")

    print("===== 測試完成 =====")
