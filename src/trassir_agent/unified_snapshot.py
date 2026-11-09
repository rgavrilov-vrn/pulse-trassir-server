# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import threading
import time
import uuid
from .core import CollectorApplication as BaseCollector, utc
from .features import Snapshot, SdkEventFactory, HEALTH_FIELDS, options as feature_options
from .inventory import ObjectsSnapshotCollector, sdk_text

CHANNEL_FIELDS = {
    'signal': ('flags', 'signal'),
    'recording_local': ('flags', 'recording_local'),
    'recording_hw': ('flags', 'recording_hw'),
    'fps_main': ('stats', 'fps_main'),
    'kbps_main': ('stats', 'kbps_main'),
    'grabber_error': ('info', 'grabber_error'),
}
STATE_FIELDS = {
    'IP Device': ['connection', 'hdd'],
    'Script': ['health', 'check_me'],
    'Script (Local)': ['state'],
    'Template': ['state', 'shared'],
    'Folder': ['folder'], 'FolderH': ['folder'],
}

def snapshot_options(config):
    section = config.get('objects_snapshot', {})
    if not isinstance(section, dict):
        raise ValueError('objects_snapshot must be an object')
    enabled = section.get('enabled', False)
    interval = section.get('interval_seconds', 60)
    server_fields = section.get('server_health_fields', config.get('health', {}).get('fields', list(HEALTH_FIELDS)))
    channel_fields = section.get('channel_fields', config.get('objects_health', {}).get('fields', sorted(CHANNEL_FIELDS)))
    local_guid = section.get('local_server_guid')
    if type(enabled) is not bool or type(interval) is not int or not 10 <= interval <= 86400:
        raise ValueError('Invalid snapshot schedule')
    for fields, allowed in ((server_fields, HEALTH_FIELDS), (channel_fields, CHANNEL_FIELDS)):
        if not isinstance(fields, list) or not fields or any(field not in allowed for field in fields):
            raise ValueError('Unsupported snapshot fields')
        if len(fields) != len(set(fields)):
            raise ValueError('Duplicate field')
    if local_guid is not None and not sdk_text(local_guid):
        raise ValueError('Empty local_server_guid')
    return {'enabled': enabled, 'interval_seconds': interval, 'local_server_guid': local_guid,
            'server_health_fields': list(server_fields), 'channel_fields': list(channel_fields)}

class V2Factory(object):
    def __init__(self, factory):
        self.factory = factory
    def create(self, kind, data):
        event = self.factory.create('agent.objects_snapshot', data)
        event['event_version'] = '2.0'
        return event

