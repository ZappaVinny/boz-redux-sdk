"""Your own model on a weapon (synthetic): skins, bone mapping, fitting, building."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import anim, assets, native, weapon_model as wm, world  # noqa: E402
from bozkit.hashing import iw_hash  # noqa: E402

TURN = (math.cos(math.pi / 8), 0.0, math.sin(math.pi / 8), 0.0)   # 45 degrees around Y


def skeleton():
    return [anim.Bone(iw_hash('J_Gun'), 0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)),
            anim.Bone(iw_hash('tag_clip'), iw_hash('J_Gun'), (0.0, -400.0, 800.0), TURN),
            anim.Bone(iw_hash('tag_flash'), iw_hash('J_Gun'), (0.0, 400.0, 12000.0), (1.0, 0.0, 0.0, 0.0))]


def gun():
    model = assets.GameModel(
        [(0, 0, 0), (1000, 0, 0), (1000, 100, 0), (100, -100, 0), (150, -200, 0), (100, -200, 0)],
        [(0.0, 0.0)] * 6, [(0, 1, 2), (3, 4, 5)], [0, 0])
    model.bones = [assets.Bone('tag_weapon', '', (0.0, 0.0, 0.0)),
                   assets.Bone('tag_clip', 'tag_weapon', (120.0, -150.0, 0.0)),
                   assets.Bone('tag_flash', 'tag_weapon', (1000.0, 50.0, 0.0))]
    model.weights = [[(0, 1.0)]] * 3 + [[(1, 1.0)]] * 2 + [[(1, 0.5), (0, 0.5)]]
    return model


class Skins(unittest.TestCase):
    def test_bind_pose_reproduces_the_model(self):
        bones = skeleton()
        positions = [(10.0, 20.0, 30.0), (-50.0, 5.0, 400.0), (0.0, -100.0, 200.0)]
        weights = [[(0, 1.0)], [(1, 1.0)], [(1, 0.25), (2, 0.75)]]
        skin = anim.build_skin(7, 9, bones, positions, weights)
        decoded = anim.decode_skin(anim.encode_skin(skin))
        self.assertEqual((decoded.model, decoded.skeleton), (7, 9))
        back = anim.skin_positions(decoded, anim.pose(bones), 3)
        for want, got in zip(positions, back):
            for a, b in zip(want, got):
                self.assertAlmostEqual(a, b, delta=1.0)

    def test_weight_bytes_add_up_to_128(self):
        skin = anim.build_skin(1, 2, skeleton(), [(0.0, 0.0, 0.0)], [[(0, 0.3), (1, 0.3), (2, 0.4)]])
        body = anim.encode_skin(skin)
        # 16 header + 16 set header + 4 bone ids + 2 index + 18 locals -> 3 weights + pad
        self.assertEqual(sum(body[56:59]), 128)
        self.assertEqual(body[59], 0xff)


class Bones(unittest.TestCase):
    def test_defaults(self):
        bones = skeleton()
        mapped = wm.default_bones(['tag_weapon', 'tag_clip', 'tag_flash', 'tag_extra'], bones, None)
        self.assertEqual(mapped, {'tag_weapon': 'J_Gun', 'tag_clip': 'tag_clip',
                                  'tag_flash': 'tag_flash', 'tag_extra': 'J_Gun'})

    def test_magazine_follows_the_reload_without_a_clip_bone(self):
        bones = skeleton()
        bones[1] = anim.Bone(0x1234, iw_hash('J_Gun'), (0.0, -400.0, 800.0), (1.0, 0.0, 0.0, 0.0))
        moving = anim.Anim(0, 3, [anim.Keyframe({}), anim.Keyframe({1: ((0.0, -3000.0, 800.0),
                                                                         (1.0, 0.0, 0.0, 0.0))})])
        mover = wm.reload_mover(bones, moving)
        self.assertEqual(mover, 1)
        self.assertEqual(wm.default_bones(['tag_clip'], bones, mover), {'tag_clip': '#1'})
        self.assertEqual(wm.bone_index(bones, '#1'), 1)


class Fitting(unittest.TestCase):
    def test_auto_fit_lines_up_with_the_stock_gun(self):
        model = gun()
        stock = [(-200, -300, -1000), (200, 600, 3000)]
        fit = wm.auto_fit({b.name: b.head for b in model.bones}, model.vertices, skeleton(), stock)
        placed = wm.apply_fit(fit, model.vertices)
        self.assertAlmostEqual(min(p[2] for p in placed), -1000, delta=1)
        self.assertAlmostEqual(max(p[2] for p in placed), 3000, delta=1)
        # The barrel (asset +X) now points down the stock gun's forward axis (+Z).
        muzzle = wm.apply_fit(fit, [(1000.0, 50.0, 0.0), (0.0, 50.0, 0.0)])
        self.assertGreater(muzzle[0][2] - muzzle[1][2], 3000)


class Building(unittest.TestCase):
    def test_resources(self):
        model = gun()
        model.levels['lod0'] = gun()
        texture = world.Texture(4, 4, bytes(64))
        from PIL import Image
        template = native.encode_texture(Image.new('RGBA', (4, 4)))
        material = native.Material(True, 0x50000, textures=[0], trailer=b'')
        fit = {'location': [0, 0, 0], 'rotation': [1, 0, 0, 0], 'scale': 2.0}
        bones = {'tag_weapon': 'J_Gun', 'tag_clip': 'tag_clip', 'tag_flash': 'tag_flash'}
        built = wm.build('wonder', model, [texture], fit, bones, skeleton(), 0xabc, material, template)
        kinds = sorted({k for k, _h, _b in built.resources})
        self.assertEqual(kinds, ['CIwAnimSkin', 'CIwMaterial', 'CIwModel', 'CIwTexture'])
        self.assertEqual(built.view, iw_hash('wonder_model'))
        self.assertEqual(built.lods[0], iw_hash('wonder_model_lod0'))
        self.assertEqual(built.lods[1], built.view)        # no lod1: the view model
        self.assertEqual(built.ads, built.view)
        bodies = {(k, h): b for k, h, b in built.resources}
        decoded = native.decode_model(bodies[('CIwModel', built.view)])
        self.assertEqual(len(decoded.vertices), 6)
        self.assertEqual(int.from_bytes(bodies[('CIwModel', built.view)][:4], 'little'), wm.SKINNED_FLAGS)
        skin = anim.decode_skin(bodies[('CIwAnimSkin', built.view)])
        self.assertEqual(skin.skeleton, 0xabc)
        back = anim.skin_positions(skin, anim.pose(skeleton()), 6)
        self.assertAlmostEqual(back[1][0], 2000, delta=1)

    def test_too_big(self):
        model = gun()
        with self.assertRaises(wm.WeaponModelError):
            wm.build('wonder', model, [], {'scale': 100.0}, {}, skeleton(), 1,
                     native.Material(True, 0, textures=[0]), b'')


if __name__ == '__main__':
    unittest.main()
