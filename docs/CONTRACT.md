# Контракт телеметрии

Актуальная реализация: scripts/collector.py -> device_snapshot -> unified_snapshot -> core; Sender/HTTP в core.py. Этот документ описывает текущую упаковку данных и требования к приёмнику. Сам приёмник в данном репозитории не реализован.

## 1. Независимые версии
| Уровень | Значение |
|---|---|
| HTTP contract / contract_version | trassir.telemetry / 1.0 |
| agent.objects_snapshot / event_version | 2.0 |
| trassir.system_event / event_version | 1.1 при raw_sdk.enabled=true, иначе 1.0 |
| agent.heartbeat, trassir.log_entry | event_version=1.0 |
| JSONL / config / SQLite schema | record_version=1 / config_version=1 / meta.schema=1 |

Версия приложения/producer не равна версии события. HTTP producer в текущем коде: trassir-sdk-agent/1.0.0. Переключение строки версии не меняет схему автоматически. Существующие пакеты/события не переписываются. Новые поля паспорта/связей добавлены к снимку 2.0 как настраиваемое дополнение, поэтому их отсутствие надо отличать от null/пустого значения.

## 2. HTTP-пакет
HTTPS POST на delivery.url. Content-Type: application/json; charset=utf-8. User-Agent: trassir-sdk-agent/1.0.0. Authorization: Bearer <токен> добавляется при заданном token_file; ASCII-токен читается из файла при каждой попытке. CA/имя узла проверяются через ssl.create_default_context, verify=False не используется.

Пример полного пакета с heartbeat, идентификаторы/время условные:
```json
{
  "contract": "trassir.telemetry",
  "contract_version": "1.0",
  "batch_id": "11111111-1111-4111-8111-111111111111",
  "sent_at": "2026-11-09T14:46:09.000Z",
  "producer": {"name": "trassir-sdk-agent", "version": "1.0.0"},
  "server": {"server_id": "video81"},
  "events": [{
    "event_id": "22222222-2222-4222-8222-222222222222",
    "event_type": "agent.heartbeat",
    "event_version": "1.0",
    "occurred_at": null,
    "observed_at": "2026-11-09T14:46:08.000Z",
    "source": {},
    "data": {"component": "collector"}
  }]
}
```

server_id — идентификатор установки из конфига, не SDK GUID. batch_id назначается при формировании пакета. sent_at — время его формирования, НЕ очередной сетевой попытки: при повторе сохраняются payload, UUID и sent_at. В одном HTTP-пакете могут быть события разных типов и части разных снимков.

Лимиты Sender: batch_size ограничивает число событий; max_batch_bytes — полный сериализованный JSON-пакет в UTF-8, включая оболочку. Событие, не помещающееся даже в одиночный пакет, переводится в quarantine.

## 3. Общая оболочка события
| Поле | Значение |
|---|---|
| event_id | UUID, назначается при сборе и сохраняется при повторах |
| event_type | Тип события |
| event_version | Версия структуры данного типа |
| occurred_at | Сейчас null; точное время исходного SDK-события не нормализовано |
| observed_at | UTC ISO-подобная строка с миллисекундами и Z, время создания события агентом |
| source | Объект источника, может быть пустым {} |
| data | Полезная нагрузка данного типа |

Вложенные observed_at у объектов и collection_started_at/finished_at относятся к чтению снимка, не к времени возникновения неисправности. Приёмник не должен подменять время нового измерения временем HTTP-повтора.

## 4. agent.objects_snapshot / 2.0
Полный перечень видимых объектов SDK, дополненный выбранными значениями. В data нет отдельных states/metrics/health, все значения в objects[].values. Серверный health — значения локального Server, отдельный trassir.health текущим Collector не создаётся.

