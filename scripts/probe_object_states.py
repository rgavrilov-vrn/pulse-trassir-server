# -*- coding: utf-8 -*-
# Одноразовая серверная диагностика, НЕ второй Collector и НЕ генератор событий.
# Читаем только имена состояний одного представителя класса, без значений и методов управления.
import os
import json
import logging
from logging.handlers import RotatingFileHandler

ROOT = r"C:\TRASSIR_Agent"
DIRECTORY = os.path.join(ROOT, 'logs')
if not os.path.isdir(DIRECTORY):
    os.makedirs(DIRECTORY)
logger = logging.getLogger('trassir_agent.object_states_probe')
logger.propagate = False
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(os.path.join(DIRECTORY, 'object_states_probe.log'),
                                 maxBytes=2097152, backupCount=1, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)

for class_name in ['IP Device', 'Script', 'Script (Local)', 'Template', 'Folder', 'FolderH']:
    result = {'class_name': class_name}
    try:
        rows = list(objects_list(class_name))
        result['count'] = len(rows)
        if rows:
            guid = rows[0][1]
            result['sample_guid'] = guid
            sdk_object = object(guid)
            states = sdk_object.state
            result['state_python_type'] = type(states).__name__
            # keys() читается как операция отображения, не вызываются методы объекта TRASSIR.
            # Если SDK не предоставляет отображение, фиксируем ошибку, не угадываем API.
            names = list(states.keys())
            result['state_keys'] = [name.decode('utf-8', 'replace') if isinstance(name, bytes) else name for name in names[:100]]
            result['keys_truncated'] = len(names) > 100
    except Exception as error:
        result['error_type'] = type(error).__name__
    logger.info('%s', json.dumps(result, ensure_ascii=False))

logger.info('Object state discovery completed')
