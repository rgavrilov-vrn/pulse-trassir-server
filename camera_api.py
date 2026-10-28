# camera_api.py
import json
import http.client
import ssl
import uuid
from datetime import datetime, timezone

import config
from logger import log_debug, log_info, log_error


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def generate_event_id():
    event_id = str(uuid.uuid4())
    log_debug("Сгенерирован event_id: %s" % event_id)
    return event_id


def get_server_info():
    log_debug(
        "Формирование информации о сервере: %s"
        % config.SERVER_ID
    )

    return {
        "server_id": config.SERVER_ID,
        "name": config.SERVER_NAME,
        "hostname": config.SERVER_HOSTNAME,
        "ip_address": config.SERVER_IP,
        "trassir_version": config.SERVER_VERSION,
        "trassir_server_guid": getattr(server, "guid", None),
        "trassir_server_name": getattr(server, "name", None),
        "trassir_server_class": getattr(server, "class_name", None),
        "generated_at": now_iso(),
    }


def build_camera_record(camera):
    record = {
        "camera_id": camera.guid,
        "name": camera.name,
        "ip_address": getattr(camera, "connection_ip", None),
        "model": getattr(camera, "model", None),
        "vendor": getattr(camera, "family", None),
        "channel_id": getattr(camera, "channel00_guid", None),
        "enabled": getattr(camera, "grabber_enabled", None),
        "status": config.STATUS_UNKNOWN,
        "observed_at": now_iso(),
    }

    log_debug(
        "Сформирована запись камеры: %s"
        % record["camera_id"]
    )

    return record


def normalize_server_event(event):
    record = {
        "event_id": generate_event_id(),
        "server_id": config.SERVER_ID,
        "type": event.type,
        "timestamp": event.ts,
        "observed_at": now_iso(),
        "origin": event.origin,
        "origin_name": event.origin_object.name,
        "p1": event.p1,
        "p2": event.p2,
        "p3": event.p3,
    }

    log_debug(
        "Событие нормализовано: type=%s, origin=%s"
        % (record["type"], record["origin"])
    )

    return record


def build_payload(cameras, events):
    payload = {
        "schema_version": config.SCHEMA_VERSION,
        "server": get_server_info(),
        "cameras": cameras,
        "events": events,
    }

    log_debug(
        "Payload сформирован: камер %s, событий %s"
        % (len(cameras), len(events))
    )

    if config.LOG_PAYLOAD_DEBUG:
        log_debug(
            "Payload: %s"
            % json.dumps(payload, ensure_ascii=False)
        )

    return payload


def send_status(payload):
    body = json.dumps(payload, ensure_ascii=False)

    log_debug(
        "Подготовка запроса к REST API: %s:%s%s"
        % (
            config.REST_API_HOST,
            config.REST_API_PORT,
            config.REST_API_PATH,
        )
    )

    context = None

    if not config.VERIFY_SSL:
        context = ssl._create_unverified_context()

    connection = http.client.HTTPSConnection(
        config.REST_API_HOST,
        config.REST_API_PORT,
        context=context,
        timeout=config.REST_API_TIMEOUT,
    )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer %s" % config.REST_API_TOKEN,
    }

    try:
        connection.request(
            "POST",
            config.REST_API_PATH,
            body=body.encode("utf-8"),
            headers=headers,
        )

        response = connection.getresponse()
        response_body = response.read().decode("utf-8")

        log_debug(
            "Получен ответ REST API: HTTP %s"
            % response.status
        )

        if response.status not in (200, 201, 202, 204):
            raise Exception(
                "HTTP %s: %s"
                % (
                    response.status,
                    response_body,
                )
            )

        log_info(
            "REST API отправка успешна: HTTP %s, камер %s, событий %s"
            % (
                response.status,
                len(payload.get("cameras", [])),
                len(payload.get("events", [])),
            )
        )

        return {
            "http_status": response.status,
            "body": response_body,
        }

    except Exception as error:
        log_error(
            "Ошибка отправки в REST API %s:%s%s: %s"
            % (
                config.REST_API_HOST,
                config.REST_API_PORT,
                config.REST_API_PATH,
                error,
            )
        )

        raise

    finally:
        connection.close()
