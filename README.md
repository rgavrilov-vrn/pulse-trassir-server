# TRASSIR SDK Telemetry Agent

Серверный агент TRASSIR: собирает снимки объектов, системные события и выбранные текстовые логи, сохраняет в SQLite и отправляет во внешнюю систему по HTTPS. Развёртывание копированием, без pip, отдельной службы и брокера. Основное окружение — серверный Script Engine Python 2.7; совместимость конкретной сборки проверяется пилотом.

## Актуальная схема
```text
SDK objects / settings / events / text logs
                  |
           Collector (SDK script)
                  |
             SQLite COMMIT
                  |
          best-effort JSONL copy
                  |
           Sender (SDK script)
                  |
       persisted HTTP batch -> HTTPS POST
                  |
             HTTP 200 -> delivered
```
Два SDK-скрипта не означают два изолированных процесса. SQLite — очередь и источник истины; JSONL — дополнительная копия, не очередь доставки.

Основной мониторинг: `agent.objects_snapshot`, `event_version=2.0`. Одна запись на объект: идентификация + `values` + время/ошибки чтения. В снимок входят Server health, Channel metrics, SDK-состояния, паспорт IP Device и настроенные связи с каналами. Отдельные новые `trassir.health`, `agent.objects_health`, `agent.objects_states` не создаются текущей точкой входа. Старые события могут оставаться в очереди. Heartbeat, системные и файловые события остаются отдельными.

На пилотном video81 подтверждено локальное создание полного снимка 206 объектов, заполнение паспорта 82 IP Device и взаимных связей 82 каналов по channel00_guid; расширенный снимок разделился на две части. Это проверка конкретного пилота, не норматив числа объектов, не проверка HTTP-доставки и не гарантия для всех SDK/устройств.

## Файлы
| Путь | Назначение |
|---|---|
| config.json | Полный пилотный конфиг video81, Sender выключен |
| scripts/collector.py | Текущая SDK-точка входа, импорт device_snapshot |
| scripts/sender.py | SDK-точка входа доставки |
| src/trassir_agent/core.py | Конфиг, очередь, HTTP, базовый сбор |
| src/trassir_agent/features.py | raw_sdk, преобразование значений |
| src/trassir_agent/inventory.py | SDK-текст и разбиение снимков |
| src/trassir_agent/unified_snapshot.py | Общий перечень, Server/Channel/SDK values |
| src/trassir_agent/device_snapshot.py | Паспорт и связи IP Device/Channel |
| scripts/utils/ | Перезагрузка модулей и диагностика очереди |
| config/ | Примеры, в том числе предыдущих этапов |

Старые object_health/object_states/profiles сохранены для истории/отката, не являются текущим циклом сбора. Автоматического сборочного сценария и каталога тестов нет по решению владельца.

## Быстрый запуск
1. Скопируйте исходники в C:\TRASSIR_Agent, сохранив src/trassir_agent и scripts.
2. Для пилотного video81 используйте корневой config.json. Для другого сервера задайте собственный server_id и подтверждённый local_server_guid, путь ROOT и параметры приёмника.
3. URL monitor.example.com в пилотном конфиге — сохранённый исходный адрес, не подтверждённый рабочий endpoint. Не включайте отправку без проверки адреса/приёмника. Идентичность очереди привязана к server_id, destination_id и URL; для накопленных данных смена требует явной миграции.
4. Создайте secrets/api.token отдельно, если используется Bearer; файл не публикуется в Git. Настройте ACL для кода/конфига/токена и записи в state, archive, logs.
5. При остановленных прежних обработчиках замените содержимое серверных Collector/Sender актуальными scripts/*.py. Не запускайте второй Collector. reload не отменяет подписки/таймеры.
6. Запустите Collector, оставив sender.enabled=false. Проверьте Unified snapshot saved и JSONL: все части, values, полноту и повторные snapshot_id.
7. Подготовьте приёмник по CONTRACT.md, затем включайте Sender и проверяйте HTTP 200/статусы очереди.

## Документация
- [Контракт: HTTP, события, снимок v2, требования к приёмнику](docs/CONTRACT.md).
- [Логика работы: сбор, SQLite, отправка, перезапуск](docs/ARCHITECTURE.md).
- [Установка, конфигурация, диагностика и обновления](docs/OPERATIONS.md).
- [Индекс и статус документов предыдущих этапов](docs/README.md).

## Версии и ограничения
HTTP `contract_version=1.0`, снимок `event_version=2.0`, JSONL `record_version=1`, конфиг `config_version=1`, схема БД `meta.schema=1` — независимые версии. Producer в HTTP-коде объявляет 1.0.0, это не версия снимка.
Доставка с повторами; exactly-once и сохранение каждого события при любых сбоях не заявляются. Только HTTP 200 подтверждает весь пакет. Нет дисковой квоты/аварийного spool/автоимпорта JSONL. Синхронные SDK/HTTPS могут задерживать callback. Известный риск sqlite3.Row/Unicode в Sender отдельно требует проверки/исправления; dict-row_factory утилиты queue_debug его не исправляет.
