# -*- coding: utf-8 -*-
# Инвентаризация использует подтверждённый на сервере objects_list("").
from __future__ import unicode_literals
import time
import uuid
from .core import dumps, utc
from .features import CollectorApplication as FeatureCollector
try:
    TEXT = unicode
    STRINGS = basestring
except NameError:
    TEXT = str
    STRINGS = str

def inventory_options(config):
    section = config.get('objects_snapshot', {})
    if not isinstance(section, dict):
        raise ValueError('objects_snapshot must be an object')
    enabled = section.get('enabled', False)
    interval = section.get('interval_seconds', 300)
    if type(enabled) is not bool:
        raise ValueError('objects_snapshot.enabled must be boolean')
    if type(interval) is not int or not 10 <= interval <= 86400:
        raise ValueError('objects_snapshot.interval_seconds must be 10..86400')
    return {'enabled': enabled, 'interval_seconds': interval}

def sdk_text(value, nullable=False):
    # В Python 2 имена объектов приходят байтовыми UTF-8 строками.
    # Ошибки декодирования не скрываем: строка будет отмечена как непрочитанная.
    if value is None and nullable:
        return None
    if isinstance(value, bytes):
        return value.decode('utf-8')
    if isinstance(value, STRINGS):
        return value
    raise ValueError('Unexpected object field type')

class ObjectsSnapshotCollector(object):
    def __init__(self, list_objects):
        # SDK-функция приходит явно из серверного скрипта.
        self.list_objects = list_objects
    def collect(self):
        started = utc()
        objects = []
        errors = []
        failed = 0
        rows_count = 0
        try:
            rows = list(self.list_objects(''))
            rows_count = len(rows)
        except Exception as error:
            rows = []
            errors.append({'stage': 'enumeration', 'error_type': type(error).__name__})
        counts = {}
        ids = set()
        servers = []
        for index, row in enumerate(rows):
            try:
                if not isinstance(row, (list, tuple)) or len(row) != 4:
                    raise ValueError('Expected name,guid,class,parent tuple')
                name, guid, class_name, parent = row
                obj = {'object_id': sdk_text(guid), 'name': sdk_text(name),
                       'class_name': sdk_text(class_name), 'parent_id': sdk_text(parent, True)}
                if not obj['object_id'] or obj['object_id'] in ids:
                    raise ValueError('Empty or duplicate object id')
                ids.add(obj['object_id'])
                objects.append(obj)
                counts[obj['class_name']] = counts.get(obj['class_name'], 0) + 1
                if obj['class_name'] == 'Server':
                    servers.append(obj['object_id'])
            except Exception as error:
                failed += 1
                # Ограничиваем только диагностику, не число собираемых объектов.
                if len(errors) < 20:
                    errors.append({'stage': 'row', 'row_index': index, 'error_type': type(error).__name__})
        objects.sort(key=lambda obj: obj['object_id'])
        metadata = {'snapshot_id': str(uuid.uuid4()),
                    'collection_started_at': started, 'collection_finished_at': utc(),
                    'snapshot_atomic': False, 'scope': 'sdk_visible',
                    'sdk_rows_count': rows_count, 'objects_count': len(objects),
                    'failed_rows_count': failed, 'counts_by_class': counts,
                    'visible_server_guids': servers,
                    'collection_complete': not errors and failed == 0,
                    'collection_errors': errors}
        return metadata, objects
    def events(self, factory, config):
        metadata, objects = self.collect()
        # Верхняя оценка числа частей: максимум одна запись на часть.
        # Используем её при измерении, чтобы финальные номера не увеличили размер.
        upper = max(1, len(objects))
        limit = min(65536, config['sender']['max_batch_bytes'])
        def make_event(items, index, total):
            data = dict(metadata)
            data.update({'part_index': index, 'parts_total': total, 'objects': items})
            return factory.create('agent.objects_snapshot', data)
        def packet_size(event):
            # Измеряем полный одиночный пакет той же формы, что строит Sender.
            packet = {'contract': 'trassir.telemetry', 'contract_version': '1.0',
                      'batch_id': '00000000-0000-0000-0000-000000000000',
                      'sent_at': utc(), 'producer': {'name': 'trassir-sdk-agent', 'version': '1.0.0'},
                      'server': {'server_id': config['server_id']}, 'events': [event]}
            return len(dumps(packet).encode('utf-8'))
        chunks = []
        current = []
        for obj in objects:
            candidate = current + [obj]
            if packet_size(make_event(candidate, upper, upper)) > limit:
                if not current:
                    raise ValueError('Object or metadata exceeds snapshot packet limit')
                chunks.append(current)
                current = [obj]
                if packet_size(make_event(current, upper, upper)) > limit:
                    raise ValueError('Single object exceeds snapshot packet limit')
            else:
                current = candidate
        if current or not chunks:
            chunks.append(current)
        result = [make_event(items, index+1, len(chunks)) for index, items in enumerate(chunks)]
        # Все части строятся и проверяются до первой записи в БД.
        if any(packet_size(event) > limit for event in result):
            raise ValueError('Snapshot metadata exceeds packet limit')
        return result

class CollectorApplication(FeatureCollector):
    def __init__(self, path, settings_function, list_objects):
        self._inventory_options = inventory_options({})
        self._inventory_error = None
        self._inventory_at = 0
        FeatureCollector.__init__(self, path, settings_function)
        self.inventory = ObjectsSnapshotCollector(list_objects)
    def refresh(self):
        config = FeatureCollector.refresh(self)
        try:
            candidate = inventory_options(config)
        except Exception as error:
            name = type(error).__name__
            if name != self._inventory_error:
                self.logger.error('Object snapshot settings rejected: %s; previous settings retained', name)
            self._inventory_error = name
        else:
            if candidate != self._inventory_options:
                # Включение или изменение периода запускает новый отсчёт сразу.
                self._inventory_at = 0
            self._inventory_options = candidate
            self._inventory_error = None
        return config
    def tick(self):
        # Тот же RLock, что у health/raw_sdk: исключаем наложение callback Collector.
        with self._callback_lock:
            try:
                FeatureCollector.tick(self)
            except Exception:
                # Ошибка health не должна автоматически отменять инвентаризацию.
                self.logger.exception('Base collector tick failed before object snapshot')
            config = self.config.value
            setting = self._inventory_options
            if not config['collector']['enabled'] or not setting['enabled']:
                return
            if time.time() < self._inventory_at:
                return
            self._inventory_at = time.time() + setting['interval_seconds']
            try:
                events = self.inventory.events(self.factory, config)
                for event in events:
                    # Обычный путь: SQLite COMMIT, затем одна попытка JSONL.
                    self.save(event)
                data = events[0]['data']
                self.logger.info('Objects snapshot saved: id=%s objects=%s parts=%s complete=%s',
                                 data['snapshot_id'], data['objects_count'], len(events), data['collection_complete'])
            except Exception:
                # Если запись части не удалась, приёмник не должен применять неполный снимок.
                self.logger.exception('Objects snapshot failed; partial snapshot must not replace inventory')
