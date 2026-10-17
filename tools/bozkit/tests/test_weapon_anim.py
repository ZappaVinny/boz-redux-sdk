"""A weapon's own animations (synthetic): formats written back, clips, retargeting, building."""
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import anim, assets, weapon_anim as wa  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

TURN = (math.cos(math.pi / 8), 0.0, math.sin(math.pi / 8), 0.0)


def stock_bones():
    return [anim.Bone(iw_hash('J_Gun'), 0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)),
            anim.Bone(iw_hash('tag_clip'), iw_hash('J_Gun'), (0.0, -400.0, 800.0), TURN)]


def stock_reload():
    frames = []
    for number, drop in enumerate((0.0, -1500.0, 0.0)):
        frames.append(anim.Keyframe({1: ((0.0, -400.0 + drop, 800.0), TURN)}, wa.time_of(number * 10)))
    return anim.Anim(0, 2, frames)


def asset_model():
    model = assets.GameModel([(0, 0, 0)], [(0.0, 0.0)], [], [])
    model.bones = [assets.Bone('tag_weapon', '', (0.0, 0.0, 0.0)),
                   assets.Bone('tag_clip', 'tag_weapon', (100.0, -50.0, 0.0))]
    return model


class Formats(unittest.TestCase):
    def test_skeleton(self):
        bones = stock_bones()
        body = anim.encode_skel(bones)
        back = anim.decode_skel(body)
        self.assertEqual([(b.name, b.parent, b.index) for b in back],
                         [(b.name, b.parent, i) for i, b in enumerate(bones)])
        self.assertEqual(anim.skel_value(body), anim.SKEL_VALUE)
        for a, b in zip(back[1].rotation, TURN):
            self.assertAlmostEqual(a, b, places=2)
        self.assertEqual(anim.encode_skel(back), body)    # stored rotations are kept

    def test_animation(self):
        body = anim.encode_anim(stock_reload(), b'\xff' * 0x90)
        back = anim.decode_anim(body)
        self.assertEqual([k.time for k in back.keyframes], [0, 1365, 2731])
        self.assertEqual(back.duration, 2731)
        self.assertAlmostEqual(back.keyframes[1].keys[1][0][1], -1900.0)
        self.assertEqual(anim.encode_anim(back), body)

    def test_state_machine(self):
        state = struct.pack('<IIIiihIBB', iw_hash('reloading'), 5, 6, 4096, 0, 0, 0, 0, 0)
        state += struct.pack('<I', 0) * 3 + struct.pack('<I', 0)
        body = struct.pack('<I', 1) + state + struct.pack('<h', 0)
        patched = anim.patch_asm(body, {iw_hash('reloading'): 99})
        states, _default = anim.decode_asm(patched)
        self.assertEqual((states[0].anim, states[0].anim2), (99, 6))

    def test_state_lengths(self):
        def state(name, length):
            return (struct.pack('<IIIiihIBB', iw_hash(name), 5, 6, 4096, length, 0, 0, 0, 0)
                    + struct.pack('<I', 0) * 4)
        body = (struct.pack('<I', 3) + state('reloading', 2333) + state('idle', 0) + state('Aim_up', 0)
                + struct.pack('<h', 1))
        changes = anim.asm_lengths(body, {iw_hash('reloading'): 3067, iw_hash('idle'): 500,
                                          iw_hash('Aim_up'): 533})
        out = bytearray(body)
        for offset, value in changes.items():
            struct.pack_into('<I', out, offset, value)
        lengths = [struct.unpack_from('<i', out, at + anim.LENGTH_AFTER_ANIM)[0]
                   for _name, at, _second in anim.asm_anim_offsets(bytes(out))]
        self.assertEqual(lengths, [3067, 0, 533])   # idle keeps none; aiming in needs one


class Clips(unittest.TestCase):
    def test_frames_and_times(self):
        self.assertEqual(wa.time_of(30), 4096)
        self.assertEqual(wa.frame_of(2731), 20)


