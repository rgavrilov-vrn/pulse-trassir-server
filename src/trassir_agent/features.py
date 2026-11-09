# -*- coding: utf-8 -*-
# Расширения Collector. core.py, схема БД и транспорт остаются прежними.
from __future__ import unicode_literals
import json
import math
import threading
import time
from .core import CollectorApplication as BaseCollector
from .core import EventFactory, scalar
try:
    TEXT = unicode
    STRINGS = basestring
    NUMBERS = (int, long, float)
except NameError:
    TEXT = str
    STRINGS = str
    NUMBERS = (int, float)

HEALTH_FIELDS = (
    'server_ok', 'cpu_usage', 'gpu_usage', 'startup_ts',
    'ip_devices_total', 'ip_devices_connected',
    'channels_network_total', 'channels_network_online',
    'channels_board_total', 'channels_board_online',
    'channels_bitrate_exceeded', 'channels_detector_error',
    'channels_detector_warning', 'db_connected', 'db_is_slow',
    'db_last_error', 'disks_error_count', 'disks_is_slow',
    'disks_last_error', 'iscsi_error', 'archive_last_error',
    'amerge_error', 'disks_stat_main_days', 'disks_stat_subs_days',
    'scripts_ok', 'scripts_total', 'plugins_ok', 'plugins_warning',
    'network_really_connected', 'network_should_be_connected',
    'network_last_error', 'license_expires_in_sec', 'watchdog',
)
DEFAULT_RAW = ('type', 'ts', 'origin', 'p1', 'p2', 'p3')

def options(config):
    # Отсутствующие разделы означают выключенные расширения старой установки.
    h = config.get('health', {})
    r = config.get('raw_sdk', {})
    if not isinstance(h, dict) or not isinstance(r, dict):
        raise ValueError('health/raw_sdk must be objects')
    enabled_h = h.get('enabled', False)
    enabled_r = r.get('enabled', False)
    if type(enabled_h) is not bool or type(enabled_r) is not bool:
        raise ValueError('Feature enabled must be boolean')
    interval = h.get('interval_seconds', 60)
    if type(interval) is not int or not 5 <= interval <= 86400:
        raise ValueError('Invalid health interval')
    fields = h.get('fields', list(HEALTH_FIELDS))
    attributes = r.get('attributes', list(DEFAULT_RAW))
    if not isinstance(fields, list) or not fields or any(x not in HEALTH_FIELDS for x in fields):
        raise ValueError('Unknown health field')
    if not isinstance(attributes, list) or len(attributes) > 64:
        raise ValueError('raw_sdk.attributes must contain at most 64 names')
    for name in attributes:
        if not isinstance(name, STRINGS) or not name or len(name) > 64 or not name.isascii() if False else False:
            pass
        if not isinstance(name, STRINGS) or not name or len(name) > 64:
            raise ValueError('Invalid raw attribute')
        name.encode('ascii')
        if name.startswith('_') or name == 'origin_object' or any(x in name.lower() for x in ('password', 'token', 'secret', 'session', 'sid')):
            raise ValueError('Unsafe raw attribute')
    return {'health': {'enabled': enabled_h, 'interval_seconds': interval, 'fields': fields},
            'raw_sdk': {'enabled': enabled_r, 'attributes': attributes}}

