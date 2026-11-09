# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import math
import time
import uuid
from .core import utc
from .inventory import ObjectsSnapshotCollector, sdk_text
from .profiles import CollectorApplication as PreviousCollector

try:
    INTEGERS = (int, long)
except NameError:
    INTEGERS = (int,)

STATE_FIELDS = {
    'IP Device': ['connection', 'hdd'],
    'Script': ['health', 'check_me'],
    'Script (Local)': ['state'],
    'Template': ['state', 'shared'],
    'Folder': ['folder'],
    'FolderH': ['folder'],
}

def state_options(config):
    section = config.get('objects_states', {})
    if not isinstance(section, dict):
        raise ValueError('objects_states must be an object')
    if any(key not in ('enabled', 'interval_seconds', 'classes') for key in section):
        raise ValueError('Unknown objects_states option')
    enabled = section.get('enabled', False)
    interval = section.get('interval_seconds', 60)
    classes = section.get('classes', sorted(STATE_FIELDS))
    if type(enabled) is not bool or type(interval) is not int or not 10 <= interval <= 86400:
        raise ValueError('Invalid objects_states schedule')
    if not isinstance(classes, list) or not classes or any(cls not in STATE_FIELDS for cls in classes):
        raise ValueError('Unsupported objects_states classes')
    if len(classes) != len(set(classes)):
        raise ValueError('Duplicate class')
    return {'enabled': enabled, 'interval_seconds': interval, 'classes': sorted(classes)}

def pack_state(value):
    result = {'python_type': type(value).__name__}
    if value is None or isinstance(value, (bool,) + INTEGERS):
        result['value'] = value
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError('Nonfinite state')
        result['value'] = value
    else:
        text = sdk_text(value)
        result['value'] = text[:4096]
        result['truncated'] = len(text) > 4096
    return result

class StateEventFactory(object):
    def __init__(self, factory):
        self.factory = factory
    def create(self, kind, data):
        event = self.factory.create('agent.objects_states', data)
        event['event_version'] = '1.0'
        return event

class ObjectStatesCollector(ObjectsSnapshotCollector):
    def __init__(self, list_objects, object_function):
        ObjectsSnapshotCollector.__init__(self, list_objects)
        self.object_function = object_function
        self.classes = sorted(STATE_FIELDS)
    def collect(self):
        started = utc()
        objects, errors, ids, counts = [], [], set(), {}
        row_count, failed, state_errors = 0, 0, 0
        for cls in self.classes:
            counts[cls] = 0
            try:
                rows = list(self.list_objects(str(cls)))
                row_count += len(rows)
            except Exception as error:
                errors.append({'stage': 'enumeration', 'class_name': cls, 'error_type': type(error).__name__})
                continue
            for index, row in enumerate(rows):
                try:
                    if not isinstance(row, (list, tuple)) or len(row) != 4:
                        raise ValueError('Invalid object tuple')
                    name, raw_guid, actual_class, parent = row
                    guid = sdk_text(raw_guid)
                    if not guid or guid in ids or sdk_text(actual_class) != cls:
                        raise ValueError('Invalid object identity')
                    obj = {'object_id': guid, 'name': sdk_text(name), 'class_name': cls,
                           'parent_id': sdk_text(parent, True), 'states': {}, 'collection_errors': []}
                    ids.add(guid)
                except Exception as error:
                    failed += 1
                    if len(errors) < 20:
                        errors.append({'stage': 'row', 'class_name': cls, 'row_index': index,
                                       'error_type': type(error).__name__})
                    continue
                sdk_object, lookup_error = None, None
                try:
                    sdk_object = self.object_function(raw_guid)
                except Exception as error:
                    lookup_error = error
                for field in STATE_FIELDS[cls]:
                    obj['states'][field] = None
                    try:
                        if lookup_error is not None:
                            raise lookup_error
                        packed = pack_state(sdk_object.state(str(field)))
                        obj['states'][field] = packed
                        if packed.get('truncated', False):
                            obj['collection_errors'].append({'field': field, 'error_type': 'ValueLimited'})
                    except Exception as error:
                        obj['collection_errors'].append({'field': field, 'error_type': type(error).__name__})
                obj['observed_at'] = utc()
                obj['collection_complete'] = not obj['collection_errors']
                state_errors += len(obj['collection_errors'])
                counts[cls] += 1
                objects.append(obj)
        objects.sort(key=lambda obj: (obj['class_name'], obj['object_id']))
        data = {'snapshot_id': str(uuid.uuid4()), 'profile': 'sdk_states_v1',
                'collection_started_at': started, 'collection_finished_at': utc(),
                'snapshot_atomic': False, 'scope': 'sdk_visible_selected_classes',
                'source': 'object.state', 'classes': list(self.classes),
                'requested_states': dict((cls, list(STATE_FIELDS[cls])) for cls in self.classes),
                'sdk_rows_count': row_count, 'objects_count': len(objects), 'counts_by_class': counts,
                'failed_rows_count': failed, 'state_errors_count': state_errors,
                'collection_complete': not errors and failed == 0 and state_errors == 0,
                'collection_errors': errors}
        return data, objects
    def events(self, factory, config, classes):
        self.classes = list(classes)
        return ObjectsSnapshotCollector.events(self, StateEventFactory(factory), config)

class CollectorApplication(PreviousCollector):
    def __init__(self, path, settings_function, list_objects, object_function):
        self._states_options = state_options({})
        self._states_error = None
        self._states_at = 0
        PreviousCollector.__init__(self, path, settings_function, list_objects)
        self.object_states = ObjectStatesCollector(list_objects, object_function)
    def refresh(self):
        config = PreviousCollector.refresh(self)
        try:
            candidate = state_options(config)
        except Exception as error:
            name = type(error).__name__
            if name != self._states_error:
                self.logger.error('Object states settings rejected: %s; previous settings retained', name)
            self._states_error = name
        else:
            if candidate != self._states_options:
                self._states_at = 0
            self._states_options, self._states_error = candidate, None
        return config
    def tick(self):
        with self._callback_lock:
            try:
                PreviousCollector.tick(self)
            except Exception:
                self.logger.exception('Collector failed before object states')
            config, option = self.config.value, self._states_options
            if not config['collector']['enabled'] or not option['enabled'] or time.time() < self._states_at:
                return
            self._states_at = time.time() + option['interval_seconds']
            try:
                events = self.object_states.events(self.factory, config, option['classes'])
                for event in events:
                    self.save(event)
                data = events[0]['data']
                self.logger.info('Object states saved: id=%s objects=%s parts=%s errors=%s complete=%s',
                                 data['snapshot_id'], data['objects_count'], len(events),
                                 data['state_errors_count'], data['collection_complete'])
            except Exception:
                self.logger.exception('Object states failed; incomplete snapshot must not replace state')
