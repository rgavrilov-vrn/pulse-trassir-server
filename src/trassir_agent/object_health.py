# -*- coding: utf-8 -*-
# Состояние каналов отдельно от перечня объектов и серверного health.
from __future__ import unicode_literals
import time
import uuid
from .core import utc
from .features import Snapshot
from .inventory import CollectorApplication as InventoryCollector
from .inventory import ObjectsSnapshotCollector, sdk_text

FIELDS = {
    'signal': ('flags', 'signal'),
    'recording_local': ('flags', 'recording_local'),
    'recording_hw': ('flags', 'recording_hw'),
    'fps_main': ('stats', 'fps_main'),
    'kbps_main': ('stats', 'kbps_main'),
    'grabber_error': ('info', 'grabber_error'),
}
DEFAULT_FIELDS = ['signal', 'recording_local', 'recording_hw', 'fps_main', 'kbps_main', 'grabber_error']

def health_options(config):
    section = config.get('objects_health', {})
    if not isinstance(section, dict):
        raise ValueError('objects_health must be an object')
    enabled = section.get('enabled', False)
    interval = section.get('interval_seconds', 60)
    fields = section.get('fields', list(DEFAULT_FIELDS))
    if type(enabled) is not bool:
        raise ValueError('objects_health.enabled must be boolean')
    if type(interval) is not int or not 10 <= interval <= 86400:
        raise ValueError('objects_health.interval_seconds must be 10..86400')
    if not isinstance(fields, list) or not fields or any(x not in DEFAULT_FIELDS for x in fields):
        raise ValueError('Unsupported objects_health.fields')
    if len(fields) != len(set(fields)):
        raise ValueError('Duplicate health field')
    return {'enabled': enabled, 'interval_seconds': interval, 'fields': list(fields)}

class HealthEventFactory(object):
    # Адаптер повторно использует проверенное разбиение inventory.events на части.
    # Изменяет только тип создаваемого события, не подписки и не глобальные классы.
    def __init__(self, factory):
        self.factory = factory
    def create(self, kind, data):
        return self.factory.create('agent.objects_health', data)

class ChannelHealthCollector(ObjectsSnapshotCollector):
    def __init__(self, list_objects, settings_function):
        ObjectsSnapshotCollector.__init__(self, list_objects)
        self.settings_function = settings_function
        self.fields = list(DEFAULT_FIELDS)
    def collect(self):
        started = utc()
        objects = []
        errors = []
        failed = 0
        metric_errors = 0
        try:
            # Читаем все видимые SDK каналы, не только каналы из предыдущего снимка.
            rows = list(self.list_objects('Channel'))
        except Exception as error:
            rows = []
            errors.append({'stage': 'enumeration', 'error_type': type(error).__name__})
        ids = set()
        for index, row in enumerate(rows):
            try:
                if not isinstance(row, (list, tuple)) or len(row) != 4:
                    raise ValueError('Invalid object tuple')
                name, guid, class_name, parent = row
                guid = sdk_text(guid)
                if not guid or '/' in guid or '\\' in guid or guid in ids:
                    raise ValueError('Invalid or duplicate channel GUID')
                class_name = sdk_text(class_name)
                if class_name != 'Channel':
                    raise ValueError('Unexpected class')
                obj = {'object_id': guid, 'name': sdk_text(name), 'class_name': class_name,
                       'parent_id': sdk_text(parent, True), 'metrics': {}, 'collection_errors': []}
                ids.add(guid)
            except Exception as error:
                failed += 1
                if len(errors) < 20:
                    errors.append({'stage': 'row', 'row_index': index, 'error_type': type(error).__name__})
                continue
            # Получаем flags/stats/info не более одного раза для каждого канала.
            folders = {}
            folder_errors = {}
            for field in self.fields:
                folder_name, key = FIELDS[field]
                obj['metrics'][field] = None
                try:
                    if folder_name in folder_errors:
                        raise folder_errors[folder_name]
                    if folder_name not in folders:
                        try:
                            folders[folder_name] = self.settings_function(str('channels/' + guid + '/' + folder_name))
                        except Exception as error:
                            folder_errors[folder_name] = error
                            raise
                    value = folders[folder_name][str(key)]
                    snapshot = Snapshot()
                    obj['metrics'][field] = snapshot.convert(value, field)
                    if snapshot.result['truncated']:
                        obj['collection_errors'].append({'field': field, 'error_type': 'ValueLimited'})
                except Exception as error:
                    # Недоступное поле остаётся null. Текст ошибки не копируем: он может
                    # содержать чувствительные настройки или детали подключения.
                    obj['collection_errors'].append({'field': field, 'error_type': type(error).__name__})
            obj['observed_at'] = utc()
            obj['collection_complete'] = not obj['collection_errors']
            metric_errors += len(obj['collection_errors'])
            objects.append(obj)
        objects.sort(key=lambda obj: obj['object_id'])
        metadata = {
            'snapshot_id': str(uuid.uuid4()), 'collection_started_at': started,
            'collection_finished_at': utc(), 'snapshot_atomic': False,
            'scope': 'sdk_visible_channels', 'source': 'settings/channels',
            'sdk_rows_count': len(rows), 'objects_count': len(objects),
            'failed_rows_count': failed, 'metric_errors_count': metric_errors,
            'requested_fields': list(self.fields),
            'collection_complete': not errors and failed == 0 and metric_errors == 0,
            'collection_errors': errors,
        }
        return metadata, objects
    def events(self, factory, config, fields):
        self.fields = list(fields)
        # Встроенный сериализатор измеряет полный одиночный HTTP-пакет и сохраняет
        # snapshot_id/part_index/parts_total; нового механизма доставки здесь нет.
        return ObjectsSnapshotCollector.events(self, HealthEventFactory(factory), config)

class CollectorApplication(InventoryCollector):
    def __init__(self, path, settings_function, list_objects):
        self._objects_health_options = health_options({})
        self._objects_health_error = None
        self._objects_health_at = 0
        InventoryCollector.__init__(self, path, settings_function, list_objects)
        self.channel_health = ChannelHealthCollector(list_objects, settings_function)
    def refresh(self):
        config = InventoryCollector.refresh(self)
        try:
            candidate = health_options(config)
        except Exception as error:
            name = type(error).__name__
            if name != self._objects_health_error:
                self.logger.error('Objects health settings rejected: %s; previous settings retained', name)
            self._objects_health_error = name
        else:
            if candidate != self._objects_health_options:
                self._objects_health_at = 0
            self._objects_health_options = candidate
            self._objects_health_error = None
        return config
    def tick(self):
        with self._callback_lock:
            try:
                InventoryCollector.tick(self)
            except Exception:
                self.logger.exception('Collector tick failed before channel health')
            config = self.config.value
            option = self._objects_health_options
            if not config['collector']['enabled'] or not option['enabled']:
                return
            if time.time() < self._objects_health_at:
                return
            self._objects_health_at = time.time() + option['interval_seconds']
            try:
                events = self.channel_health.events(self.factory, config, option['fields'])
                for event in events:
                    self.save(event)
                data = events[0]['data']
                self.logger.info('Objects health saved: id=%s channels=%s parts=%s metric_errors=%s complete=%s',
                                 data['snapshot_id'], data['objects_count'], len(events),
                                 data['metric_errors_count'], data['collection_complete'])
            except Exception:
                self.logger.exception('Objects health failed; incomplete snapshot must not replace state')