class Timelines(unittest.TestCase):
    def test_changes_hold_forward_only(self):
        changes = wa.add_pose([], 30, {'1': ((1, 2, 3), (1, 0, 0, 0))})
        self.assertEqual(wa.source_of(changes, 10), ('original', 10))      # before: untouched
        self.assertEqual(wa.source_of(changes, 30)[0], 'pose')
        self.assertEqual(wa.source_of(changes, 99)[0], 'pose')              # held from 30 on
        changes = wa.add_original(changes, 60)
        self.assertEqual(wa.source_of(changes, 70), ('original', 70))      # original again
        changes = wa.add_pose(changes, 45, {'1': ((0, 0, 0), (1, 0, 0, 0))})
        self.assertEqual(wa.change_frames(changes), [30, 45, 60])
        self.assertTrue(wa.is_yours(changes, 50))
        self.assertFalse(wa.is_yours(changes, 60))

    def test_copy_frames(self):
        changes = wa.copy_frames([], 100, 40, 59, {'1': ((0, 0, 0), (1, 0, 0, 0))})
        self.assertEqual(wa.source_of(changes, 105), ('original', 45))
        self.assertEqual(wa.source_of(changes, 120)[0], 'pose')            # after the copy: held
        self.assertFalse(wa.is_yours(changes, 110))

    def test_back_to_original_at_the_start_is_nothing(self):
        self.assertEqual(wa.add_original([], 0), [])

    def test_state_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            edits = {'arms': wa.add_pose([], 5, {'2': ((1, 1, 1), (1, 0, 0, 0))}), 'gun': []}
            clip = wa.Clip([(0, {'2': ((1.0, 1.0, 1.0), (1.0, 0.0, 0.0, 0.0))})])
            wa.save_state(source, 'gun', 0xab, 'reloading', {'arms': clip, 'gun': None}, edits, 40)
            loaded = wa.load_clips(source, 'gun')[0xab]
            self.assertEqual((loaded['edits'], loaded['length'], loaded['state']), (edits, 40, 'reloading'))
            self.assertEqual(loaded['arms'].frames, clip.frames)
            wa.save_state(source, 'gun', 0xab, 'reloading', {}, {'arms': [], 'gun': []}, 40)
            self.assertEqual(wa.load_clips(source, 'gun'), {})


class Arms(unittest.TestCase):
    def test_offset_moves_the_bones_under_the_root(self):
        bones = [anim.Bone(1, 0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)),
                 anim.Bone(2, 1, (10.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)),
                 anim.Bone(3, 2, (5.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))]
        self.assertIsNone(wa.arms_offset({}))
        self.assertIsNone(wa.arms_offset({'location': [0, 0, 0], 'rotation': [1, 0, 0, 0]}))
        offset = wa.arms_offset({'location': [0.0, 2.0, 0.0], 'rotation': [1, 0, 0, 0]})
        clip = wa.Clip([(0, {'0': ((0, 0, 0), (1, 0, 0, 0)), '1': ((10, 0, 0), (1, 0, 0, 0)),
                             '2': ((5, 0, 0), (1, 0, 0, 0))})])
        moved = wa.offset_arms(clip, bones, offset)
        keys = moved.frames[0][1]
        self.assertEqual(keys['0'][0], (0, 0, 0))                 # the root stays
        self.assertAlmostEqual(keys['1'][0][1], 8.0)              # 2 model units x 4
        self.assertEqual(keys['2'][0], (5, 0, 0))                 # deeper bones ride along


class OwnSkeleton(unittest.TestCase):
    fit = {'location': [10.0, 0.0, 0.0], 'rotation': [1.0, 0.0, 0.0, 0.0], 'scale': 2.0}

    def test_retargeted_reload_drops_the_magazine(self):
        model = asset_model()
        own = wa.own_skeleton(model, self.fit)
        self.assertEqual((own[0].name, own[0].position), (iw_hash(wa.ROOT), (0.0, 0.0, 0.0)))
        self.assertEqual(own[2].position, (800.0, -400.0, 0.0))      # (100, -50) x 2 x 4
        clip = wa.retarget(stock_bones(), stock_reload(), own, wa.follow_list(model, stock_bones(), {'tag_clip': 'tag_clip'}))
        self.assertEqual([f for f, _k in clip.frames], [0, 10, 20])
        start = anim.pose(own, anim.Keyframe(clip.frames[0][1]))[2][0]
        low = anim.pose(own, anim.Keyframe(clip.frames[1][1]))[2][0]
        self.assertAlmostEqual(low[1] - start[1], -1500.0, delta=1.0)

    def test_editor_and_game_spaces(self):
        model = asset_model()
        own = wa.own_skeleton(model, self.fit)
        clip = wa.retarget(stock_bones(), stock_reload(), own, wa.follow_list(model, stock_bones(), {'tag_clip': 'tag_clip'}))
        back = wa.gun_clip_to_game(wa.game_clip_to_asset(clip, model, self.fit), model, self.fit)
        for (frame, keys), (frame2, keys2) in zip(clip.frames, back.frames):
            self.assertEqual(frame, frame2)
            for bone in keys:
                for a, b in zip(keys[bone][0], keys2[bone][0]):
                    self.assertAlmostEqual(a, b, places=6)

    def test_encode(self):
        model = asset_model()
        own = wa.own_skeleton(model, self.fit)
        clip = wa.retarget(stock_bones(), stock_reload(), own, wa.follow_list(model, stock_bones(), {}))
        body = wa.encode_clip(clip, 77, own, lambda k: k, b'\xff' * 0x90)
        back = anim.decode_anim(body)
        self.assertEqual((back.skeleton, back.bone_count, len(back.keyframes)), (77, 3, 3))


if __name__ == '__main__':
    unittest.main()
