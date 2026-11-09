# -*- coding: utf-8 -*-
# Раздельные read-only профили с разной частотой: потоки, архив, паспорт устройств.
from __future__ import unicode_literals
import time
import uuid
from .core import utc
from .features import Snapshot
from .inventory import ObjectsSnapshotCollector, sdk_text
from .object_health import CollectorApplication as PreviousCollector

SPECS = {
    'channels_extended': {
        'class': 'Channel', 'prefix': 'channels', 'interval': 60,
        'event': 'agent.objects_health', 'version': '1.1',
        'fields': {
            'signal': ('flags', 'signal'),
            'recording_local': ('flags', 'recording_local'),
            'recording_hw': ('flags', 'recording_hw'),
            'fps_main': ('stats', 'fps_main'),
            'kbps_main': ('stats', 'kbps_main'),
            'fps_ss': ('stats', 'fps_ss'),
            'kbps_ss': ('stats', 'kbps_ss'),
            'grabber_error': ('info', 'grabber_error'),
            'record_mode_local': ('', 'record_mode_local'),
            'health_ignore': ('', 'health_ignore'),
        }
    },
    'channel_archive': {
        'class': 'Channel', 'prefix': 'channels', 'interval': 600,
        'event': 'agent.objects_health', 'version': '1.1',
        'fields': {
            'mainstream_depth': ('arch_stats', 'mainstream_depth'),
            'substream_depth': ('arch_stats', 'substream_depth'),
        }
    },
    'ip_devices': {
        'class': 'IP Device', 'prefix': 'ip_cameras', 'interval': 900,
        'event': 'agent.devices_snapshot', 'version': '1.0',
        'fields': {
            'family': ('', 'family'),
            'model': ('', 'model'),
            'connection_ip': ('', 'connection_ip'),
            'connection_port': ('', 'connection_port'),
            'grabber_enabled': ('', 'grabber_enabled'),
            'channels_enabled': ('', 'channels_enabled'),
            'economy_mode': ('', 'economy_mode'),
            'have_working_hdd': ('', 'have_working_hdd'),
        }
    },
}

def profile_options(config):
    section = config.get('monitoring_profiles', {})
    if not isinstance(section, dict):
        raise ValueError('monitoring_profiles must be an object')
    if any(name not in SPECS for name in section):
        raise ValueError('Unknown monitoring profile')
    result = {}
    for name, spec in SPECS.items():
        option = section.get(name, {})
        if not isinstance(option, dict):
            raise ValueError('Profile must be an object')
        enabled = option.get('enabled', False)
        interval = option.get('interval_seconds', spec['interval'])
        fields = option.get('fields', sorted(spec['fields']))
        if type(enabled) is not bool or type(interval) is not int or not 10 <= interval <= 86400:
            raise ValueError('Invalid profile schedule')
        if not isinstance(fields, list) or not fields:
            raise ValueError('Profile fields must be a nonempty list')
        if any(field not in spec['fields'] for field in fields):
            raise ValueError('Unsupported field')
        if len(fields) != len(set(fields)):
            raise ValueError('Duplicate field')
        result[name] = {'enabled': enabled, 'interval_seconds': interval, 'fields': list(fields)}
    return result

class ProfileEventFactory(object):
    # Адаптер задаёт тип/версию и сохраняет общий алгоритм разбиения на части.
    def __init__(self, factory, spec):
        self.factory, self.spec = factory, spec
    def create(self, kind, data):
        event = self.factory.create(self.spec['event'], data)
        event['event_version'] = self.spec['version']
        return event

