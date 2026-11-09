# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
import time
import sqlite3
import logging

from collections import deque
from logging.handlers import RotatingFileHandler

ROOT = r"C:\TRASSIR_Agent"
CONFIG_FILE = os.path.join(ROOT, "config.json")
DEBUG_LOG = os.path.join(ROOT, "logs", "queue_debug.log")
POLL_SECONDS = 5

# False: heartbeat не выводим, чтобы видеть реальные события.
# True: выводим также heartbeat.
SHOW_HEARTBEAT = False

# За проход смотрим последние записи.
# Это диагностика, а не гарантированный аудит всего потока.
READ_LIMIT = 300

# Ограничиваем объём памяти для защиты от повторного вывода.
SEEN_LIMIT = 3000

def dictionary_row_factory(cursor, values):
    """Преобразует строку SQLite в обычный словарь.

    cursor.description содержит имена столбцов.
    values содержит значения текущей строки.
    Обычный dict позволяет использовать Unicode-ключи в Python 2.7.
    """
    result = {}
    for index, column in enumerate(cursor.description):
        column_name = column[0]
        result[column_name] = values[index]
    return result

def resolve_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join(ROOT, path)

log_directory = os.path.dirname(DEBUG_LOG)
if not os.path.isdir(log_directory):
    os.makedirs(log_directory)

logger = logging.getLogger("trassir_agent.queue_debug")
logger.propagate = False
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = RotatingFileHandler(
        DEBUG_LOG,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)

seen = set()
seen_order = deque()
last_summary_at = 0

def remember(key):
    seen.add(key)
    seen_order.append(key)
    while len(seen_order) > SEEN_LIMIT:
        old_key = seen_order.popleft()
        seen.discard(old_key)

def inspect_queue():
    global last_summary_at

    # Читаем текущий путь БД из рабочего конфига.
    # Приложение Collector/Sender здесь не создаём.
    with open(CONFIG_FILE, "rb") as config_file:
        config = json.loads(config_file.read().decode("utf-8-sig"))
    database_path = resolve_path(config["storage"]["database"])

    # Не создаём пустую БД, если Collector ещё не запускался.
    if not os.path.isfile(database_path):
        logger.warning("Database does not exist: %s", database_path)
        return

    # Соединение создаётся и закрывается в текущем callback.
    # Между потоками SDK его не передаём.
    connection = sqlite3.connect(database_path, timeout=0.1)
    connection.row_factory = dictionary_row_factory

    try:
        # Дополнительная защита: этому соединению запрещены записи.
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            """
            SELECT id, payload, status, batch_id
            FROM events
            ORDER BY created DESC, id DESC
            LIMIT ?
            """,
            (READ_LIMIT,),
        ).fetchall()

        # Показываем выбранные записи от старых к новым.
        for row in reversed(rows):
            event = json.loads(row["payload"])
            if (
                not SHOW_HEARTBEAT
                and event.get("event_type") == "agent.heartbeat"
            ):
                continue

            # Изменение статуса также выводим: pending -> batched -> delivered.
            key = (row["id"], row["status"], row["batch_id"])
            if key in seen:
                continue

            logger.info(
                "EVENT id=%s status=%s batch_id=%s payload=%s",
                row["id"],
                row["status"],
                row["batch_id"],
                json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            )

            if row["batch_id"]:
                batch = connection.execute(
                    """
                    SELECT payload
                    FROM batches
                    WHERE id = ?
                    """,
                    (row["batch_id"],),
                ).fetchone()
                if batch:
                    # Именно сохранённый HTTP-пакет:
                    # Sender использует этот JSON при отправке.
                    logger.info(
                        "HTTP_BATCH id=%s payload=%s",
                        row["batch_id"],
                        batch["payload"],
                    )

            remember(key)

        # Раз в минуту выводим общую картину очереди.
        current_time = time.time()
        if current_time >= last_summary_at + 60:
            counts = connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM events
                GROUP BY status
                """
            ).fetchall()
            summary = dict((row["status"], row["total"]) for row in counts)
            logger.info("QUEUE_COUNTS %s", json.dumps(summary, sort_keys=True))
            last_summary_at = current_time

    finally:
        connection.close()

def tick():
    try:
        inspect_queue()
    except Exception:
        logger.exception("Queue inspection failed")
    finally:
        timeout(POLL_SECONDS * 1000, tick)

logger.info("Queue debug started; show_heartbeat=%s", SHOW_HEARTBEAT)
timeout(1000, tick)