class UnifiedSnapshotCollector(ObjectsSnapshotCollector):
    def __init__(self, list_objects, settings_function, object_function):
        ObjectsSnapshotCollector.__init__(self, list_objects)
        self.settings_function, self.object_function = settings_function, object_function
        self.option = snapshot_options({})
    def collect(self):
        started = utc()
        objects, errors, ids, counts, raw_guids = [], [], set(), {}, {}
        failed = 0
        try:
            rows = list(self.list_objects(''))
        except Exception as error:
            rows = []
            errors.append({'stage': 'enumeration', 'error_type': type(error).__name__})
        for index, row in enumerate(rows):
            try:
                if not isinstance(row, (list, tuple)) or len(row) != 4:
                    raise ValueError('Invalid object tuple')
                name, raw_guid, cls, parent = row
                guid, cls = sdk_text(raw_guid), sdk_text(cls)
                if not guid or guid in ids:
                    raise ValueError('Empty or duplicate GUID')
                obj = {'object_id': guid, 'name': sdk_text(name), 'class_name': cls,
                       'parent_id': sdk_text(parent, True), 'values': {}, 'collection_errors': []}
                ids.add(guid)
                raw_guids[guid] = raw_guid
                counts[cls] = counts.get(cls, 0) + 1
                objects.append(obj)
            except Exception as error:
                failed += 1
                if len(errors) < 20:
                    errors.append({'stage': 'row', 'row_index': index, 'error_type': type(error).__name__})
        inventory_complete = not errors and failed == 0
        servers = [obj['object_id'] for obj in objects if obj['class_name'] == 'Server']
        local_guid = self.option['local_server_guid']
        if local_guid is None and len(servers) == 1:
            local_guid = servers[0]
        if local_guid not in servers:
            local_guid = None
            errors.append({'stage': 'server_binding', 'error_type': 'LocalServerNotResolved'})
        field_errors = 0
        for obj in objects:
            guid, cls = obj['object_id'], obj['class_name']
            folders, folder_errors = {}, {}
            def folder(path):
                if path in folder_errors:
                    raise folder_errors[path]
                if path not in folders:
                    try:
                        folders[path] = self.settings_function(str(path))
                    except Exception as error:
                        folder_errors[path] = error
                        raise
                return folders[path]
            def read(field, getter):
                obj['values'][field] = None
                try:
                    converter = Snapshot()
                    obj['values'][field] = converter.convert(getter(), field)
                    if converter.result['truncated']:
                        obj['collection_errors'].append({'field': field, 'error_type': 'ValueLimited'})
                except Exception as error:
                    obj['collection_errors'].append({'field': field, 'error_type': type(error).__name__})
            if cls == 'Server' and guid == local_guid:
                for field in self.option['server_health_fields']:
                    read(field, lambda field=field: folder('health')[str(field)])
            elif cls == 'Channel':
                for field in self.option['channel_fields']:
                    group, key = CHANNEL_FIELDS[field]
                    path = 'channels/' + guid + '/' + group
                    read(field, lambda path=path, key=key: folder(path)[str(key)])
            elif cls in STATE_FIELDS:
                def sdk_object():
                    if 'object' in folder_errors:
                        raise folder_errors['object']
                    if 'object' not in folders:
                        try:
                            folders['object'] = self.object_function(raw_guids[guid])
                        except Exception as error:
                            folder_errors['object'] = error
                            raise
                    return folders['object']
                for field in STATE_FIELDS[cls]:
                    read(field, lambda field=field: sdk_object().state(str(field)))
            if cls == 'Server' and local_guid is None:
                obj['collection_errors'].append({'field': '*', 'error_type': 'LocalServerNotResolved'})
            obj['observed_at'] = utc()
            obj['collection_complete'] = not obj['collection_errors']
            field_errors += len(obj['collection_errors'])
        objects.sort(key=lambda obj: obj['object_id'])
        enrichment_complete = local_guid is not None and field_errors == 0
        requested = dict((cls, list(fields)) for cls, fields in STATE_FIELDS.items())
        requested['Channel'] = list(self.option['channel_fields'])
        requested['Server'] = list(self.option['server_health_fields'])
        metadata = {'snapshot_id': str(uuid.uuid4()), 'scope': 'sdk_visible', 'snapshot_atomic': False,
                    'collection_started_at': started, 'collection_finished_at': utc(),
                    'sdk_rows_count': len(rows), 'objects_count': len(objects), 'counts_by_class': counts,
                    'failed_rows_count': failed, 'field_errors_count': field_errors,
                    'local_server_guid': local_guid, 'visible_server_guids': sorted(servers),
                    'requested_fields_by_class': requested,
                    'inventory_complete': inventory_complete, 'enrichment_complete': enrichment_complete,
                    'collection_complete': inventory_complete and enrichment_complete, 'collection_errors': errors}
        return metadata, objects
    def events(self, factory, config, option):
        self.option = option
        return ObjectsSnapshotCollector.events(self, V2Factory(factory), config)

class CollectorApplication(BaseCollector):
    # Наследуем только core: старые циклы health/inventory/states не запускаются.
    def __init__(self, path, settings_function, list_objects, object_function):
        self._callback_lock = threading.RLock()
        self._snapshot_options = snapshot_options({})
        self._features = feature_options({})
        self._snapshot_error = None
        self._snapshot_at = 0
        BaseCollector.__init__(self, path)
        self.factory = SdkEventFactory(lambda: self._features)
        self.unified_snapshot = UnifiedSnapshotCollector(list_objects, settings_function, object_function)
        self.refresh()
    def refresh(self):
        config = BaseCollector.refresh(self)
        try:
            candidate = snapshot_options(config)
            features = feature_options({'raw_sdk': config.get('raw_sdk', {})})
        except Exception as error:
            name = type(error).__name__
            if name != self._snapshot_error:
                self.logger.error('Unified snapshot settings rejected: %s; previous settings retained', name)
            self._snapshot_error = name
        else:
            if candidate != self._snapshot_options:
                self._snapshot_at = 0
            self._snapshot_options, self._features = candidate, features
            self._snapshot_error = None
        return config
    def on_event(self, event):
        with self._callback_lock:
            return BaseCollector.on_event(self, event)
    def tick(self):
        with self._callback_lock:
            try:
                BaseCollector.tick(self)
            except Exception:
                self.logger.exception('Base collector failed before unified snapshot')
            config, option = self.config.value, self._snapshot_options
            if not config['collector']['enabled'] or not option['enabled'] or time.time() < self._snapshot_at:
                return
            self._snapshot_at = time.time() + option['interval_seconds']
            try:
                events = self.unified_snapshot.events(self.factory, config, option)
                for event in events:
                    self.save(event)
                data = events[0]['data']
                self.logger.info('Unified snapshot saved: id=%s objects=%s parts=%s errors=%s inventory=%s complete=%s',
                                 data['snapshot_id'], data['objects_count'], len(events), data['field_errors_count'],
                                 data['inventory_complete'], data['collection_complete'])
            except Exception:
                self.logger.exception('Unified snapshot failed; partial snapshot must not replace state')
