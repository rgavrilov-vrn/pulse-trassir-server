# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import re
from .core import utc
from .features import Snapshot
from .inventory import sdk_text
from .unified_snapshot import UnifiedSnapshotCollector, CollectorApplication as PreviousCollector

DEVICE_FIELDS = ('connection_ip', 'connection_port', 'family', 'model')

def device_options(config):
    section = config.get('objects_snapshot', {})
    fields = section.get('device_fields', [])
    links = section.get('device_channel_fields', [])
    if not isinstance(fields, list) or any(field not in DEVICE_FIELDS for field in fields):
        raise ValueError('Unsupported device_fields')
    if len(fields) != len(set(fields)):
        raise ValueError('Duplicate device field')
    if not isinstance(links, list) or len(links) > 64:
        raise ValueError('Invalid device_channel_fields')
    links = [sdk_text(field) for field in links]
    if any(re.match(r'^channel[0-9]{2}_guid\Z', field) is None for field in links):
        raise ValueError('Invalid channel GUID field')
    if len(links) != len(set(links)):
        raise ValueError('Duplicate channel GUID field')
    return {'device_fields': list(fields), 'device_channel_fields': links}

class DeviceSnapshotCollector(UnifiedSnapshotCollector):
    def __init__(self, list_objects, settings_function, object_function, get_options):
        UnifiedSnapshotCollector.__init__(self, list_objects, settings_function, object_function)
        self.get_device_options = get_options
    def collect(self):
        data, objects = UnifiedSnapshotCollector.collect(self)
        option = self.get_device_options()
        fields, slots = option['device_fields'], option['device_channel_fields']
        channels = dict((obj['object_id'], obj) for obj in objects if obj['class_name'] == 'Channel')
        owners, devices = {}, {}
        links_complete = True
        for obj in objects:
            if obj['class_name'] != 'IP Device' or not (fields or slots):
                continue
            guid = obj['object_id']
            devices[guid] = obj
            folder, folder_error = None, None
            try:
                folder = self.settings_function(str('ip_cameras/' + guid))
            except Exception as error:
                folder_error = error
            for field in fields:
                obj['values'][field] = None
                try:
                    if folder_error is not None:
                        raise folder_error
                    converter = Snapshot()
                    obj['values'][field] = converter.convert(folder[str(field)], field)
                    if converter.result['truncated']:
                        obj['collection_errors'].append({'field': field, 'error_type': 'ValueLimited'})
                except Exception as error:
                    obj['collection_errors'].append({'field': field, 'error_type': type(error).__name__})
            if slots:
                ids, complete = set(), True
                for field in slots:
                    try:
                        if folder_error is not None:
                            raise folder_error
                        channel_id = sdk_text(folder[str(field)])
                        if channel_id:
                            if channel_id not in channels:
                                raise ValueError('Channel not present in inventory')
                            ids.add(channel_id)
                    except Exception as error:
                        complete = False
                        obj['collection_errors'].append({'field': 'channel_ids', 'source_field': field,
                                                         'error_type': type(error).__name__})
                obj['values']['channel_ids'] = sorted(ids) if complete else None
                if complete:
                    for channel_id in ids:
                        owners.setdefault(channel_id, set()).add(guid)
                else:
                    links_complete = False
            obj['observed_at'] = utc()
        if slots:
            for channel_id, obj in channels.items():
                matched = owners.get(channel_id, set())
                obj['values']['ip_device_id'] = None
                if not links_complete:
                    obj['collection_errors'].append({'field': 'ip_device_id', 'error_type': 'DeviceLinksIncomplete'})
                elif len(matched) == 1:
                    obj['values']['ip_device_id'] = next(iter(matched))
                elif len(matched) > 1:
                    obj['collection_errors'].append({'field': 'ip_device_id', 'error_type': 'AmbiguousDeviceLink'})
                    for guid in matched:
                        devices[guid]['collection_errors'].append({'field': 'channel_ids', 'error_type': 'AmbiguousDeviceLink'})
                obj['observed_at'] = utc()
        for obj in objects:
            obj['collection_complete'] = not obj['collection_errors']
        data['field_errors_count'] = sum(len(obj['collection_errors']) for obj in objects)
        data['enrichment_complete'] = data['enrichment_complete'] and data['field_errors_count'] == 0
        data['collection_complete'] = data['inventory_complete'] and data['enrichment_complete']
        data['requested_fields_by_class']['IP Device'] += list(fields)
        if slots:
            data['requested_fields_by_class']['IP Device'].append('channel_ids')
            data['requested_fields_by_class']['Channel'].append('ip_device_id')
        data['device_channel_fields'] = list(slots)
        data['device_links_scope'] = 'configured_channel_fields'
        data['device_links_complete'] = links_complete and not any(len(ids) > 1 for ids in owners.values()) if slots else None
        data['collection_finished_at'] = utc()
        return data, objects

class CollectorApplication(PreviousCollector):
    def __init__(self, path, settings_function, list_objects, object_function):
        self._device_options = device_options({})
        self._device_error = None
        PreviousCollector.__init__(self, path, settings_function, list_objects, object_function)
        self.unified_snapshot = DeviceSnapshotCollector(list_objects, settings_function, object_function,
                                                        lambda: self._device_options)
    def refresh(self):
        config = PreviousCollector.refresh(self)
        try:
            candidate = device_options(config)
        except Exception as error:
            name = type(error).__name__
            if name != self._device_error:
                self.logger.error('Device snapshot settings rejected: %s; previous device settings retained', name)
            self._device_error = name
        else:
            if candidate != self._device_options:
                self._snapshot_at = 0
            self._device_options, self._device_error = candidate, None
        return config
