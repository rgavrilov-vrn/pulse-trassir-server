# -*- coding: utf-8 -*-
# Серверная точка входа TRASSIR: события, health, raw_sdk и инвентаризация.
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.inventory import CollectorApplication
# Передаём штатные SDK-функции, а не предполагаем их наличие в модулях.
app = CollectorApplication(ROOT + "/config.json", settings, objects_list)

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        # SDK timeout — однократный вызов в миллисекундах.
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

activate_on_events("", "", app.on_event)
timeout(1000, tick)
