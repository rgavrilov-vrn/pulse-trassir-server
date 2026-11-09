# -*- coding: utf-8 -*-
# SDK object передаётся явно: не подменять его встроенным Python object.
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.object_states import CollectorApplication
app = CollectorApplication(ROOT + "/config.json", settings, objects_list, object)

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

activate_on_events("", "", app.on_event)
timeout(1000, tick)
