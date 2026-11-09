# -*- coding: utf-8 -*-
# Серверный Collector: прежние сборщики плюс профили каналов, архива и IP-устройств.
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.profiles import CollectorApplication
app = CollectorApplication(ROOT + "/config.json", settings, objects_list)

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

activate_on_events("", "", app.on_event)
timeout(1000, tick)
