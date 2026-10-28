# server_events_collector.py
import json
import os
import tempfile

import config
from camera_api import normalize_server_event
from logger import log_debug, log_info, log_error

pending_events = []


def save_buffer():
    directory = os.path.dirname(config.EVENTS_BUFFER_FILE)

    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    temp_file = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".events_buffer_",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_file = file.name
            json.dump(
                pending_events,
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_file, config.EVENTS_BUFFER_FILE)
        temp_file = None

        log_debug(
            "Буфер событий сохранён на диск: %s записей"
            % len(pending_events)
        )

    except Exception as error:
        log_error(
            "Не удалось сохранить буфер событий: %s"
            % error
        )
        raise

    finally:
        if temp_file and os.path.exists(temp_file):
            os.unlink(temp_file)


def load_buffer():
    if not os.path.exists(config.EVENTS_BUFFER_FILE):
        del pending_events[:]
        log_debug("Файл буфера событий не найден")
        return

    try:
        with open(
            config.EVENTS_BUFFER_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        del pending_events[:]

        if isinstance(data, list):
            pending_events.extend(data)

        log_debug(
            "Буфер событий загружен: %s записей"
            % len(pending_events)
        )

    except Exception as error:
        del pending_events[:]
        log_error(
            "Не удалось загрузить буфер событий: %s"
            % error
        )


def add_event(event):
    pending_events.append(normalize_server_event(event))
    save_buffer()


def take_pending_events():
    events = pending_events[:]
    del pending_events[:]
    save_buffer()

    log_debug(
        "Из буфера взято событий: %s"
        % len(events)
    )

    return events


def return_events(events):
    pending_events[:0] = events
    save_buffer()

    log_debug(
        "Возвращено событий в буфер: %s"
        % len(events)
    )


def on_server_event(ev):
    log_debug(
        "Получено событие TRASSIR: type=%s, origin=%s"
        % (ev.type, ev.origin)
    )

    add_event(ev)


load_buffer()

activate_on_events(
    config.SERVER_EVENT_TYPE_FILTER,
    config.SERVER_EVENT_OBJECT_FILTER,
    on_server_event,
)
