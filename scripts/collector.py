# -*- coding: utf-8 -*-
# Серверная точка входа: события, raw_sdk, health сервера, инвентарь и health каналов.
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.object_health import CollectorApplication
# SDK-функции передаём явно; объект приложения создаём после загрузки модулей.
app = CollectorApplication(ROOT + "/config.json", settings, objects_list)

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        # Однократное планирование в миллисекундах; интервал после завершения прохода.
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

activate_on_events("", "", app.on_event)
timeout(1000, tick)
