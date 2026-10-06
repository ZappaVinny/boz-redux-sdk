"""Private native-resource corpus auditing.

Reports contain metadata, counts, and cryptographic hashes only.  They never contain
resource bodies, extracted assets, or decoded game content.
"""
from __future__ import annotations

import hashlib
import fnmatch
from collections import defaultdict
from pathlib import Path

from . import collision, group, map_resources, native, navigation, resources
from .hashing import iw_hash
from .schema import Names

_CAPABILITIES = {
    iw_hash('CIwTexture'): ('preserve', 'experimental-raw-layout'),
    iw_hash('CIwMaterial'): ('parse', 'write', 'edit', 'validate'),
    iw_hash('CIwModel'): ('preserve', 'experimental-static-geometry'),
    resources.ENTITY_SPEC: ('parse', 'write', 'edit', 'validate'),
    iw_hash('CIsNavMesh'): ('parse', 'write', 'edit-settings', 'validate'),
    iw_hash('CIsNavMeshConnection'): ('parse', 'write', 'edit', 'validate'),
    iw_hash('CIsPortal'): ('parse', 'write', 'edit', 'validate'),
}


def _validate_codec(class_hash: int, body: bytes) -> bool | None:
    """Return codec support for a known class, or None when no codec exists."""
    if class_hash == iw_hash('CIwTexture'):
        native.texture_layout(body)
    elif class_hash == iw_hash('CIwMaterial'):
        value = native.decode_material(body)
        if native.encode_material(value) != body:
            raise ValueError('material round-trip mismatch')
    elif class_hash == iw_hash('CIwModel'):
        value = native.decode_model(body)
        if native.encode_model(value, body) != body:
            raise ValueError('model round-trip mismatch')
    elif class_hash == resources.ENTITY_SPEC:
        value = resources.decode_entity_spec(body)
        if resources.encode_entity_spec(value) != body:
            raise ValueError('entity-spec round-trip mismatch')
        for component in value.components:
            if component.class_hash == resources.COLLISION_MESH_SPEC:
                mesh = collision.decode(component.extra)
                if collision.encode(mesh) != component.extra:
                    raise ValueError('collision round-trip mismatch')
    elif class_hash == iw_hash('CIsNavMesh'):
        value = navigation.decode(body)
        if navigation.encode(value) != body:
            raise ValueError('navigation round-trip mismatch')
    elif class_hash == iw_hash('CIsPortal'):
        value = map_resources.decode_portal(body)
        if map_resources.encode_portal(value) != body:
            raise ValueError('portal round-trip mismatch')
    elif class_hash == iw_hash('CIsNavMeshConnection'):
        value = navigation.decode_connection(body)
        if navigation.encode_connection(value) != body:
            raise ValueError('navigation-connection round-trip mismatch')
    else:
        return None
    return True


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(paths: list[str | Path], exclude: tuple[str, ...] = ()) -> dict:
    """Audit group files recursively and verify byte-identical container round trips."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_dir():
            files.extend(sorted(path.rglob('*.group.bin')))
        else:
            files.append(path)
    names = Names()
    classes: dict[int, dict] = defaultdict(lambda: {'resources': 0, 'bytes': 0, 'groups': 0})
    reports = []
    failures = []
    for path in sorted(set(files)):
        if any(fnmatch.fnmatch(path.as_posix(), pattern) for pattern in exclude):
            continue
        try:
            data = path.read_bytes()
            parsed = group.parse(data)
            encoded = group.encode(parsed)
            seen = set()
            resource_count = 0
            for kind in parsed.types():
                entry = classes[kind.class_hash]
                entry['resources'] += len(kind.resources)
                entry['bytes'] += sum(len(item.body) for item in kind.resources)
                resource_count += len(kind.resources)
                if kind.class_hash not in seen:
                    entry['groups'] += 1
                    seen.add(kind.class_hash)
                for item in kind.resources:
                    if resources.decode_reflected(item.body) is not None:
                        entry['reflected'] = entry.get('reflected', 0) + 1
                    try:
                        supported = _validate_codec(kind.class_hash, item.body)
                    except Exception:
                        entry['codec_failures'] = entry.get('codec_failures', 0) + 1
                    else:
                        if supported:
                            entry['codec_resources'] = entry.get('codec_resources', 0) + 1
            match = data == encoded
            report = {'file': path.name, 'group': parsed.name, 'bytes': len(data),
                      'resources': resource_count, 'input_sha256': _sha256(data),
                      'roundtrip_sha256': _sha256(encoded), 'byte_identical': match}
            reports.append(report)
            if not match:
                failures.append({'file': path.name, 'error': 'round-trip mismatch'})
        except Exception as exc:  # a corpus report should continue after a malformed file
            failures.append({'file': path.name, 'error': str(exc)})
    coverage = []
    for class_hash, values in sorted(classes.items()):
        capabilities = _CAPABILITIES.get(class_hash)
        if capabilities is None and values.get('reflected') == values['resources']:
            capabilities = ('parse', 'write', 'edit', 'validate')
        if capabilities is None:
            capabilities = ('preserve',)
        codec_total = values.get('codec_resources', 0) + values.get('codec_failures', 0)
        if codec_total:
            values['codec_coverage'] = ('full' if values.get('codec_failures', 0) == 0 else
                                        'partial')
        elif values.get('reflected') == values['resources']:
            values['codec_resources'] = values['resources']
            values['codec_coverage'] = 'full'
        coverage.append({'class': names.name(class_hash), 'hash': f'0x{class_hash:08x}',
                         **values, 'capabilities': list(capabilities)})
    return {'schema': 1, 'summary': {'groups': len(reports),
                                     'resources': sum(item['resources'] for item in reports),
                                     'classes': len(coverage), 'failures': len(failures),
                                     'all_byte_identical': not failures},
            'classes': coverage, 'groups': reports, 'failures': failures}
