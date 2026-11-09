# -*- coding: utf-8 -*-
# Одноразовая утилита для серверного Script Editor TRASSIR / Python 2.7.
# Перед запуском Collector и Sender должны быть остановлены.
# reload не отменяет старые SDK-подписки, таймеры и экземпляры приложений.

import sys

ROOT = r"C:\TRASSIR_Agent"
MODULE_PATH = ROOT + r"\src"

if MODULE_PATH not in sys.path:
    sys.path.insert(0, MODULE_PATH)

# Загружаем именно модули, а не отдельные классы из них.
import trassir_agent.core as core
import trassir_agent.features as features
import trassir_agent.inventory as inventory
import trassir_agent.object_health as object_health
import trassir_agent.profiles as profiles
import trassir_agent.object_states as object_states
import trassir_agent.unified_snapshot as unified_snapshot
import trassir_agent.device_snapshot as device_snapshot

# Сначала перечитываем базовые классы, затем производные.
core = reload(core)
features = reload(features)
inventory = reload(inventory)
object_health = reload(object_health)
profiles = reload(profiles)
object_states = reload(object_states)
unified_snapshot = reload(unified_snapshot)
device_snapshot = reload(device_snapshot)

# Структурная проверка определения класса в памяти.
# Наличие property само по себе не является многопоточным тестом SQLite.
db_attribute = core.EventRepository.__dict__.get("db")

if not isinstance(db_attribute, property):
    raise RuntimeError(
        "SQLite thread-local fix is NOT loaded"
    )

message(
    "Telemetry module reloaded. File: %s; "
    "EventRepository.db is a property: OK"
    % core.__file__
)
