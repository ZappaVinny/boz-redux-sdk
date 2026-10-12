"""Skeletons, skins, animations, state machines and posing (synthetic data only)."""
import math
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import anim  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

BONE = iw_hash('CIwAnimBone')
SET = iw_hash('CIwAnimSkinSet')


def skel_body(bones):
    """bones: (name, parent, position, (w, x, y, z))."""
    out = bytearray(struct.pack('<I', len(bones)))
    for index, (name, parent, position, rotation) in enumerate(bones):
        out += struct.pack('<IIII', BONE, iw_hash(name), iw_hash(parent) if parent else 0,
                           anim.compress_quat(*rotation))
        out += struct.pack('<3hhhi', *position, index, 3, 0x400)
    return bytes(out)


def skin_body(model, skel, sets):
    """sets: (bone ids, [(index, [local per bone], [weight byte per bone])])."""
    out = bytearray(struct.pack('<IIII', 1, iw_hash(model), iw_hash(skel), len(sets)))
    for bones, vertices in sets:
        data = bytearray(bytes(bones + [0xff] * (2 - len(bones) if len(bones) == 1 else 4 - len(bones))))
        for index, locals_, weights in vertices:
            data += struct.pack('<H', index)
            for local in locals_:
                data += struct.pack('<3h', *local)
            pad = 2 if len(bones) < 3 else 4
            data += bytes(weights + [0] * (pad - len(weights)))
        out += struct.pack('<IIII', SET, 0, len(vertices), len(data)) + data
    return bytes(out)


def anim_body(skel, keys):
    """One keyframe; keys: per bone (position, (w, x, y, z)) in bone order."""
    frame = bytearray(0x90)
    struct.pack_into('<HB', frame, 4, len(keys), 4)
    for position, (w, x, y, z) in keys:
        frame += struct.pack('<3h4h', *position, *(round(v * 4096) for v in (w, x, y, z)))
    while len(frame) % 4:
        frame += b'\0'
    count = len(keys)
    mask = (1 << count) - 1
    return (struct.pack('<III', iw_hash(skel), count, mask) + struct.pack('<II', 1, len(frame))
            + bytes(frame) + struct.pack('<iiI', 0, 0x4000, 0))


def asm_body(states, default):
    out = bytearray(struct.pack('<I', len(states)))
    for name, anim_name, looping in states:
        out += struct.pack('<IIIiihIBB', iw_hash(name), iw_hash(anim_name) if anim_name else 0, 0,
                           4096, 0, 0, 0, looping, 1)
        out += struct.pack('<III', 0, 0, 0) + struct.pack('<I', 0)
    return bytes(out) + struct.pack('<h', default)


class AnimTests(unittest.TestCase):
    def test_quaternions(self):
        for q in [(1, 0, 0, 0), (0.7071, 0.7071, 0, 0), (0.5, 0.5, 0.5, 0.5), (0.1, 0.2, -0.9, 0.37)]:
            norm = math.sqrt(sum(v * v for v in q))
            q = tuple(v / norm for v in q)
            back = anim.decompress_quat(anim.compress_quat(*q))
            same = max(abs(a - b) for a, b in zip(q, back)) < 0.01
            opposite = max(abs(a + b) for a, b in zip(q, back)) < 0.01
            self.assertTrue(same or opposite, (q, back))
        self.assertEqual(anim.decompress_quat(0xe0080200), (1.0, 0.0, 0.0, 0.0))

    def test_skeleton_skin_and_pose(self):
        quarter = (math.cos(math.pi / 4), 0.0, math.sin(math.pi / 4), 0.0)   # 90 degrees about Y
        bones = anim.decode_skel(skel_body([('root', '', (0, 0, 0), (1, 0, 0, 0)),
                                            ('arm', 'root', (400, 0, 0), (1, 0, 0, 0)),
                                            ('TAG_WEAPON', 'arm', (0, 0, 800), (1, 0, 0, 0))]))
        self.assertEqual([b.parent for b in bones], [0, iw_hash('root'), iw_hash('arm')])
        skin = anim.decode_skin(skin_body('arms', 'rig', [
            ([1], [(0, [(40, 0, 0)], [128])]),
            ([1, 2], [(1, [(0, 0, 0), (0, 0, 0)], [64, 64])])]))
        self.assertEqual([s.bones for s in skin.sets], [[1], [1, 2]])
        bind = anim.pose(bones)
        positions = anim.skin_positions(skin, bind, 2)
        self.assertEqual(positions[0], (110.0, 0.0, 0.0))         # (400 + 40) / 4
        self.assertEqual(positions[1], (100.0, 0.0, 100.0))       # halfway arm .. tag, / 4
        keyframe = anim.decode_anim(anim_body('rig', [((0, 0, 0), (1, 0, 0, 0)),
                                                      ((400, 0, 0), quarter),
                                                      ((0, 0, 800), (1, 0, 0, 0))])).keyframes[0]
        posed = anim.pose(bones, keyframe)
        tag = anim.bone_world(bones, posed, 'TAG_WEAPON')
        self.assertTrue(all(abs(a - b) < 1.0 for a, b in zip(tag[0], (1200.0, 0.0, 0.0))), tag)
        # Something hung from the tag follows it.
        child = anim.pose([anim.Bone(iw_hash('gun'), 0, (0.0, 0.0, 0.0), (1, 0, 0, 0))], root=tag)
        self.assertTrue(all(abs(a - b) < 1.0 for a, b in zip(child[0][0], (1200.0, 0.0, 0.0))))
        # Unique positions expanded to every vertex (seams duplicate positions).
        expanded = anim.skin_positions(skin, bind, 3, [(0, 0, 0)] * 3, remap=[0, 1, 0])
        self.assertEqual(expanded[2], expanded[0])

    def test_state_machine(self):
        states, default = anim.decode_asm(asm_body([('draw', 'gun_draw', 0), ('idle', 'gun_idle', 1),
                                                    ('shooting', 'gun_fire', 0)], 0))
        self.assertEqual(default, 0)
        self.assertEqual(anim.state_anim(states, 'idle'), iw_hash('gun_idle'))
        self.assertTrue(states[1].looping)
        self.assertIsNone(anim.state_anim(states, 'sprint'))


if __name__ == '__main__':
    unittest.main()