class ProfileCollector(ObjectsSnapshotCollector):
    def __init__(self, list_objects, settings_function, profile):
        ObjectsSnapshotCollector.__init__(self, list_objects)
        self.settings_function = settings_function
        self.profile = profile
        self.spec = SPECS[profile]
        self.fields = []
    def collect(self):
        started = utc()
        objects, errors, ids = [], [], set()
        failed, metric_errors = 0, 0
        try:
            rows = list(self.list_objects(str(self.spec['class'])))
        except Exception as error:
            rows = []
            errors.append({'stage': 'enumeration', 'error_type': type(error).__name__})
        for index, row in enumerate(rows):
            try:
                if not isinstance(row, (tuple, list)) or len(row) != 4:
                    raise ValueError('Invalid object tuple')
                name, guid, cls, parent = row
                guid, cls = sdk_text(guid), sdk_text(cls)
                if not guid or '/' in guid or '\\' in guid or guid in ids or cls != self.spec['class']:
                    raise ValueError('Invalid object identity')
                obj = {'object_id': guid, 'name': sdk_text(name), 'class_name': cls,
                       'parent_id': sdk_text(parent, True), 'metrics': {}, 'collection_errors': []}
                ids.add(guid)
            except Exception as error:
                failed += 1
                if len(errors) < 20:
                    errors.append({'stage': 'row', 'row_index': index, 'error_type': type(error).__name__})
                continue
            folders = {}
            folder_errors = {}
            for field in self.fields:
                folder, key = self.spec['fields'][field]
                obj['metrics'][field] = None
                try:
                    if folder in folder_errors:
                        raise folder_errors[folder]
                    if folder not in folders:
                        path = self.spec['prefix'] + '/' + guid
                        if folder:
                            path += '/' + folder
                        try:
                            folders[folder] = self.settings_function(str(path))
                        except Exception as error:
                            folder_errors[folder] = error
                            raise
                    snapshot = Snapshot()
                    obj['metrics'][field] = snapshot.convert(folders[folder][str(key)], field)
                    if snapshot.result['truncated']:
                        obj['collection_errors'].append({'field': field, 'error_type': 'ValueLimited'})
                except Exception as error:
                    obj['collection_errors'].append({'field': field, 'error_type': type(error).__name__})
            obj['observed_at'] = utc()
            obj['collection_complete'] = not obj['collection_errors']
            metric_errors += len(obj['collection_errors'])
            objects.append(obj)
        objects.sort(key=lambda obj: obj['object_id'])
        data = {'snapshot_id': str(uuid.uuid4()), 'profile': self.profile,
                'collection_started_at': started, 'collection_finished_at': utc(),
                'snapshot_atomic': False, 'scope': 'sdk_visible_class',
                'object_class': self.spec['class'], 'source': 'settings/' + self.spec['prefix'],
                'sdk_rows_count': len(rows), 'objects_count': len(objects),
                'failed_rows_count': failed, 'metric_errors_count': metric_errors,
                'requested_fields': list(self.fields), 'collection_errors': errors,
                'collection_complete': not errors and failed == 0 and metric_errors == 0}
        return data, objects
    def events(self, factory, config, fields):
        self.fields = list(fields)
        return ObjectsSnapshotCollector.events(self, ProfileEventFactory(factory, self.spec), config)

class CollectorApplication(PreviousCollector):
    def __init__(self, path, settings_function, list_objects):
        self._profile_options = profile_options({})
        self._profile_error = None
        self._profile_at = dict((name, 0) for name in SPECS)
        PreviousCollector.__init__(self, path, settings_function, list_objects)
        self.profile_collectors = dict((name, ProfileCollector(list_objects, settings_function, name)) for name in SPECS)
    def refresh(self):
        config = PreviousCollector.refresh(self)
        try:
            candidate = profile_options(config)
        except Exception as error:
            name = type(error).__name__
            if name != self._profile_error:
                self.logger.error('Monitoring profiles rejected: %s; previous profile settings retained', name)
            self._profile_error = name
        else:
            for name in SPECS:
                if candidate[name] != self._profile_options[name]:
                    self._profile_at[name] = 0
            self._profile_options = candidate
            self._profile_error = None
        return config
    def tick(self):
        with self._callback_lock:
            try:
                PreviousCollector.tick(self)
            except Exception:
                self.logger.exception('Collector failed before monitoring profiles')
            config = self.config.value
            if not config['collector']['enabled']:
                return
            for name in sorted(SPECS):
                option = self._profile_options[name]
                if not option['enabled'] or time.time() < self._profile_at[name]:
                    continue
                self._profile_at[name] = time.time() + option['interval_seconds']
                try:
                    events = self.profile_collectors[name].events(self.factory, config, option['fields'])
                    for event in events:
                        self.save(event)
                    data = events[0]['data']
                    self.logger.info('Profile saved: profile=%s objects=%s parts=%s errors=%s complete=%s',
                                     name, data['objects_count'], len(events), data['metric_errors_count'], data['collection_complete'])
                except Exception:
                    self.logger.exception('Profile failed: %s', name)
