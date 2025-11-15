"""工具模組

包含錯誤類別、日誌配置、進度追蹤器、輔助函數等。
"""

# 導出錯誤類別
from srt_translator.utils.errors import (
    APIKeyError,
    AppError,
    CacheError,
    ConfigError,
    FileError,
    ModelError,
    ModelNotFoundError,
    NetworkError,
    TimeoutError,
    TranslationError,
    ValidationError,
)

# 導出工具函數和類別
from srt_translator.utils.helpers import (
    # 本地化和國際化工具
    LocaleManager,
    # 快取工具
    MemoryCache,
    # 進度追蹤工具
    ProgressTracker,
    check_api_connection,
    # 網絡檢查工具
    check_internet_connection,
    check_python_packages,
    # 文本處理工具
    clean_text,
    compute_text_hash,
    detect_language,
    # 執行命令工具
    execute_command,
    format_datetime,
    # 時間和格式工具
    format_elapsed_time,
    # 錯誤處理工具
    format_exception,
    format_file_size,
    # 字幕處理工具
    format_srt_time,
    generate_unique_filename,
    get_language_name,
    # 系統信息工具
    get_system_info,
    is_command_available,
    is_valid_subtitle_file,
    parse_srt_time,
    safe_execute,
    split_sentences,
    standardize_language_code,
    truncate_text,
)

# 導出日誌配置
from srt_translator.utils.logging_config import setup_logger, setup_root_logger

__all__ = [
    # 錯誤類別
    'AppError',
    'ConfigError',
    'ModelError',
    'TranslationError',
    'FileError',
    'NetworkError',
    'APIKeyError',
    'ModelNotFoundError',
    'CacheError',
    'ValidationError',
    'TimeoutError',
    # 日誌配置
    'setup_logger',
    'setup_root_logger',
    # 錯誤處理工具
    'format_exception',
    'safe_execute',
    # 文本處理工具
    'clean_text',
    'detect_language',
    'standardize_language_code',
    'get_language_name',
    'compute_text_hash',
    'truncate_text',
    'split_sentences',
    # 字幕處理工具
    'format_srt_time',
    'parse_srt_time',
    'generate_unique_filename',
    'is_valid_subtitle_file',
    # 時間和格式工具
    'format_elapsed_time',
    'format_datetime',
    'format_file_size',
    # 進度追蹤工具
    'ProgressTracker',
    # 網絡檢查工具
    'check_internet_connection',
    'check_api_connection',
    # 系統信息工具
    'get_system_info',
    'check_python_packages',
    # 本地化和國際化工具
    'LocaleManager',
    # 快取工具
    'MemoryCache',
    # 執行命令工具
    'execute_command',
    'is_command_available'
]
