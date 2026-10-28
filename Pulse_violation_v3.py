import os
import json
import datetime
import requests

# Основной принимающий сервис
KUMA_URL = "http://10.10.55.220:7777/input"

# Дополнительный принимающий сервис
PULSE_URL = "http://10.10.55.229:8080/pulse-videoevents/"

# Каталог для JSON-файлов, скриншотов и логов
SCREENSHOT_DIR = r"C:\TRASSIR_Incidents"

LOG_FILE = os.path.join(SCREENSHOT_DIR, "send_log.txt")

# Таймауты запросов, секунды
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15
REQUEST_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

# Фиксированное название события
VIOLATION_NAME = "Событие из TRASSIR"

# Токен авторизации
AUTH_TOKEN = "8df504699a5ae5f717b4e14a896363f4"

# Идентификаторы для Pulse
PULSE_SOURCE = "TRASSIR"
PULSE_CREATION_MODE = "INTEGRATION"
PULSE_STATUS = "DRAFT"
PULSE_SEVERITY = "LOW"

PULSE_CREATED_BY_ID = "b98fcd6f-379f-483e-b905-8407c1cc59de"
PULSE_OPERATOR_ID = "b98fcd6f-379f-483e-b905-8407c1cc59de"
PULSE_CHECKLIST_ITEM_ID = "faf2af9b-972c-42eb-b811-0deec627a747"
PULSE_SERVER_ID = "d1a9067f-1cb8-456d-a6d1-6fbf9c875a3b"
PULSE_FACILITY_ID = "46164dcc-2278-40f0-8e37-fda195ce490a"
PULSE_ZONE_ID = "b2f12ce7-e58c-43c6-bca3-2c4698248b79"
PULSE_EMPLOYEE_ID = "b98fcd6f-379f-483e-b905-8407c1cc59de"
PULSE_DEPARTMENT_ID = "99b6cabf-4e60-4f4d-8ed2-f88d6c5d3680"


