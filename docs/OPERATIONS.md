# Эксплуатация и сопровождение

Актуальный формат/приёмник: [CONTRACT.md](CONTRACT.md). Логика: [ARCHITECTURE.md](ARCHITECTURE.md). Текущий Collector импортирует device_snapshot, формат снимка 2.0.

## Установка
Копируйте проект в C:\TRASSIR_Agent без сборки/pip. Проверьте ROOT в scripts/collector.py и scripts/sender.py. Это код для СЕРВЕРНОГО редактора TRASSIR, а не самостоятельная служба/консольная программа. Не создавайте параллельные копии Collector/Sender.
Корневой config.json — полный конфиг пилотного video81. Для другой установки не копируйте server_id/local_server_guid/адрес назначения без адаптации. Старые config/*.example.json описывают также предыдущие этапы, не выбирайте их вместо актуального полного конфига вслепую. Sender по умолчанию выключен. monitor.example.com в исходной доставке не подтверждён как рабочий endpoint.
Создайте токен отдельно в secrets/api.token, ограничьте ACL; предоставьте пользователю TRASSIR запись state/archive/logs и чтение исходников/конфига/CA/токена. TLS проверяется. При собственной CA задайте ca_file, не отключайте верификацию.

## Главные настройки
| Раздел | Назначение |
|---|---|
| collector | Общий enabled, callback tick_seconds, heartbeat_seconds, file_copy_enabled, SDK-фильтры и log_sources |
| objects_snapshot | Единый период/переключатель, local_server_guid, server_health_fields, channel_fields, device_fields, device_channel_fields |
| raw_sdk | Диагностические SDK-атрибуты системных событий |
| sender | Доставка enabled, tick, лимиты пакета, retry, retention |
| delivery | HTTPS URL, destination_id, contract_version=1.0, token_file/ca_file, timeout_seconds |
| storage | database, archive, logs; относительные пути от config.json |

objects_snapshot.interval_seconds=10..86400 (в пилоте 60). Отсутствие enabled означает false; отсутствие периода — 60. Не оставляйте старый 300, если нужен опрос раз в минуту. local_server_guid задаётся явно либо null для единственного видимого Server. Автопривязка при нескольких Server запрещена.
server_health_fields/channel_fields — непустые списки allowlist без повторов. Если не заданы, используются прежние health.fields/objects_health.fields, затем встроенные defaults. Встроенный полный Server allowlist может включать неподдерживаемые показатели: для пилота используйте 21 проверенное поле корневого config.json.
device_fields — только connection_ip, connection_port, family, model. device_channel_fields — явные channelXX_guid (две цифры, до 64 полей), общий список для всех IP Device. В пилоте только channel00_guid; пустой список/отсутствие выключает связи. Не добавляйте отсутствующие индексы наугад: они вызывают неполноту чтения/обратных связей. Для неоднородных многоканальных устройств требуется отдельное развитие адаптера.
Старые health.enabled/objects_health.enabled/objects_states/monitoring_profiles не создают отдельных циклов текущим Collector. Не рассчитывайте, что их переключение выключит соответствующие данные внутри нового снимка. Состав выбирается актуальными списками полей; SDK-состояния шести классов заданы в коде.

## Применение конфига
Редактируйте атомарной заменой, не дублируйте JSON-ключи. Базовая проверка не чаще раза в 5 секунд в callback; при ошибке последняя рабочая конфигурация остаётся. Слои snapshot/raw_sdk и device-опций имеют отдельную валидацию и сохраняют собственные предыдущие настройки. При первом ошибочном разделе расширение может остаться выключенным/пустым, смотрите лог.
collector.enabled=false выключает сбор; sender.enabled=false выключает отправку, но не накопление. Токен/CA используются заново при попытке HTTP. Storage/identity требуют перезапуска/миграции: БД привязана к server_id,destination_id,url, в том числе после перезапуска. Не удаляйте meta и не меняйте адрес для накопленной очереди без плана миграции.

## Проверка Collector
При Sender=false ожидаются строки Unified Collector started: module=trassir_agent.device_snapshot и Unified snapshot saved. В последней проверяйте objects/parts/errors/inventory/complete. В JSONL: agent.objects_snapshot/2.0, все части снимка, Server.values, значения Channel/состояния/паспорт IP Device, channel_ids и ip_device_id. У всех частей общий snapshot_id; новый цикл — новый UUID.
Проверяйте несколько циклов. Успех логического снимка: inventory_complete=true, enrichment_complete=true, collection_complete=true, collection_errors=[], field_errors_count=0. Для связей отдельно device_links_complete и фактическое покрытие каналов; true не значит, что автоматически опрошены все аппаратные слоты.
collection_complete не равно server_ok: Needs Attention/Disconnected/Model Mismatch — реальные значения, не сбой агента. Успех JSONL не подтверждает HTTP-доставку.
Если нет новых полей, проверьте requested_fields_by_class, device_channel_fields, актуальный импорт/путь device_snapshot.py, конфиг и startup-строку. В device_snapshot метаданные связей присутствуют даже при выключенных слотах; их полное отсутствие указывает на другой путь сбора/версию, а не просто пустой паспорт.

## Файлы
- state/queue.db — очередь и состояния доставки.
- logs/collector.log, logs/sender.log — диагностика; ротация 2 MiB и 3 предыдущих файла.
- archive/events.jsonl — record_version=1, best-effort копия; 10 MiB и 3 предыдущих.
- logs/queue_debug.log — полный диагностический вывод утилиты; 2 MiB и 3 предыдущих.
Одна большая запись может превысить порог. Часы диагностики локальные, времена JSON — UTC с Z. Не подключайте собственный вывод в log_sources.

## Очередь и доставка
Read-only диагностические SELECT через совместимый SQLite-клиент:
```sql
SELECT status, COUNT(*) FROM events GROUP BY status;
SELECT MIN(created) FROM events WHERE status IN ('pending','batched');
SELECT id, attempts, error, next_at, lease FROM batches WHERE status='pending';
SELECT id FROM events WHERE status='quarantine';
SELECT * FROM meta;
```
Времена created/next_at/lease — Unix seconds. pending — не упаковано; batched — находится в пакете; delivered — локально подтверждён HTTP 200; quarantine — слишком большое одиночное событие. Pending-пакет с ошибкой блокирует новые. Не редактируйте статусы вручную для сокрытия проблемы.
Перед Sender=true проверьте реальный endpoint, токен/CA и поддержку всех версий/сборку частей/дедупликацию приёмником. Ожидайте Delivered batch и delivered в БД. Любой не-200 повторяется, тело ответа не используется. Не заявляйте полный успех только по JSONL.

## Типовые ошибки
| Сообщение/симптом | Действие |
|---|---|
| Unified snapshot settings rejected | Проверить snapshot/raw_sdk, типы полей, allowlist; остаются предыдущие настройки |
| Device snapshot settings rejected | Проверить device_fields и имена/повторы channelXX_guid; device-слой сохраняет прежние настройки |
| LocalServerNotResolved | Проверить видимые Server и local_server_guid, не подставлять чужой GUID |
| DeviceLinksIncomplete | Проверить ошибки channel_ids/source_field у устройств; не угадывать обратные ссылки |
| AmbiguousDeviceLink | Один Channel заявлен несколькими устройствами; проверить исходные настройки |
| unbound method __init__ | Проверить смешение поколений модулей; остановить старые обработчики, перечитать зависимую цепочку, создать новый app |
| SQLite objects created in a thread... | Проверить, что в памяти актуальный thread-local EventRepository; property-проверка сама по себе не полный тест потоков |
| sqlite3.Row / Unicode-ключи в Sender | Отдельный известный риск: dict в queue_debug не меняет row_factory Sender |
| database is locked / Event NOT saved | Проверить конкуренцию/нагрузку, возможна потеря события; JSONL не аварийный spool |
| File copy failed | Событие уже в SQLite, файловая копия не повторяется |
| HTTP 401/403, TLS, retry | Исправить доступ/CA/endpoint; пакет не удалять, учитывать блокировку следующих |
| Database identity mismatch | Согласовать миграцию очереди, не обходить удалением meta |

## Утилиты
- scripts/utils/reload_modules.py: один раз, Collector/Sender остановлены; обновляет определения в текущем интерпретаторе и проверяет EventRepository.db property. Не останавливает callbacks и не переиспользует старый app. Инструкция в scripts/utils/README.md.
- scripts/utils/queue_debug.py: отдельный диагностический скрипт с таймером, не создаёт приложения агента. Читает последние 300 событий, изменения id/status/batch_id и сохранённые HTTP_BATCH, summary раз в минуту. Это не полный аудит. Одна копия, остановить после диагностики. Документ scripts/utils/QUEUE_DEBUG.md.
Логи утилиты содержат полный payload/IP/имена, автоматического обезличивания нет; ограничьте доступ. Не считайте PRAGMA query_only эквивалентом файлового read-only открытия на любой SQLite-сборке.

## Обновление/откат
1. Остановить прежние Collector/Sender и диагностические таймеры проверенным способом.
2. Сохранить локальный конфиг, секреты и согласованную копию SQLite после остановки работы с ней.
3. Заменить только нужные исходники и содержимое серверных SDK-точек входа. Не затереть рабочие настройки корневым пилотным config.json.
4. Текущий Collector делает reload core -> features -> inventory -> unified_snapshot -> device_snapshot, затем новый app. Это не отменяет прежние подписки. Разные интерпретаторы обновляются отдельно.
5. Проверить несколько локальных снимков с Sender=false, затем доставку/повторы. Не пересоздавать БД для обычного обновления.
6. При откате учитывать версии накопленных событий и совместимость приёмника; автоматических миграций/перепаковки пакетов нет.

## Диск и приёмка
retention_days применяется только к delivered; 0 отключает удаление. Очистка примерно раз в час при включённом Sender, до 100 старых пакетов за проход. Pending/quarantine не очищаются по возрасту. Квоты БД нет; мониторьте размер/свободное место/возраст очереди. DELETE не уменьшает файл; VACUUM отдельно на остановленной установке с запасом места.
До тиражирования проверить фактические Python/SQLite/SSL/SDK, несколько циклов и многокомпонентные снимки, отключение камеры/восстановление, ошибочные поля и привязку сервера, TLS/токен/не-200, потерю ответа, перезапуск после POST, блокировки/полный диск/ротацию. Пилот подтверждает локальный сбор; полная транспортная отказоустойчивость ещё требует отдельной проверки.
