# logger.py
# Восстановленная реализация по интерфейсу проекта.
import logging
import os
from logging.handlers import RotatingFileHandler

import config

_logger = None

def init_logger(log_level=None):
    global _logger
    level_name = log_level or config.LOG_LEVEL
    level = getattr(logging, level_name.upper(), logging.INFO)
    directory = os.path.dirname(config.LOG_FILE)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    handler = RotatingFileHandler(config.LOG_FILE, maxBytes=config.LOG_MAX_BYTES, backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    _logger = logging.getLogger("trassir_camera_monitor")
    _logger.setLevel(level)
    _logger.handlers.clear()
    _logger.addHandler(handler)
    return _logger

def apply_log_level(level_name):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.getLogger("trassir_camera_monitor").setLevel(level)

def _get_logger():
    global _logger
    if _logger is None:
        init_logger()
    return _logger

def log_debug(message):
    _get_logger().debug(message)

def log_info(message):
    _get_logger().info(message)

def log_error(message):
    _get_logger().error(message)