### Метаданные data
| Поле | Смысл |
|---|---|
| snapshot_id | UUID общего логического снимка |
| scope | sdk_visible; область видимости зависит от SDK/установки |
| snapshot_atomic | false: чтение последовательное |
| collection_started_at, collection_finished_at | Начало/конец чтения, включая паспорт/связи |
| part_index, parts_total | Номер части от 1 и общее число частей |
| sdk_rows_count | Число строк общего objects_list |
| objects_count | Число принятых уникальных записей во ВСЁМ снимке |
| counts_by_class | Число принятых объектов по классам во ВСЁМ снимке |
| failed_rows_count | Число отвергнутых/дублирующихся строк перечня |
| field_errors_count | Число записей ошибок чтения/обработки полей у объектов |
| local_server_guid | SDK GUID сервера, к которому привязан локальный health; null при неразрешённой привязке |
| visible_server_guids | Видимые SDK GUID Server |
| requested_fields_by_class | Набор выбранных полей; Server относится только к local_server_guid |
| inventory_complete | Перечень получен без ошибок перечисления/строк |
| enrichment_complete | Успешная привязка сервера и отсутствие ошибок выбранных значений |
| collection_complete | inventory_complete AND enrichment_complete |
| collection_errors | Ошибки перечисления/строк/привязки; не замена ошибок объектов |
| device_channel_fields | Настроенные источники связей, например [channel00_guid] |
| device_links_scope | configured_channel_fields |
| device_links_complete | Успех чтения настроенных связей и отсутствие неоднозначных владельцев; null, если связи выключены |
| objects | Только записи, попавшие в данную часть |

Метаданные повторяются в частях. objects_count не равно длине objects одной части. field_errors_count может быть нулём при ошибке привязки без видимых Server; всегда проверяйте collection_errors и признаки полноты. device_links_complete не доказывает полного покрытия всех аппаратных слотов/каналов и не заменяет inventory_complete.

### Запись объекта
Пример IP Device с условным адресом и идентификаторами:
```json
{
  "object_id": "device-guid",
  "name": "Камера 1",
  "class_name": "IP Device",
  "parent_id": "devices-folder-guid",
  "observed_at": "2026-11-09T14:46:08.580Z",
  "collection_complete": true,
  "values": {
    "connection": "Connected",
    "hdd": "HDD Absent",
    "connection_ip": "192.0.2.10",
    "connection_port": 80,
    "family": "TRASSIR",
    "model": "Модель из SDK",
    "channel_ids": ["channel-guid"]
  },
  "collection_errors": []
}
```
object_id — SDK GUID, имя не ключ идентичности. parent_id — родитель в дереве; допускаются null и самоссылка корня. parent_id не связывает IP Device с Channel. Ключ состояния объекта на приёмнике: server_id + class_name + object_id.

### Наборы values
| Класс | Поля / источник |
|---|---|
| Server | Выбранные server_health_fields из settings(health), один локальный Server |
| Channel | signal, recording_local, recording_hw из flags; fps_main/kbps_main из stats; grabber_error из info; дополнительно ip_device_id |
| IP Device | connection/hdd из state(); выбранные connection_ip/connection_port/family/model из settings(ip_cameras/GUID); channel_ids из выбранных channelXX_guid |
| Script | health, check_me из state() |
| Script (Local) | state из state() |
| Template | state, shared из state() |
| Folder, FolderH | folder из state() |
| Другие классы | Пока values={} |

Пилотный Server-набор: server_ok, cpu_usage, gpu_usage, startup_ts, ip_devices_total, ip_devices_connected, channels_network_total, channels_network_online, db_connected, db_is_slow, db_last_error, disks_error_count, disks_is_slow, disks_last_error, disks_stat_main_days, disks_stat_subs_days, scripts_ok, scripts_total, network_really_connected, network_should_be_connected, network_last_error. Конфиг определяет фактическую выборку, не число из примера.

Сохраняются исходные JSON-типы. Строки 0/1 не преобразуются в bool/числа, пустая строка остаётся строкой, -1 не считается true, startup_ts не пересчитывается в дату. family — семейство/выбранный драйвер, не независимое доказательство производителя; модель может быть ошибочно выбрана.

Ошибка поля: values[field]=null и collection_errors=[{field,error_type}]. SDK None: null БЕЗ ошибки. Для связи дополнительно возможен source_field. Усечение/неподдерживаемое значение Snapshot помечается ValueLimited, объект и снимок неполны. Snapshot ограничивает строки 4096 UTF-8 байт, сложные контейнеры глубиной 3 и 50 элементами; поддержка контейнеров не означает, что SDK обязан возвращать их в конкретном поле.

collection_complete=true означает успешный сбор, НЕ исправность. Needs Attention, Model Mismatch, Disabled, HDD Absent, Any State — исходные значения, а не collection_errors. Неизвестное поле/класс не переводится в offline. Изменение requested_fields не означает исчезновение устройства или сброс старых показателей в ноль.

