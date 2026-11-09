# -*- coding: utf-8 -*-
# Серверная точка входа TRASSIR. SDK settings передаём явно.
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.features import CollectorApplication
app = CollectorApplication(ROOT + "/config.json", settings)

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        # Однократный SDK timeout, миллисекунды. Следующий вызов после завершения.
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

activate_on_events("", "", app.on_event)
timeout(1000, tick)