class Snapshot(object):
    # Ограничения фиксированы, чтобы настройками нельзя было случайно отключить защиту.
    MAX_BYTES = 32768
    MAX_STRING = 4096
    MAX_DEPTH = 3
    MAX_ITEMS = 50
    def __init__(self):
        self.result = {'attributes': {}, 'unavailable_attributes': [], 'limitations': [], 'truncated': False}
    def note(self, path, reason):
        self.result['truncated'] = True
        if len(self.result['limitations']) < 64:
            self.result['limitations'].append({'path': path[:128], 'reason': reason})
    def convert(self, value, path, depth=0, ancestors=None):
        ancestors = set() if ancestors is None else ancestors
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, NUMBERS):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                self.note(path, 'non_finite_number'); return None
            return value
        if isinstance(value, bytes):
            value = value.decode('utf-8', 'replace')
        if isinstance(value, STRINGS):
            raw = value.encode('utf-8')
            if len(raw) > self.MAX_STRING:
                self.note(path, 'string_size_limit')
                return raw[:self.MAX_STRING].decode('utf-8', 'ignore')
            return value
        if isinstance(value, (dict, list, tuple)):
            if depth >= self.MAX_DEPTH:
                self.note(path, 'depth_limit'); return None
            if id(value) in ancestors:
                self.note(path, 'cycle'); return None
            parents = ancestors | set([id(value)])
            if len(value) > self.MAX_ITEMS:
                self.note(path, 'item_limit')
            if isinstance(value, dict):
                result = {}
                for index, key in enumerate(value):
                    if index >= self.MAX_ITEMS: break
                    if not isinstance(key, STRINGS):
                        self.note(path, 'non_string_key'); continue
                    if any(word in key.lower() for word in ('password', 'token', 'secret', 'session')):
                        self.note(path, 'sensitive_key'); continue
                    safe_key = key[:128]
                    result[safe_key] = self.convert(value[key], path + '.' + safe_key, depth+1, parents)
                return result
            return [self.convert(x, path+'[]', depth+1, parents) for x in value[:self.MAX_ITEMS]]
        # Не вызываем методы, repr или рекурсивный обход произвольного SDK-объекта.
        self.note(path, 'unsupported_object')
        return None
    def read(self, event, names):
        for name in names:
            try:
                value = getattr(event, str(name))
                if callable(value):
                    self.note(name, 'callable_skipped'); continue
                self.result['attributes'][name] = self.convert(value, name)
            except Exception as error:
                self.result['unavailable_attributes'].append({'name': name, 'error_type': type(error).__name__})
            if len(json.dumps(self.result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > self.MAX_BYTES:
                self.result['attributes'].pop(name, None)
                self.note(name, 'total_size_limit')
                break
        # Метаданные тоже входят в общий лимит.
        if len(json.dumps(self.result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > self.MAX_BYTES:
            self.result = {'attributes': {}, 'unavailable_attributes': [], 'limitations': [{'path': '', 'reason': 'total_size_limit'}], 'truncated': True}
        return self.result

class SdkEventFactory(EventFactory):
    def __init__(self, get_options):
        self.get_options = get_options
    def from_sdk(self, event):
        # Нормализованный контракт сохраняем, как в базовой версии.
        result = EventFactory.from_sdk(self, event)
        raw = self.get_options()['raw_sdk']
        if raw['enabled']:
            result['raw_sdk'] = Snapshot().read(event, raw['attributes'])
            result['event_version'] = '1.1'
        return result

class HealthCollector(object):
    def __init__(self, settings_function):
        # SDK-функция приходит из точки входа; импортируемый модуль её не угадывает.
        self.settings_function = settings_function
    def collect(self, fields):
        data = {'metrics': {}, 'missing_fields': [], 'collection_errors': [], 'source': 'settings/health', 'snapshot_atomic': False}
        try:
            folder = self.settings_function('health')
        except Exception as error:
            data['collection_errors'].append({'field': '*', 'error_type': type(error).__name__})
            return data
        for name in fields:
            try:
                value = folder[str(name)]
                snapshot = Snapshot()
                data['metrics'][name] = snapshot.convert(value, name)
                if snapshot.result['truncated']:
                    data['collection_errors'].append({'field': name, 'error_type': 'ValueLimited'})
            except KeyError:
                data['missing_fields'].append(name)
            except Exception as error:
                # Не превращаем отсутствие показателя в 0 и не сохраняем текст исключения.
                data['collection_errors'].append({'field': name, 'error_type': type(error).__name__})
        return data

class CollectorApplication(BaseCollector):
    def __init__(self, path, settings_function):
        self._callback_lock = threading.RLock()
        self._features = options({})
        self._feature_error = None
        BaseCollector.__init__(self, path)
        self.refresh()
        self.factory = SdkEventFactory(lambda: self._features)
        self.health_collector = HealthCollector(settings_function)
        self._health_at = 0
    def refresh(self):
        c = BaseCollector.refresh(self)
        try:
            candidate = options(c)
        except Exception as error:
            name = type(error).__name__
            if name != self._feature_error:
                self.logger.error('Feature settings rejected: %s; previous feature settings retained', name)
            self._feature_error = name
        else:
            self._features = candidate
            self._feature_error = None
        return c
    def on_event(self, event):
        # Не допускаем одновременной ротации JSONL и reload из двух callback Collector.
        with self._callback_lock:
            return BaseCollector.on_event(self, event)
    def tick(self):
        with self._callback_lock:
            BaseCollector.tick(self)
            h = self._features['health']
            if not self.config.value['collector']['enabled'] or not h['enabled']:
                return
            if time.time() < self._health_at:
                return
            self._health_at = time.time() + h['interval_seconds']
            data = self.health_collector.collect(h['fields'])
            self.save(self.factory.create('trassir.health', data))
