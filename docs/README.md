# Документация проекта

## Основные актуальные документы
1. [README проекта](../README.md): назначение, структура, быстрый запуск.
2. [CONTRACT.md](CONTRACT.md): HTTP contract_version=1.0, события, единый objects_snapshot/2.0, values, части/полнота/связи, требования к приёмнику.
3. [ARCHITECTURE.md](ARCHITECTURE.md): реальная цепочка Collector, SQLite/JSONL, Sender, retry/lease, ограничения.
4. [OPERATIONS.md](OPERATIONS.md): конфиг, обновления, диагностика, ручная приёмка.

При расхождении описаний предыдущих этапов с этими документами для текущих scripts/collector.py и scripts/sender.py используйте основные документы и фактический код. Обновление документации не меняет код, конфиг, версии очереди или точки входа.

## Уточняющие заметки текущего развития
- [UNIFIED_SNAPSHOT_V2.md](UNIFIED_SNAPSHOT_V2.md): первый этап объединения. Порядок запуска и полный текущий состав с паспортом смотрите в основных документах.
- [DEVICE_PASSPORT_LINKS.md](DEVICE_PASSPORT_LINKS.md): паспорт, выбранные channelXX_guid и обратные ссылки.

## Исторические документы раздельных сборщиков
HEALTH_RAW.md, OBJECTS_SNAPSHOT.md, OBJECTS_HEALTH.md, OBJECT_STATES.md, MONITORING_PROFILES.md описывают промежуточные версии и старые отдельные типы событий/конфиги. Они сохранены для анализа истории и совместимости очереди, но не являются инструкцией включения текущего объединённого Collector. В частности, старое утверждение об отсутствии health/камер больше не актуально; разделение values на states/metrics не используется.

## Утилиты
- [Перезагрузка модулей](../scripts/utils/README.md), scripts/utils/reload_modules.py.
- [Диагностика очереди](../scripts/utils/QUEUE_DEBUG.md), scripts/utils/queue_debug.py.

Полный config.json в корне — пилотный video81 с выключенным Sender. config/*.example.json — примеры разных этапов, не универсальная замена рабочего файла. Значения производственной доставки/секретов и локальные изменения нельзя затирать при обновлении.