### Связи устройств и каналов
Читаются только явно настроенные device_channel_fields. В пилотном конфиге один channel00_guid; это не сканирование всех слотов устройства. Список общий для всех IP Device, неоднородные многоканальные устройства требуют дальнейшей настройки/адаптации.
У IP Device channel_ids — отсортированные уникальные GUID выбранных слотов. Пустая строка слота означает отсутствие ссылки; ошибка/нестроковое значение/ссылка на отсутствующий Channel -> channel_ids=null с ошибкой. У Channel ip_device_id — единственный найденный владелец. Несколько владельцев -> null/AmbiguousDeviceLink. При неполном чтении связей любого устройства обратные ссылки всех каналов остаются null/DeviceLinksIncomplete. Отсутствие владельца в настроенных слотах -> null без ошибки, это не доказательство отсутствия аппаратного устройства. Связи не угадываются по имени/порядку/родителю.

### Части и применение
Сборщик измеряет полный одиночный HTTP-пакет и ограничивает его min(65536, sender.max_batch_bytes). Объект не делится между частями. До записи в БД все части построены/проверены, но записываются отдельно: общий атомарный COMMIT всего снимка не реализован.
Приёмник группирует части по server_id + event_type + event_version + snapshot_id. Проверяет части 1..parts_total, согласованность метаданных/количеств и отсутствие дублирующихся объектов. Не применяет отдельную часть как полный перечень; устанавливает собственный срок ожидания неполных снимков. Части могут быть доставлены разными HTTP-пакетами/с повторами. event_id различен у частей, snapshot_id общий.
Полноту перечня и значений применяйте раздельно. Исчезновение объекта допустимо выводить только из полного перечня в сопоставимой SDK-области. Ошибка чтения не удаляет объект и не означает offline. Успешные данные/отметку неудачного чтения храните раздельно, старое значение не объявляйте свежим. Учитывайте время снимка: поздний retry старого пакета не должен откатить более новое состояние. Правила допустимого рассогласования часов и хранения истории определяет приёмник.

## 5. Другие события
agent.heartbeat/1.0: data={component:collector}. Только жизнь сборщика, не health видеосервера.
trassir.system_event/1.0: data содержит type,p1,p2,p3,timestamp_raw; source.object_id/object_name извлекаются из origin/origin_object при наличии. occurred_at=null, единицы ts не подтверждены. Нормализованные поля преобразуются scalar() в скаляры/текст.
При raw_sdk.enabled=true событие версии 1.1 дополнительно содержит TOP-LEVEL raw_sdk: attributes, unavailable_attributes, limitations, truncated. Поля выбирает конфиг. Без вызова методов/обхода произвольных объектов; лимиты Snapshot, общий размер диагностического блока 32 КиБ и не более 64 выбранных имён. Чувствительные имена атрибутов запрещены валидатором, однако разрешённые значения также могут быть конфиденциальными.
trassir.log_entry/1.0: data.source_id, level=null, message, chunked. Уровень не угадывается. Длинная строка может стать несколькими событиями; timestamp источника не парсится.

## 6. Подтверждение и повторы
Единственный успех — HTTP 200. Тело ответа НЕ читается/не проверяется. 201/202/204, 4xx/5xx и сетевые ошибки оставляют пакет на повтор. Приёмник должен отдавать 200 только после надёжного сохранения всех событий пакета, включая уже принятые дубликаты; при невозможности принять весь пакет — не 200. Это требование к приёмнику, не реализованная сервером гарантия.
Дедупликация: server_id + event_id; batch_id помогает распознавать повтор неизменного пакета, но не заменяет ключ события. Потерянный ответ/сбой после POST до локального COMMIT ведёт к повтору. Exactly-once не заявляется. Retry экспоненциальный с jitter +/-20%, итоговая задержка может превысить retry_max_seconds на 20%. Старейший pending-пакет блокирует новые. Ошибки авторизации/формата также повторяются до вмешательства оператора. Lease не исключает повторов при долгом зависании.

## 7. JSONL и миграция
Локальная строка JSONL имеет оболочку {record_version:1,event:<событие>}; это НЕ HTTP-пакет. Она создаётся после SQLite COMMIT, не содержит актуальный статус доставки и не импортируется обратно автоматически.
Приёмник на переходе должен принимать старый objects_snapshot/1.0, objects_health, objects_states, trassir.health и новый objects_snapshot/2.0, пока в очереди есть старые события. Схемы различаются по event_type/event_version, не только по наличию отдельных ключей. Неподдерживаемую версию нельзя подтверждать 200 с последующим молчаливым отбрасыванием. Приёмник может сохранять исходные данные без немедленной проекции, если надёжно принимает весь пакет.
