# -*- coding: utf-8 -*-
# Отдельный СЕРВЕРНЫЙ скрипт TRASSIR: доставка из SQLite, не подписка на события.
# Отдельный SDK-скрипт не означает отдельный процесс или изоляцию от Script Engine.
import sys
ROOT = r"C:\TRASSIR_Agent"
sys.path.insert(0, ROOT + "/src")
from trassir_agent.core import SenderApplication
app = SenderApplication(ROOT + "/config.json")

def tick():
    # Один проход: reload, захват пакета, максимум один HTTPS POST, фиксация результата.
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        # Следующий проход через настроенный интервал после окончания текущего.
        # HTTPS синхронный, поэтому реальный период включает длительность запроса.
        timeout(int(app.config.value["sender"]["tick_seconds"] * 1000), tick)

# В примере sender.enabled=false: скрипт можно запустить до включения доставки.
timeout(1000, tick)
