"""Closed app-owned display projections and conditional read-model envelopes."""
from __future__ import annotations

import hashlib
import json
import math
import re

_FORBIDDEN_KEY = re.compile(r'password|secret|token|credential|authorization|authority|capabilit', re.I)
_UNSAFE_URL = re.compile(r'^blob\s*:|[?&](?:sig|signature|x-amz-signature|x-goog-signature)=', re.I)


def project_display_model(value: object, shape: dict, *, depth: int = 0) -> dict:
    if not isinstance(value, dict) or depth > 16:
        raise ValueError('Invalid display model object.')
    result = {}
    for key, kind in shape.get('fields', {}).items():
        if key not in value:
            if key in shape.get('required', []):
                raise ValueError(f'Missing display field: {key}')
            continue
        item = value[key]
        if item is None:
            result[key] = None
            continue
        if kind == 'strings':
            valid = isinstance(item, list) and all(isinstance(entry, str) for entry in item)
        else:
            valid = (kind == 'string' and isinstance(item, str)) or (kind == 'number' and isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)) or (kind == 'boolean' and isinstance(item, bool))
        if not valid:
            raise ValueError(f'Invalid display field: {key}')
        if isinstance(item, str) and _UNSAFE_URL.search(item):
            continue
        result[key] = item
    for key, child in shape.get('objects', {}).items():
        if key in value:
            result[key] = None if value[key] is None else project_display_model(value[key], child, depth=depth+1)
    for key, child in shape.get('lists', {}).items():
        if key not in value:
            if key in shape.get('required', []):
                raise ValueError(f'Missing display list: {key}')
            continue
        if not isinstance(value[key], list):
            raise ValueError(f'Invalid display list: {key}')
        result[key] = [project_display_model(item, child, depth=depth+1) for item in value[key]]
    for key, kind in shape.get('maps', {}).items():
        if key not in value:
            continue
        if not isinstance(value[key], dict):
            raise ValueError(f'Invalid display map: {key}')
        entries = {}
        for name, item in value[key].items():
            if _FORBIDDEN_KEY.search(name) or name in {'__proto__', 'constructor', 'prototype'}:
                continue
            if item is None or isinstance(item, (str, bool)) or (isinstance(item, (int, float)) and math.isfinite(item)):
                if kind == 'number' and (not isinstance(item, (int, float)) or isinstance(item, bool)):
                    raise ValueError(f'Invalid numeric map: {key}')
                if not isinstance(item, str) or not _UNSAFE_URL.search(item):
                    entries[name] = item
            elif kind == 'scalar' and isinstance(item, list) and all(isinstance(entry, str) for entry in item):
                entries[name] = item
            else:
                raise ValueError(f'Invalid display map value: {key}')
        result[key] = entries
    return result


def conditional_display_response(payload: dict, known_revision: object = None) -> dict:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    revision = hashlib.sha256(encoded).hexdigest()
    if known_revision == revision:
        return {'revision': revision, 'not_modified': True}
    return {'revision': revision, 'payload': payload}
