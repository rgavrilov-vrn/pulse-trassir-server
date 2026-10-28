# logger.py
import logging
import os
from logging.handlers import RotatingFileHandler

import config

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
logger = logging.getLogger("camera_monitor")


def normalize_log_level(value):
    if not value:
        return logging.INFO

    level_name = str(value).upper()

    if level_name not in VALID_LOG_LEVELS:
        return logging.INFO

    return getattr(logging, level_name)


def apply_log_level(level_name):
    level = normalize_log_level(level_name)
    logger.setLevel(level)

    for handler in logger.handlers:
        handler.setLevel(level)

    logger.debug(
        "Уровень логирования изменён на %s"
        % logging.getLevelName(level)
    )


def init_logger(level_name=None):
    if not logger.handlers:
        log_directory = os.path.dirname(config.LOG_FILE)

        if log_directory and not os.path.exists(log_directory):
            os.makedirs(log_directory)

        handler = RotatingFileHandler(
            filename=config.LOG_FILE,
            mode="a",
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        handler.setFormatter(formatter)
        logger.addHandler(handler)

    apply_log_level(level_name or config.LOG_LEVEL)


def log_debug(message):
    logger.debug(message)


def log_info(message):
    logger.info(message)


def log_warning(message):
    logger.warning(message)


def log_error(message):
    logger.error(message)


def log_exception(message, error):
    logger.error("%s: %s" % (message, error), exc_info=True)
