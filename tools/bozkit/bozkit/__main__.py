"""
bozkit command line.

  python3 -m bozkit dump GROUP.group.bin [-o out.json] [--class CWave]
      Readable JSON of every resource: reflected resources and entity specs with named fields
      and typed values; other resources are listed with their size.

  python3 -m bozkit set GROUP.group.bin RESOURCE FIELD VALUE [-o NEW.group.bin] [--component C]
      Change one field and write a new group (default: overwrite in place is refused; give -o).
      RESOURCE is the resource name hash (0x...) or name, FIELD the property name
      (m_ZombieCount), VALUE a JSON value (6, 1.5, [0,0,1], "text"). For entity specs, pick the
      component with --component (e.g. CPlayerWeapon).

  python3 -m bozkit names FILE... 
      Builds a local name dictionary (resource, entity and asset names) from strings in your own
      game files (boz.s3e.unpacked, extracted groups) at ~/.cache/bozkit/names.txt, so dump shows
      names instead of hashes. The dictionary stays on your machine.

  python3 -m bozkit save FILE.i3d [-o out.json]
      A game save (N_save_game.i3d) as JSON: level, and every section (owner, class); sections
      holding reflection blobs are shown by field name, others as hex words.

  python3 -m bozkit settings save_settings.i3d [--set name=value ...] [-o NEW.i3d]
      Show the settings, or change them and write a correctly signed copy.

Groups come from the game's .dz packs; extract them with `dade marmalade extract-dz --no-delete`
or let the client's override layer pick up the edited file from a mod's assets folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import group, reflect, resources, save
from .schema import Names


def _blob_json(blob: reflect.Blob, names: Names) -> dict:
    out = {'class': names.name(blob.class_hash), 'fields': []}
    for p in blob.properties:
        item = {'name': names.name(p.name_hash), 'type': names.name(p.type_hash)}
        if names.name(p.owner_hash) != out['class']:
            item['declared_in'] = names.name(p.owner_hash)
        if p.nested is not None:
            item['value'] = _blob_json(p.nested, names)
        elif p.elements is not None:
            item['value'] = [_blob_json(e, names) for e in p.elements]
        else:
            v = reflect.typed_value(p)
            item['value'] = v if v is not None else {'raw': p.raw.hex()}
        out['fields'].append(item)
    return out


def _spec_json(spec: resources.EntitySpec, names: Names) -> dict:
    return {
        'components': [{
            'component': names.name(c.type_hash),
            'spec_class': names.name(c.class_hash),
            'properties': [_blob_json(b, names) for b in c.blobs if not b.empty],
            **({'extra_bytes': len(c.extra)} if c.extra else {}),
        } for c in spec.components],
        'children': [_spec_json(child, names) for _, _, child in spec.children],
    }


def cmd_dump(args) -> int:
    names = Names()
    g = group.parse(Path(args.group).read_bytes())
    out = {'group': g.name, 'resources': []}
    for t in g.types():
        cls = names.name(t.class_hash)
        if args.cls and cls != args.cls:
            continue
        for r in t.resources:
            item = {'class': cls, 'name': names.name(r.name_hash if r.name_hash is not None else r.in_group_hash)}
            if t.class_hash == resources.ENTITY_SPEC:
                item['entity'] = _spec_json(resources.decode_entity_spec(r.body), names)
            else:
                blob = resources.decode_reflected(r.body)
                if blob is not None:
                    item.update(_blob_json(blob, names))
                else:
                    item['bytes'] = len(r.body)
            out['resources'].append(item)
    text = json.dumps(out, indent=1)
    if args.output:
        Path(args.output).write_text(text + '\n')
    else:
        sys.stdout.write(text + '\n')
    return 0


def _find_property(blob: reflect.Blob, field_hash: int) -> reflect.Property | None:
    for p in blob.properties:
        if p.name_hash == field_hash:
            return p
    return None


def cmd_set(args) -> int:
    if not args.output:
        print('give -o NEW.group.bin (the input is never overwritten)', file=sys.stderr)
        return 2
    names = Names()
    g = group.parse(Path(args.group).read_bytes())
    want = names.hash(args.resource)
    field_hash = names.hash(args.field)
    value = json.loads(args.value)
    changed = 0
    for t in g.types():
        for r in t.resources:
            if want not in (r.name_hash, r.in_group_hash):
                continue
            if t.class_hash == resources.ENTITY_SPEC:
                spec = resources.decode_entity_spec(r.body)
                for c in spec.components:
                    if args.component and names.name(c.type_hash) != args.component:
                        continue
                    for b in c.blobs:
                        p = _find_property(b, field_hash)
                        if p is not None:
                            reflect.set_typed_value(p, value)
                            changed += 1
                r.body = resources.encode_entity_spec(spec)
            else:
                blob = resources.decode_reflected(r.body)
                p = blob and _find_property(blob, field_hash)
                if p is not None:
                    reflect.set_typed_value(p, value)
                    r.body = resources.encode_reflected(blob)
                    changed += 1
    if not changed:
        print(f'no field {args.field} on resource {args.resource}', file=sys.stderr)
        return 1
    Path(args.output).write_bytes(group.encode(g))
    print(f'{changed} value(s) changed -> {args.output}')
    return 0


def cmd_names(args) -> int:
    import re
    from .schema import NAMES_CACHE
    found: set[str] = set()
    for f in args.files:
        data = Path(f).read_bytes()
        for m in re.finditer(rb'[A-Za-z_][A-Za-z0-9_./-]{2,80}', data):
            text = m.group().decode('ascii')
            found.add(text)
            # path-like strings also contribute their last component and stem
            leaf = text.rsplit('/', 1)[-1]
            found.add(leaf)
            found.add(leaf.split('.', 1)[0])
    NAMES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NAMES_CACHE.write_text('\n'.join(sorted(found)) + '\n', encoding='latin-1')
    print(f'{len(found)} names -> {NAMES_CACHE}')
    return 0


def cmd_save(args) -> int:
    import struct
    names = Names()
    for extra in ('DynamicEntityData', 'BlackOpsStartLevel', 'DeadopsSavedRound', 'HashGenerator'):
        names.add(extra)
    g = save.parse_game_save(Path(args.file).read_bytes())
    out = {'version': g.version, 'level': g.level, 'dynamic_entities': g.dynamic_count, 'sections': []}
    for sec in g.sections:
        item = {'owner': names.name(sec.id), 'class': names.name(sec.class_hash), 'bytes': len(sec.data)}
        try:
            blobs = reflect.decode_sequence(sec.data, 0, len(sec.data)) if reflect.is_blob(sec.data) else None
        except Exception:
            blobs = None
        if blobs:
            item['properties'] = [_blob_json(b, names) for b in blobs if not b.empty]
        elif len(sec.data) % 4 == 0 and len(sec.data) <= 64:
            item['words'] = list(struct.unpack(f'<{len(sec.data) // 4}I', sec.data))
        else:
            item['hex'] = sec.data[:64].hex() + ('...' if len(sec.data) > 64 else '')
        out['sections'].append(item)
    text = json.dumps(out, indent=1)
    if args.output:
        Path(args.output).write_text(text + '\n')
    else:
        sys.stdout.write(text + '\n')
    return 0


def cmd_settings(args) -> int:
    version, values = save.parse_settings(Path(args.file).read_bytes())
    if not args.set:
        print(json.dumps(values, indent=1))
        return 0
    if not args.output:
        print('give -o NEW.i3d (the input is never overwritten)', file=sys.stderr)
        return 2
    for item in args.set:
        key, _, raw = item.partition('=')
        if key not in values:
            print(f'unknown setting {key}; known: {", ".join(values)}', file=sys.stderr)
            return 1
        values[key] = json.loads(raw) if key != 'last_level' else raw
    Path(args.output).write_bytes(save.encode_settings(version, values))
    print(f'settings written -> {args.output}')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='bozkit', description='BOZ asset tools')
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dump', help='group to JSON')
    d.add_argument('group')
    d.add_argument('-o', '--output')
    d.add_argument('--class', dest='cls')
    d.set_defaults(func=cmd_dump)
    s = sub.add_parser('set', help='change one field')
    s.add_argument('group')
    s.add_argument('resource')
    s.add_argument('field')
    s.add_argument('value')
    s.add_argument('-o', '--output')
    s.add_argument('--component')
    s.set_defaults(func=cmd_set)
    sv = sub.add_parser('save', help='game save to JSON')
    sv.add_argument('file')
    sv.add_argument('-o', '--output')
    sv.set_defaults(func=cmd_save)
    st = sub.add_parser('settings', help='show or change save_settings.i3d')
    st.add_argument('file')
    st.add_argument('--set', action='append', default=[])
    st.add_argument('-o', '--output')
    st.set_defaults(func=cmd_settings)
    n = sub.add_parser('names', help='build the local name dictionary from game files')
    n.add_argument('files', nargs='+')
    n.set_defaults(func=cmd_names)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
