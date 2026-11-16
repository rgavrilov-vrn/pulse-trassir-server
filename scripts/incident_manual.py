# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import re
import json
import uuid
import datetime
import requests


# ============================================================
# Настройки
# ============================================================

KUMA_URL = "http://10.10.55.220:7777/input"

PULSE_BASE_URL = "http://10.10.55.229:8080"

PULSE_INCIDENT_URL = (
    PULSE_BASE_URL
    + "/pulse-platform/api/v1/tressir/incidents/manual"
)

PULSE_TOKEN_URL = (
    PULSE_BASE_URL
    + "/pulse-platform/api/v1/auth/token"
)

SERVER_ID = "11111111-1111-1111-1111-111111111111"

ROOT_DIR = "C:/Users/r.gavrilov/TRASSIR_Incidents"
SECRETS_DIR = os.path.join(ROOT_DIR, "secrets")

LOG_FILE = os.path.join(ROOT_DIR, "send_log.txt")

# Токен KUMA хранится отдельно от кода.
KUMA_TOKEN_FILE = os.path.join(SECRETS_DIR, "kuma.token")

# Настройки запроса получения токена Pulse.
PULSE_AUTH_FILE = os.path.join(SECRETS_DIR, "pulse_auth.json")

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15
REQUEST_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

VIOLATION_NAME = "Событие из TRASSIR"

# Сохранено из исходного кода.
# Проверьте соответствие адресу сервера выбранного канала.
SCREENSHOT_URL_TEMPLATE = (
    "https://10.81.0.82:8080/screenshot/%s"
    "?timestamp=%s&password=Script"
)

try:
    text_type = unicode
except NameError:
    text_type = str


# ============================================================
# Общие функции
# ============================================================

def txt(value):
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")

    return text_type(value)


def utc_string(value):
    return value.strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def ensure_directory(path):
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            if not os.path.isdir(path):
                raise


def safe_filename(value):
    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        txt(value)
    )

    return value.strip(" .")[:80] or "camera"


def write_log(service, message):
    try:
        ensure_directory(ROOT_DIR)

        line = "[%s] [%s] %s\n" % (
            datetime.datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            txt(service),
            txt(message).replace("\r", " ").replace("\n", " ")
        )

        with open(LOG_FILE, "ab") as stream:
            stream.write(line.encode("utf-8"))

    except Exception:
        # Ошибка логирования не должна прерывать отправку.
        pass

def log_error(service, error):
    import sys
    import traceback

    parts = [
        "ERROR",
        type(error).__name__
    ]

    if isinstance(error, IOError):
        parts.append(
            "errno=%s"
            % txt(getattr(error, "errno", None))
        )

        parts.append(
            "reason=%s"
            % txt(getattr(error, "strerror", None))
        )

        parts.append(
            "file=%s"
            % txt(getattr(error, "filename", None))
        )

    elif isinstance(error, KeyError):
        missing_key = (
            error.args[0]
            if error.args
            else "<unknown>"
        )

        parts.append(
            "missing_key=%s" % txt(missing_key)
        )

    elif isinstance(error, RuntimeError):
        message = txt(error)

        if message.startswith("Token endpoint HTTP "):
            parts.append(message)

    elif service == "SCREENSHOT":
        parts.append(txt(error))

    # Только название функции и номер строки.
    # Исходный код и локальные переменные не выводятся.
    tb = sys.exc_info()[2]

    if tb is not None:
        frames = traceback.extract_tb(tb)

        if frames:
            frame = frames[-1]

            parts.append(
                "function=%s line=%s"
                % (
                    txt(frame[2]),
                    frame[1]
                )
            )

    write_log(
        service,
        " ".join(parts)
    )

