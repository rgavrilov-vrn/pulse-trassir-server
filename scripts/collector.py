# -*- coding: utf-8 -*-
# Запускать только после остановки прежних Collector и Sender.
# Reload не отменяет существующие SDK-подписки и таймеры.
import sys
ROOT = r"C:\TRASSIR_Agent"
SOURCE = ROOT + "/src"
if SOURCE in sys.path:
    sys.path.remove(SOURCE)
sys.path.insert(0, SOURCE)
try:
    reload_module = reload
except NameError:
    from importlib import reload as reload_module

for name in ["trassir_agent.core", "trassir_agent.features",
             "trassir_agent.inventory", "trassir_agent.unified_snapshot"]:
    if name in sys.modules:
        reload_module(sys.modules[name])
    else:
        __import__(name, fromlist=["CollectorApplication"])

from trassir_agent.unified_snapshot import CollectorApplication
app = CollectorApplication(ROOT + "/config.json", settings, objects_list, object)
app.logger.info("Unified Collector started: module=%s options=%s",
                type(app).__module__, app._snapshot_options)

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

activate_on_events("", "", app.on_event)
timeout(1000, tick)