def txt(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text_type(value)


def build_kuma_data(channel, video_time, comment):
    """Формирует данные события для отправки в Kuma."""
    camera_guid = channel.guid
    camera_name = channel.name

    image_filename = video_time + "_" + txt(VIOLATION_NAME) + ".jpg"

    timestamp_utc = datetime.datetime.utcnow().strftime(
        "%Y-%m-%dT%H:%M:%S"
    )

    return {
        "video_timestamp": video_time,
        "timestampUtc": timestamp_utc,
        "camera_guid": camera_guid,
        "camera_name": camera_name,
        "comment": comment,
        "image_file": image_filename,
        "screenshot_url": (
            "https://10.81.0.82:8080/screenshot/%s?timestamp=%s&password=Script"
            % (camera_guid, video_time)
        )
    }


def build_pulse_data(channel, event_time_utc, comment):
    """Формирует данные события для отправки в Pulse."""
    return {
        "source": PULSE_SOURCE,
        "creationMode": PULSE_CREATION_MODE,
        "status": PULSE_STATUS,
        "severity": PULSE_SEVERITY,
        "eventTime": event_time_utc,
        "createdById": PULSE_CREATED_BY_ID,
        "operatorId": PULSE_OPERATOR_ID,
        "checklistItemId": PULSE_CHECKLIST_ITEM_ID,
        "serverId": PULSE_SERVER_ID,
        "facilityId": PULSE_FACILITY_ID,
        "zoneId": PULSE_ZONE_ID,
        "cameraId": "",
        "cameraDescription": channel.name,
        "employeeId": PULSE_EMPLOYEE_ID,
        "departmentId": PULSE_DEPARTMENT_ID,
        "comment": comment,
        "cameraExternalId": channel.guid
    }


def write_log(service, url, status=None, response_text="", error=None):
    """Записывает результат отправки в лог-файл."""
    try:
        if not os.path.isdir(SCREENSHOT_DIR):
            os.makedirs(SCREENSHOT_DIR)

        timestamp = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        if error is not None:
            message = (
                "[%s] [%s] [%s] ERROR: %s\n"
                % (timestamp, service, url, error)
            )
        else:
            message = (
                "[%s] [%s] [%s] HTTP %s: %s\n"
                % (
                    timestamp,
                    service,
                    url,
                    status,
                    response_text
                )
            )

        with open(LOG_FILE, "ab") as log:
            log.write(message.encode("utf-8"))
    except Exception as log_error:
        alert("Не удалось записать лог: %s" % log_error)


def write_json(path, data):
    """Атомарно сохраняет JSON-файл с обработкой ошибок."""
    temporary = path + ".tmp"

    try:
        directory = os.path.dirname(path)

        if directory and not os.path.isdir(directory):
            os.makedirs(directory)

        with open(temporary, "wb") as stream:
            stream.write(
                json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())

        os.rename(temporary, path)

    except Exception as error:
        # Пытаемся удалить временный файл, если он был создан
        try:
            if os.path.isfile(temporary):
                os.remove(temporary)
        except Exception as cleanup_error:
            write_log(
                "JSON",
                path,
                error=(
                    "Не удалось удалить временный файл %s: %s"
                    % (temporary, cleanup_error)
                )
            )

        error_text = "Не удалось сохранить JSON %s: %s" % (path, error)

        write_log(
            "JSON",
            path,
            error=error_text
        )

        alert(error_text)


def post_event(service_name, url, data):
    """Выполняет POST-запрос с таймаутом и логированием."""
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + AUTH_TOKEN
    }

    try:
        response = requests.post(
            url,
            payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        response_text = ""
        try:
            response_text = response.text[:1000]
        except Exception:
            pass

        write_log(
            service_name,
            url,
            response.status_code,
            response_text
        )

        response.raise_for_status()

        alert(
            "%s: событие отправлено, HTTP %s"
            % (service_name, response.status_code)
        )

        return response

    except requests.exceptions.Timeout:
        error_text = (
            "Таймаут запроса: connect=%s сек, read=%s сек"
            % (CONNECT_TIMEOUT, READ_TIMEOUT)
        )
        write_log(service_name, url, error=error_text)
        alert("%s: %s" % (service_name, error_text))
        return None

    except requests.exceptions.ConnectionError as error:
        error_text = "Ошибка соединения: %s" % error
        write_log(service_name, url, error=error_text)
        alert("%s: %s" % (service_name, error_text))
        return None

    except requests.exceptions.HTTPError as error:
        error_text = "HTTP-ошибка: %s" % error
        write_log(service_name, url, error=error_text)
        alert("%s: %s" % (service_name, error_text))
        return None

    except requests.exceptions.RequestException as error:
        error_text = "Ошибка запроса: %s" % error
        write_log(service_name, url, error=error_text)
        alert("%s: %s" % (service_name, error_text))
        return None

    except Exception as error:
        error_text = "Неизвестная ошибка: %s" % error
        write_log(service_name, url, error=error_text)
        alert("%s: %s" % (service_name, error_text))
        return None


def send_to_kuma(data):
    """Отправляет событие в Kuma."""
    return post_event("KUMA", KUMA_URL, data)


def send_to_pulse(data):
    """Отправляет событие в Pulse."""
    return post_event("PULSE", PULSE_URL, data)


def save_screenshot(channel, video_time, image_filename):
    """Сохраняет стоп-кадр из архива в JPG-файл."""
    try:
        channel.screenshot_v2(
            video_time,
            image_filename,
            SCREENSHOT_DIR,
            0
        )
    except Exception as error:
        alert("Не удалось запросить кадр: %s" % error)


def register_incident(channel):
    # Время события: текущий момент
    video_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # Комментарий по умолчанию
    comment = ""

    # Время события в формате ISO 8601 UTC с миллисекундами
    event_time_utc = datetime.datetime.utcnow().strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"

    # Данные для Kuma
    kuma_data = build_kuma_data(
        channel,
        video_time,
        comment
    )

    # Данные для Pulse
    pulse_data = build_pulse_data(
        channel,
        event_time_utc,
        comment
    )

    # Общая часть имени файлов
    base_filename = (
        video_time + "_" + txt(VIOLATION_NAME) + "_" +
        txt(channel.name) + "(" + channel.guid + ")"
    )

    # Имена локальных JSON-файлов
    kuma_json_filename = base_filename + "_kuma.json"
    pulse_json_filename = base_filename + "_pulse.json"

    # Сохранение JSON для Kuma
    write_json(
        os.path.join(SCREENSHOT_DIR, kuma_json_filename),
        kuma_data
    )

    # Сохранение JSON для Pulse
    write_json(
        os.path.join(SCREENSHOT_DIR, pulse_json_filename),
        pulse_data
    )

    # Сохранение стоп-кадра из архива в JPG
    save_screenshot(
        channel,
        video_time,
        kuma_data["image_file"]
    )

    # Отправка события в Kuma
    send_to_kuma(kuma_data)

    # Отправка события в Pulse
    send_to_pulse(pulse_data)


action = activate_on_context_menu(
    "Channel",
    "Зафиксировать событие",
    register_incident
)