def write_json(path, data):
    # Итоговое имя содержит UUID, существующие файлы не заменяем.
    temporary = path + "." + str(uuid.uuid4()) + ".tmp"

    ensure_directory(os.path.dirname(path))

    try:
        payload = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        ).encode("utf-8")

        with open(temporary, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        os.rename(temporary, path)

    finally:
        if os.path.isfile(temporary):
            try:
                os.remove(temporary)
            except Exception:
                pass


def read_token_file(path):
    with open(path, "rb") as stream:
        token = stream.read().decode("ascii").strip()

    return validate_token(token)


def validate_token(value):
    if not isinstance(value, (text_type, bytes)):
        raise ValueError("Token must be a string")

    token = txt(value).strip()

    if not token or "\r" in token or "\n" in token:
        raise ValueError("Empty or invalid token")

    token.encode("ascii")
    return token


def json_bytes(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False
    ).encode("utf-8")


# ============================================================
# Авторизация Pulse
# ============================================================

def get_pulse_token():
    """
    Получает токен Pulse.

    Настройки читает из PULSE_AUTH_FILE.
    В лог записывает только HTTP-статус авторизации.
    Пароли, токен и тело ответа не логируются.
    """
    with open(PULSE_AUTH_FILE, "rb") as stream:
        config = json.loads(
            stream.read().decode("utf-8-sig")
        )

    request_format = config["request_format"]
    request_body = config["body"]
    token_path = config["token_path"]

    if request_format not in ("json", "form"):
        raise ValueError(
            "request_format must be json or form"
        )

    if (
        not isinstance(token_path, list)
        or not token_path
        or not all(
            isinstance(key, (text_type, bytes))
            for key in token_path
        )
    ):
        raise ValueError(
            "token_path must be a non-empty list of keys"
        )

    headers = {
        "Accept": "application/json"
    }

    if request_format == "json":
        headers["Content-Type"] = (
            "application/json; charset=utf-8"
        )

        body = json_bytes(request_body)

    else:
        body = request_body

    response = requests.post(
        PULSE_TOKEN_URL,
        data=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False
    )

    try:
        status = response.status_code

        write_log(
            "PULSE_AUTH",
            "HTTP %s" % status
        )

        if not 200 <= status < 300:
            raise RuntimeError(
                "Token endpoint HTTP %s" % status
            )

        value = response.json()

        for key in token_path:
            value = value[key]

        return validate_token(value)

    finally:
        response.close()

# ============================================================
# Формирование событий
# ============================================================

def build_kuma_data(camera_guid, camera_name,
                    video_time, event_time_utc,
                    comment, image_filename):
    return {
        "video_timestamp": video_time,

        # Сохраняем формат старого поля:
        # UTC без миллисекунд и суффикса Z.
        "timestampUtc": event_time_utc[:19],

        "camera_guid": camera_guid,
        "camera_name": camera_name,
        "comment": comment,
        "image_file": image_filename,

        "screenshot_url": (
            SCREENSHOT_URL_TEMPLATE
            % (camera_guid, video_time)
        )
    }


def build_manual_event(event_id, camera_guid,
                       camera_name, video_time,
                       event_time_utc, comment,
                       image_filename):
    return {
        "event_id": event_id,
        "event_type": "trassir.incident_manual",
        "event_version": "1.0",

        "occurred_at": event_time_utc,
        "observed_at": event_time_utc,

        "source": {
            "object_id": camera_guid,
            "object_name": camera_name,
            "object_class": "Channel"
        },

        "data": {
            "reason": "operator_reported",
            "comment": comment,
            "video_timestamp": video_time,
            "image_file": image_filename
        }
    }


def build_pulse_batch(event):
    return {
        "contract": "trassir.telemetry",
        "contract_version": "1.0",

        "batch_id": str(uuid.uuid4()),
        "sent_at": utc_string(
            datetime.datetime.utcnow()
        ),

        "producer": {
            "name": "trassir-client-manual",
            "version": "1.0.0"
        },

        "server": {
            "server_id": SERVER_ID
        },

        "events": [event]
    }


# ============================================================
# Отправка
# ============================================================

def post_json(service, url, data, token, expected_status=None):
    response = requests.post(
        url,
        data=json_bytes(data),

        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": "Bearer " + token
        },

        timeout=REQUEST_TIMEOUT,
        allow_redirects=False
    )

    try:
        status = response.status_code

        # Токен, тело запроса и ответ сервиса не логируем.
        write_log(service, "HTTP %s" % status)

        if expected_status is not None:
            accepted = status == expected_status
        else:
            accepted = 200 <= status < 300

        return accepted, status

    finally:
        response.close()


