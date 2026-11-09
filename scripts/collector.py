# -*- coding: utf-8 -*-
# Вставьте этот файл в СЕРВЕРНЫЙ скрипт автоматизации TRASSIR.
# Модули и config.json должны находиться на том же сервере, не на клиентском ПК.
import sys
ROOT = r"C:\TRASSIR_Agent"
# Добавляем каталог пакета, а не отдельные файлы. Для Linux измените ROOT.
sys.path.insert(0, ROOT + "/src")
from trassir_agent.core import CollectorApplication
app = CollectorApplication(ROOT + "/config.json")

def tick():
    # Периодическое чтение файловых логов, reload настроек и heartbeat.
    try:
        app.tick()
    except Exception:
        app.logger.exception("Tick failed")
    finally:
        # timeout — однократный вызов в миллисекундах: планируем следующий
        # даже после ошибки, без time.sleep и без бесконечного while.
        timeout(int(app.config.value["collector"]["tick_seconds"] * 1000), tick)

# Пустые фильтры — все типы и объекты системного журнала.
# Подписка одна; динамические исключения проверяются внутри app.on_event.
activate_on_events("", "", app.on_event)
# Первый периодический проход через секунду; подписка уже активна.
timeout(1000, tick)
