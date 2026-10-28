# TRASSIR Camera Monitor

Интеграция TRASSIR с внешней REST API: периодический сбор состояния IP-камер и событий сервера, формирование JSON snapshot и отправка по HTTPS.

## Состав проекта

```text
trassir_camera_monitor/
├── config.py
├── logger.py
├── camera_api.py
├── server_events_collector.py
├── camera_status_monitor.py
└── README.md
```

## Как работает

```text
TRASSIR Script Engine
        ↓ activate_on_events()
Буфер событий в памяти
        ↓ сохранение в events_buffer.json
camera_status_monitor.py
        ↓ timeout(POLL_INTERVAL_SECONDS)
Формирование payload
        ↓ HTTPS POST
Внешний REST API
```

- События собираются через `activate_on_events()`.
- Каждому событию присваивается уникальный `event_id` (UUID4).
- Буфер хранится в `events_buffer.json`.
- Буфер очищается только после успешного POST.
- При ошибке REST API события возвращаются в буфер и сохраняются на диске.
- Лог пишется в `camera_monitor.log` с ротацией по размеру.

## Развёртывание

1. Создайте на сервере TRASSIR папку:

```text
/opt/trassir_scripts/
```

Для Windows:

```text
C:\trassir_scripts\
```

2. Скопируйте в неё файлы:

```text
config.py
logger.py
camera_api.py
server_events_collector.py
camera_status_monitor.py
```

3. Проверьте права пользователя TRASSIR на запись:

```text
/opt/trassir_scripts/events_buffer.json
/opt/trassir_scripts/camera_monitor.log
```

4. В TRASSIR откройте:

```text
Настройки -> Автоматизация -> Скрипты -> Новый скрипт
```

5. Вставьте содержимое `camera_status_monitor.py`.

6. Убедитесь, что путь к модулям указан правильно:

```python
sys.path.append("/opt/trassir_scripts")
```

Для Windows:

```python
sys.path.append(r"C:\trassir_scripts")
```

7. Установите параметры скрипта:

| Параметр | Значение |
|---|---|
| `log_level` | `DEBUG` для отладки, `INFO` для production |
| `monitor_enabled` | `1` |

8. Включите скрипт и нажмите **Save and Run**.

## Настройка config.py

Перед запуском обязательно измените:

```python
SERVER_ID = "trassir-01"
REST_API_HOST = "api.example.com"
REST_API_PATH = "/v1/trassir/status"
REST_API_TOKEN = "ВАШ_ТОКЕН"
EVENTS_BUFFER_FILE = "/opt/trassir_scripts/events_buffer.json"
LOG_FILE = "/opt/trassir_scripts/camera_monitor.log"
```

Для Windows:

```python
EVENTS_BUFFER_FILE = r"C:\trassir_scripts\events_buffer.json"
LOG_FILE = r"C:\trassir_scripts\camera_monitor.log"
```

## Формат payload

```json
{
  "schema_version": 1,
  "server": {
    "server_id": "trassir-01",
    "name": "trassir-server-01",
    "hostname": "trassir-server-01.local",
    "ip_address": "10.81.0.82",
    "trassir_version": "4.5",
    "trassir_server_guid": "a1b2c3d4",
    "trassir_server_name": "trassir-server-01",
    "trassir_server_class": "Server",
    "generated_at": "2026-10-16T11:46:00+00:00"
  },
  "cameras": [
    {
      "camera_id": "eQi2LbHz",
      "name": "Вход",
      "ip_address": "10.81.0.120",
      "model": "DS-2CD2143G2",
      "vendor": "Hikvision",
      "channel_id": "JFnVgcxe",
      "enabled": 1,
      "status": "unknown",
      "observed_at": "2026-10-16T11:46:00+00:00"
    }
  ],
  "events": [
    {
      "event_id": "9f2b7a51-4a9e-4dcb-9b3f-3e1f6c9d8a77",
      "server_id": "trassir-01",
      "type": "Signal Lost",
      "timestamp": 1760600000000000,
      "observed_at": "2026-10-16T11:46:00+00:00",
      "origin": "JFnVgcxe",
      "origin_name": "Вход",
      "p1": null,
      "p2": null,
      "p3": null
    }
  ]
}
```

## Проверка перед production

- Проверьте версию TRASSIR и доступность `json`, `uuid`, `http.client`, `os`, `tempfile`.
- Проверьте доступность `requests` и `pika`, только если они действительно нужны.
- Проверьте права на запись `EVENTS_BUFFER_FILE` и `LOG_FILE`.
- Проверьте доступность REST API с сервера TRASSIR.
- Подтвердите фактические атрибуты `server.guid`, `server.name`, `server.class_name`.
- Подтвердите поля события: `ev.type`, `ev.ts`, `ev.origin`, `ev.origin_object`, `ev.p1`, `ev.p2`, `ev.p3`.
- Определите фактическое поле health, отражающее наличие видеосигнала.
- Не используйте `status: unknown` как рабочий статус: он установлен намеренно до подтверждения health.
- Не включайте `LOG_PAYLOAD_DEBUG = True` в production, если payload содержит чувствительные данные.

## Важные ограничения

- Версия Python и доступные модули зависят от версии TRASSIR Script Engine.
- Не рассчитывайте на установку pip-пакетов внутри TRASSIR.
- `time.sleep()` блокирует Script Engine; для расписания используйте `timeout()`.
- Глобальные переменные не гарантируют сохранность после перезапуска TRASSIR.
- Для долговременного состояния используйте файл, PostgreSQL или внешний REST API.
- Не храните токены и пароли в логах.

## Безопасность

- Не публикуйте `REST_API_TOKEN`.
- Не логируйте токены, пароли камер и полные payload с чувствительными данными.
- Ограничьте права на `config.py`, `events_buffer.json` и `camera_monitor.log`.
- Для production используйте `LOG_LEVEL = "INFO"`.
