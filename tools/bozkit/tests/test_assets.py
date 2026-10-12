"""Project assets (synthetic): settings, game versions, budgets, textures, checks, attach."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bozkit import assets, world  # noqa: E402


def square(materials=(0, 0)):
    return assets.GameModel([(0, 0, 0), (1000, 0, 0), (1000, 1000, 0), (0, 1000, 0)],
                            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
                            [(0, 1, 2), (0, 2, 3)], list(materials))


def textures(count=1, side=8):
    return [world.Texture(side, side, bytes(side * side * 4)) for _ in range(count)]


class AssetFiles(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            original = root / 'elsewhere' / 'gun.blend'
            original.parent.mkdir()
            original.write_bytes(b'BLENDER')
            copy = assets.copy_source(root, 'gun', original)
            self.assertEqual(copy, 'assets/gun/gun.blend')
            asset = assets.AssetDef('gun', 'weapon', copy, str(original), ['Body'], 'pc')
            assets.save_def(source, asset)
            self.assertEqual(assets.load_def(source, 'gun'), asset)
            self.assertEqual([a.name for a in assets.list_defs(source)], ['gun'])
            model = square()
            model.bones = [assets.Bone('tag_weapon', '', (0.0, 0.0, 0.0)),
                           assets.Bone('tag_clip', 'tag_weapon', (10.0, 0.0, -5.0))]
            model.weights = [[(0, 1.0)], [(0, 0.5), (1, 0.5)], [(1, 1.0)], [(0, 1.0)]]
            model.parts = {'Magazine': [1]}
            assets.write_game(source, 'gun', model, textures())
            loaded, loaded_textures = assets.load_game(source, 'gun')
            self.assertEqual(loaded, model)
            self.assertEqual(len(loaded_textures), 1)
            self.assertEqual(assets.load_stats(source, 'gun')['triangles'], 2)
            assets.delete(root, 'gun')
            self.assertFalse(assets.has_game(source, 'gun'))
            self.assertFalse((root / 'assets' / 'gun').exists())

    def test_bad_settings(self):
        for bad in (assets.AssetDef('1gun'), assets.AssetDef('gun', 'car'),
                    assets.AssetDef('gun', preset='ultra'), assets.AssetDef('gun', texture_size=300)):
            with self.assertRaises(assets.AssetError):
                assets.check_def(bad)

    def test_presets(self):
        self.assertEqual(assets.AssetDef('a', 'weapon').budget(), 1500)
        self.assertEqual(assets.AssetDef('a', 'weapon', preset='pc').max_texture(), 1024)
        self.assertEqual(assets.AssetDef('a', 'prop', triangles=300).budget(), 300)


class Budget(unittest.TestCase):
    def test_split(self):
        shares = assets.split_budget([18000, 12000, 400, 1200, 9000], 1500)
        self.assertLessEqual(sum(shares), 1500)
        self.assertTrue(all(s >= assets.MIN_PART_TRIANGLES for s in shares))
        self.assertGreater(shares[0], shares[1] > shares[4] - 1)
        self.assertEqual(assets.split_budget([100, 50], 1500), [100, 50])

    def test_unit_guess(self):
        self.assertEqual(assets.guess_unit(115.0, 'weapon'), 'cm')
        self.assertEqual(assets.guess_unit(0.9, 'weapon'), 'm')
        self.assertEqual(assets.guess_unit(20.0, 'weapon'), 'inch')

    def test_texture_sides(self):
        self.assertEqual(assets.texture_side(2048, 512), 512)
        self.assertEqual(assets.texture_side(300, 1024), 256)
        self.assertEqual(assets.texture_sizes([1.0, 0.2, 0.01], 512), [512, 256, 64])


class Textures(unittest.TestCase):
    def test_reduce_and_shade(self):
        from PIL import Image
        colour = Image.new('RGBA', (64, 64), (100, 100, 100, 255))
        flat = Image.new('RGB', (64, 64), (128, 128, 255))
        texture = assets.reduce_texture(colour, 16, flat)
        self.assertEqual((texture.width, texture.height), (16, 16))
        self.assertAlmostEqual(texture.bgra[0], 100, delta=2)      # a flat normal: unchanged
        away = Image.new('RGB', (64, 64), (0, 0, 128))              # facing down and back
        dark = assets.reduce_texture(colour, 16, away)
        self.assertLess(dark.bgra[0], 70)

    def test_flat(self):
        texture = assets.flat_texture((1.0, 0.0, 0.0, 1.0))
        self.assertEqual(texture.bgra[:4], bytes((0, 0, 255, 255)))


class Checks(unittest.TestCase):
    def test_clean(self):
        errors, warnings = assets.check(assets.AssetDef('a'), square(), textures())
        self.assertEqual((errors, warnings), ([], []))

    def test_hard_limits(self):
        model = square()
        model.vertices[0] = (40000, 0, 0)
        model.uvs[1] = (9.0, 0.0)
        model.materials = [0, 1]
        model.weights = [[(0, 0.2)] * 5, [], [], []]
        errors, _ = assets.check(assets.AssetDef('a'), model, [world.Texture(6, 6, bytes(144))])
        text = ' '.join(errors)
        for wanted in ('m from its centre', '-8..8', 'no texture', 'powers of two', 'bones'):
            self.assertIn(wanted, text)

    def test_warnings(self):
        model = square()
        model.bones = [assets.Bone('tag_weapon', '', (0, 0, 0)), assets.Bone('tag_clip', 'tag_weapon', (0, 0, 0))]
        errors, warnings = assets.check(assets.AssetDef('a', 'weapon', triangles=1), model,
                                        textures(side=1024))
        self.assertEqual(errors, [])
        text = ' '.join(warnings)
        for wanted in ('budget', 'preset', 'magazine'):
            self.assertIn(wanted, text)


class Attach(unittest.TestCase):
    def test_asset_model_builds_as_a_mesh(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            assets.save_def(source, assets.AssetDef('crate'))
            assets.write_game(source, 'crate', square(), textures())
            placed = world.World('kino', inherit=True, models=[
                world.Model('Crate', (10.0, 0.0, 0.0), asset='crate'),
                world.Model('Crate2', asset='crate', scale=(2.0, 2.0, 2.0))])
            world.save(placed, source)
            loaded = world.load(source)
            self.assertEqual(loaded.models[0].asset, 'crate')
            self.assertEqual(world.validate(loaded), [])
            assets.attach(loaded, source)
            self.assertEqual([m.name for m in loaded.meshes], ['asset_crate'])
            self.assertEqual(loaded.models[1].scale, (0.2, 0.2, 0.2))
            layout = world.lower(loaded)
            self.assertEqual(len(layout.props), 1)
            self.assertEqual(len(layout.instances), 2)

    def test_missing_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            placed = world.World('kino', inherit=True, models=[world.Model('Gun', asset='gun')])
            with self.assertRaises(world.WorldError):
                assets.attach(placed, Path(temp))


if __name__ == '__main__':
    unittest.main()
