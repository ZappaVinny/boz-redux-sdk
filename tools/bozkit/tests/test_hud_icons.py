"""HUD weapon icons: fitting pictures, free room on the sheet, weapons' rectangles (synthetic)."""
import unittest

from PIL import Image

from bozkit import hud_icons, reflect
from bozkit.hashing import iw_hash
from bozkit.weapons import PLAYER_WEAPON


class HudIconTests(unittest.TestCase):
    def test_fit_crops_scales_and_centres(self):
        picture = Image.new('RGBA', (400, 400), (0, 0, 0, 0))
        picture.paste((200, 200, 200, 255), (100, 150, 300, 250))   # 200 x 100 of gun
        fitted = hud_icons.fit(picture)
        self.assertEqual(fitted.size, hud_icons.SIZE)
        box = fitted.getchannel('A').getbbox()
        self.assertEqual(box[3] - box[1], 56)                          # fills the height
        self.assertAlmostEqual((box[0] + box[2]) / 2, hud_icons.SIZE[0] / 2, delta=1)

    def test_empty_picture(self):
        with self.assertRaises(hud_icons.IconError):
            hud_icons.fit(Image.new('RGBA', (10, 10)))

    def test_uv_round_trip(self):
        blob = reflect.Blob(PLAYER_WEAPON)
        self.assertIsNone(hud_icons.uv_of(blob))
        hud_icons.set_uv(blob, (10, 20, 187, 78))
        self.assertEqual(hud_icons.uv_of(blob), (10, 20, 187, 78))
        self.assertEqual(blob.properties[0].type_hash, iw_hash('CIwSVec2'))


if __name__ == '__main__':
    unittest.main()