def send_to_kuma(data):
    try:
        token = read_token_file(KUMA_TOKEN_FILE)

        accepted, status = post_json(
            "KUMA",
            KUMA_URL,
            data,
            token
        )

        if accepted:
            return "KUMA: HTTP %s" % status

        return "KUMA: не подтверждено, HTTP %s" % status

    except Exception as error:
        log_error("KUMA", error)

        return "KUMA: ошибка %s" % type(error).__name__


def send_to_pulse(batch):
    try:
        token = get_pulse_token()

        accepted, status = post_json(
            "PULSE",
            PULSE_INCIDENT_URL,
            batch,
            token,
            expected_status=200
        )

        if accepted:
            return "Pulse: подтверждено, HTTP 200"

        return "Pulse: не подтверждено, HTTP %s" % status

    except Exception as error:
        log_error("PULSE", error)

        return "Pulse: ошибка %s" % type(error).__name__


def save_screenshot(channel, video_time, image_filename):
    try:
        camera = object(channel.guid)

        if not hasattr(camera, "screenshot_v2"):
            write_log(
                "SCREENSHOT",
                "Unavailable: type=%s guid=%s"
                % (
                    type(camera).__name__,
                    txt(channel.guid)
                )
            )

            return "Кадр: screenshot_v2 недоступен"

        camera.screenshot_v2(
            video_time,
            image_filename,
            ROOT_DIR,
            0
        )

        write_log(
            "SCREENSHOT",
            "Requested " + image_filename
        )

        return "Кадр: запрос выполнен"

    except Exception as error:
        log_error("SCREENSHOT", error)

        return "Кадр: ошибка %s" % type(error).__name__

# ============================================================
# Обработчик контекстного меню
# ============================================================

def register_incident(channel):
    try:
        ensure_directory(ROOT_DIR)

        event_id = str(uuid.uuid4())

        # Времена относятся к моменту регистрации.
        event_time_utc = utc_string(
            datetime.datetime.utcnow()
        )

        video_time = datetime.datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        camera_guid = txt(channel.guid)
        camera_name = txt(channel.name)
        comment = ""

        if not camera_guid:
            raise ValueError("Empty channel GUID")

        base_filename = "%s_%s_%s" % (
            video_time,
            safe_filename(camera_name),
            event_id
        )

        image_filename = base_filename + ".jpg"

        event = build_manual_event(
            event_id,
            camera_guid,
            camera_name,
            video_time,
            event_time_utc,
            comment,
            image_filename
        )

        # Сохраняем именно событие, а не telemetry-пакет.
        event_path = os.path.join(
            ROOT_DIR,
            base_filename + "_incident_manual.json"
        )

        # При ошибке сохранения отправку не начинаем.
        write_json(event_path, event)

        write_log(
            "LOCAL",
            "Saved event_id=" + event_id
        )

        kuma_data = build_kuma_data(
            camera_guid,
            camera_name,
            video_time,
            event_time_utc,
            comment,
            image_filename
        )

        screenshot_result = save_screenshot(
            channel,
            video_time,
            image_filename
        )

        # Сервисы отправляются независимо:
        # ошибка KUMA не отменяет попытку отправки в Pulse.
        kuma_result = send_to_kuma(kuma_data)

        pulse_batch = build_pulse_batch(event)
        pulse_result = send_to_pulse(pulse_batch)

        alert(
            "Событие: %s\n"
            "JSON сохранён локально.\n"
            "%s\n%s\n%s"
            % (
                event_id,
                screenshot_result,
                kuma_result,
                pulse_result
            )
        )

    except Exception as error:
        error_type = type(error).__name__

        write_log(
            "INCIDENT",
            "ERROR " + error_type
        )

        alert(
            "Регистрация прервана: %s\n"
            "Если ошибка возникла при сохранении JSON, "
            "отправка не выполнялась."
            % error_type
        )


menu_action = host.activate_on_context_menu(
    "Channel",
    "Pulse: Зафиксировать событие",
    register_incident
)