# Состояние каналов: agent.objects_health

## Назначение
Отдельный периодический снимок состояния всех Channel, видимых objects_list('Channel'). Инвентаризация agent.objects_snapshot, серверный trassir.health и обычные события остаются независимыми. Универсальный object.health не предполагается. IP Device, Script и Folder этим адаптером не опрашиваются.

## Настройки
В полный локальный config.json добавьте раздел objects_health из config/objects_health.example.json. Пример сам не читается и не заменяет рабочий конфиг. enabled=true, interval_seconds=60, fields содержит шесть выбранных метрик. Без раздела сбор выключен. Интервал 10..86400 секунд. enabled/период/fields применяются динамически; неверное обновление оставляет предыдущие настройки этого расширения. Включение или изменение настроек запускает сбор на ближайшем tick. Collector.enabled=false выключает и этот опрос.

## SDK-пути
Для каждого GUID Channel читаются settings('channels/<GUID>/flags') для signal/recording_local/recording_hw, settings('channels/<GUID>/stats') для fps_main/kbps_main и settings('channels/<GUID>/info') для grabber_error. Получение folders и значений read-only. Формат objects_list('Channel') подтверждён на сервере; доступность этих settings-полей предстоит проверить в вашей сборке. Ошибка чтения не означает offline: сохраняется null и collection_errors с именем поля и типом исключения. Отрицательные значения и строковые числа автоматически не интерпретируются. Нулевой флаг записи без знания расписания НЕ является аварией. Настройки и пароли устройства не выгружаются.

## Контракт
Тип agent.objects_health, event_version=1.0, HTTP contract_version=1.0. Общее source события пустое, server_id находится в обёртке пакета. Data: snapshot_id, collection_started_at, collection_finished_at, snapshot_atomic=false, scope=sdk_visible_channels, source=settings/channels, sdk_rows_count, objects_count, failed_rows_count, metric_errors_count, requested_fields, collection_complete, collection_errors, part_index, parts_total, objects. Счётчики относятся ко всему снимку, а не части.
Каждый objects[] содержит object_id, name, class_name=Channel, parent_id, observed_at, metrics, collection_complete, collection_errors. Все запрошенные ключи metrics присутствуют, при ошибке значение null. Ошибки одного канала не отменяют остальные. collection_complete снимка true только при успешном перечислении/разборе и отсутствии ошибок метрик. Ограничение строк/вложенности берётся из Snapshot; ValueLimited отмечает усечение/неподдерживаемое значение. raw_sdk здесь не добавляется.

## Разбиение и приём
Повторно используется разбиение инвентаризации: до min(64 КиБ, sender.max_batch_bytes) на одиночный пакет. Один snapshot_id для всех частей, отдельный event_id каждой части, part_index с 1. Все части строятся до первой записи, затем сохраняются обычным self.save: COMMIT SQLite и одна best-effort попытка JSONL. Частичная запись/доставка возможна. Приёмник собирает все части, дедуплицирует server_id+event_id, не заменяет более новый снимок старым. Неполный снимок не означает удаление каналов, отсутствие значения не означает ноль. При ошибках метрик можно показывать успешно прочитанные поля, но не объявлять весь снимок здоровым. Ответ приёмника — HTTP 200 за весь пакет, отдельного ACK нет.

## Установка обновления
1. Остановите оба SDK-скрипта проверенным способом, сохраните рабочие данные.
2. Добавьте object_health.py рядом с актуальными core.py, features.py, inventory.py.
3. Замените содержимое Collector новым scripts/collector.py: импорт теперь из object_health.
4. Добавьте новый раздел в локальный config.json, не меняя server_id/URL/storage.
5. Загрузите новые модули в порядке core -> features -> inventory -> object_health при остановленных обработчиках, затем создайте новый app. Reload сам не отменяет старые подписки.
6. Сначала проверьте JSONL и collector.log с выключенным Sender. Не пересоздавайте БД.

## Проверка и ограничения
В collector.log ищите Objects health saved: channels=82 (или текущее число), parts, metric_errors, complete. В events.jsonl ищите agent.objects_health и ошибки отдельных полей. После первого пилотного снимка проверьте значения на исправном/проблемном канале в интерфейсе TRASSIR.
Опрос синхронный и последовательный, снимок не атомарен; RLock сериализует SDK-callback Collector. Время большого опроса может задерживать приём событий; нет жёсткого deadline SDK-getter. Этот этап не добавляет глубину архива, второй поток или правила инцидентов. Отдельные следующие задачи: проверка режимов записи, привязка IP Device к Channel и нормализация специальных значений. Существующая проблема sqlite3.Row/Unicode в Sender этим модулем не исправляется. Проверка сбора не равна проверке HTTP-доставки.
