# -*- coding: utf-8 -*-
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.core import SenderApplication
app = SenderApplication(ROOT + "/config.json")

def tick():
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        timeout(int(app.config.value["sender"]["tick_seconds"] * 1000), tick)


timeout(1000, tick)
