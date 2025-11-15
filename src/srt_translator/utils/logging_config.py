"""日誌配置模組

集中管理專案的日誌配置，避免重複代碼。
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

# 全局日誌格式設定
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s"


def setup_logger(
    name: str,
    log_file: Optional[str] = None,
    level: int = logging.DEBUG,
    log_dir: str = 'logs'
) -> logging.Logger:
    """設定並返回日誌記錄器

    參數:
        name: 日誌記錄器名稱（通常使用 __name__）
        log_file: 日誌檔案名稱（相對於 log_dir）
        level: 日誌等級（預設 DEBUG）
        log_dir: 日誌目錄（預設 'logs'）

    回傳:
        配置好的日誌記錄器
    """
    # 確保日誌目錄存在
    os.makedirs(log_dir, exist_ok=True)

    # 獲取或創建日誌記錄器
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重複添加處理程序
    if not logger.handlers:
        if log_file:
            # 檔案處理程序（每日輪替）
            file_path = os.path.join(log_dir, log_file)
            handler = TimedRotatingFileHandler(
                filename=file_path,
                when='midnight',
                interval=1,
                backupCount=7,
                encoding='utf-8'
            )
        else:
            # 控制台處理程序
            handler = logging.StreamHandler()

        # 設定格式化器
        formatter = logging.Formatter(LOG_FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def setup_root_logger(log_file: str = 'app.log', level: int = logging.INFO):
    """設定根日誌記錄器

    參數:
        log_file: 根日誌檔案名稱
        level: 日誌等級
    """
    root_logger = logging.getLogger()

    # 避免重複配置
    if not root_logger.handlers:
        os.makedirs('logs', exist_ok=True)

        handler = TimedRotatingFileHandler(
            filename=f'logs/{log_file}',
            when='midnight',
            interval=1,
            backupCount=7,
            encoding='utf-8'
        )
        formatter = logging.Formatter(LOG_FORMAT)
        handler.setFormatter(formatter)

        root_logger.addHandler(handler)
        root_logger.setLevel(level)
