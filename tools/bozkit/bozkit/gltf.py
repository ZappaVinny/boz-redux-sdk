"""Minimal glTF 2.0 interchange for static BOZ ``CIwModel`` geometry."""
from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

from .native import Model

_COMPONENT = {5121: ('B', 1), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
_WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def export_model(model: Model, output: str | Path, name: str = 'model') -> None:
    """Write a self-contained, deterministic glTF 2.0 document."""
    positions = b''.join(struct.pack('<3f', *map(float, value)) for value in model.vertices)
    texcoords = b''.join(struct.pack('<2f', *value) for value in model.uvs)
    indices = [value for triangle in model.triangles for value in triangle]
    component = 5123 if max(indices, default=0) <= 65535 else 5125
    fmt = '<H' if component == 5123 else '<I'
    index_data = b''.join(struct.pack(fmt, value) for value in indices)
    chunks = [positions]
    if model.uvs:
        chunks.append(texcoords)
    chunks.append(index_data)
    offsets = []
    binary = bytearray()
    for chunk in chunks:
        while len(binary) % 4:
            binary.append(0)
        offsets.append(len(binary))
        binary += chunk
    views = [{'buffer': 0, 'byteOffset': offsets[0], 'byteLength': len(positions),
              'target': 34962}]
    position_accessor = {'bufferView': 0, 'componentType': 5126,
                         'count': len(model.vertices), 'type': 'VEC3'}
    if model.vertices:
        position_accessor['min'] = [float(min(vertex[axis] for vertex in model.vertices))
                                    for axis in range(3)]
        position_accessor['max'] = [float(max(vertex[axis] for vertex in model.vertices))
                                    for axis in range(3)]
    accessors = [position_accessor]
    attributes = {'POSITION': 0}
    cursor = 1
    if model.uvs:
        views.append({'buffer': 0, 'byteOffset': offsets[cursor], 'byteLength': len(texcoords),
                      'target': 34962})
        accessors.append({'bufferView': cursor, 'componentType': 5126, 'count': len(model.uvs),
                          'type': 'VEC2'})
        attributes['TEXCOORD_0'] = cursor
        cursor += 1
    views.append({'buffer': 0, 'byteOffset': offsets[cursor], 'byteLength': len(index_data),
                  'target': 34963})
    accessors.append({'bufferView': cursor, 'componentType': component, 'count': len(indices),
                      'type': 'SCALAR'})
    document = {'asset': {'version': '2.0', 'generator': 'bozkit'},
                'buffers': [{'byteLength': len(binary), 'uri':
                             'data:application/octet-stream;base64,' +
                             base64.b64encode(binary).decode('ascii')}],
                'bufferViews': views, 'accessors': accessors,
                'meshes': [{'name': name, 'primitives': [{'attributes': attributes,
                                                          'indices': cursor, 'mode': 4}]}],
                'nodes': [{'name': name, 'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0}
    Path(output).write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')


def _buffer(document: dict, index: int, root: Path) -> bytes:
    uri = document['buffers'][index]['uri']
    prefix = 'data:application/octet-stream;base64,'
    if uri.startswith(prefix):
        return base64.b64decode(uri[len(prefix):], validate=True)
    path = (root / uri).resolve()
    if root != path and root not in path.parents:
        raise ValueError('glTF buffer path escapes its document directory')
    return path.read_bytes()


def _accessor(document: dict, index: int, root: Path) -> list[tuple | int | float]:
    accessor = document['accessors'][index]
    if accessor.get('sparse') is not None:
        raise ValueError('sparse glTF accessors are unsupported')
    view = document['bufferViews'][accessor['bufferView']]
    fmt, size = _COMPONENT[accessor['componentType']]
    width = _WIDTH[accessor['type']]
    stride = view.get('byteStride', size * width)
    start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
    data = _buffer(document, view['buffer'], root)
    out = []
    for item in range(accessor['count']):
        value = struct.unpack_from('<' + fmt * width, data, start + item * stride)
        out.append(value[0] if width == 1 else value)
    return out


def import_model(source: str | Path, *, round_positions: bool = True) -> Model:
    """Read the first triangle primitive from a glTF 2.0 JSON document."""
    path = Path(source).resolve()
    document = json.loads(path.read_text())
    if document.get('asset', {}).get('version') != '2.0' or not document.get('meshes'):
        raise ValueError('file is not a supported glTF 2.0 mesh')
    primitive = document['meshes'][0]['primitives'][0]
    if primitive.get('mode', 4) != 4 or 'indices' not in primitive:
        raise ValueError('glTF primitive must use indexed triangles')
    positions = _accessor(document, primitive['attributes']['POSITION'], path.parent)
    vertices = [tuple(round(float(value)) if round_positions else float(value)
                      for value in position) for position in positions]
    raw_indices = [int(value) for value in _accessor(document, primitive['indices'], path.parent)]
    if len(raw_indices) % 3:
        raise ValueError('glTF index count is not divisible by three')
    triangles = [tuple(raw_indices[index:index + 3]) for index in range(0, len(raw_indices), 3)]
    uvs = []
    if 'TEXCOORD_0' in primitive['attributes']:
        uvs = [tuple(map(float, value)) for value in
               _accessor(document, primitive['attributes']['TEXCOORD_0'], path.parent)]
    return Model(vertices, triangles, uvs)
