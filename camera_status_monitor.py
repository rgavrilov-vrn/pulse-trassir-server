# camera_status_monitor.py
"""
<parameters>
    <parameter>
        <id>log_level</id>
        <type>string_from_list</type>
        <name>Уровень логирования</name>
        <value>INFO</value>
        <string_list>DEBUG,INFO,WARNING,ERROR,CRITICAL</string_list>
    </parameter>

    <parameter>
        <id>monitor_enabled</id>
        <type>boolean</type>
        <name>Включить отправку состояния камер</name>
        <value>1</value>
    </parameter>
</parameters>
"""

import sys

sys.path.append("/opt/trassir_scripts")
# Для Windows:
# sys.path.append(r"C:\trassir_scripts")

import config
from camera_api import (
    build_camera_record,
    build_payload,
    send_status,
)
from logger import (
    init_logger,
    apply_log_level,
    log_debug,
    log_info,
    log_error,
)
from server_events_collector import (
    take_pending_events,
    return_events,
)


def get_all_cameras():
    cameras = []

    for camera in server.objects["ip_cameras"].objects:
        if camera.type != "Grabber":
            continue

        cameras.append(camera)

    log_debug(
        "Найдено камер типа Grabber: %s"
        % len(cameras)
    )

    return cameras


def monitor_cameras():
    if not config.MONITOR_ENABLED:
        log_debug("Мониторинг отключён")
        return

    log_debug("Запуск цикла мониторинга")

    cameras = get_all_cameras()

    camera_records = [
        build_camera_record(camera)
        for camera in cameras
    ]

    events = take_pending_events()
    payload = build_payload(camera_records, events)

    try:
        result = send_status(payload)

        log_info(
            "Цикл мониторинга завершён успешно: "
            "камер %s, событий %s, HTTP %s"
            % (
                len(camera_records),
                len(events),
                result["http_status"],
            )
        )

    except Exception as error:
        return_events(events)

        log_error(
            "Цикл мониторинга завершён с ошибкой; "
            "возвращено событий в буфер: %s"
            % len(events)
        )


init_logger(log_level)
config.MONITOR_ENABLED = bool(monitor_enabled)

monitor_cameras()

timeout(
    config.POLL_INTERVAL_SECONDS,
    monitor_cameras,
)
