# config.py
# Общие константы интеграции TRASSIR -> REST API.

MONITOR_ENABLED = True

SERVER_ID = "trassir-01"
POLL_INTERVAL_SECONDS = 60

REST_API_HOST = "api.example.com"
REST_API_PORT = 443
REST_API_PATH = "/v1/trassir/status"
REST_API_TOKEN = "ВАШ_ТОКЕН"
REST_API_TIMEOUT = 10
VERIFY_SSL = False

SCHEMA_VERSION = 1

SERVER_NAME = "trassir-server-01"
SERVER_HOSTNAME = "trassir-server-01.local"
SERVER_IP = "10.81.0.82"
SERVER_VERSION = "4.5"

SERVER_EVENT_TYPE_FILTER = ""
SERVER_EVENT_OBJECT_FILTER = ""

EVENTS_BUFFER_FILE = "/opt/trassir_scripts/events_buffer.json"
# Для Windows:
# EVENTS_BUFFER_FILE = r"C:\trassir_scripts\events_buffer.json"

LOG_FILE = "/opt/trassir_scripts/camera_monitor.log"
LOG_LEVEL = "INFO"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_PAYLOAD_DEBUG = True

STATUS_UNKNOWN = "unknown"
STATUS_VIDEO_OK = "video_ok"
STATUS_VIDEO_LOST = "video_lost"
STATUS_DISABLED = "disabled"
