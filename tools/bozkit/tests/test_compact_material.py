"""Synthetic material regression cases; no imaging dependencies required."""
import struct
import unittest
from bozkit import native


class CompactMaterialTests(unittest.TestCase):
    def test_primary_texture_is_decoded_and_editable(self):
        source = struct.pack('<BII', 1, 0x50000, 0x12345678) + b'preserved'
        material = native.decode_material(source)
        self.assertEqual(material.textures, [0x12345678])
        self.assertEqual(native.encode_material(material), source)
        material.textures[0] = 0x87654321
        self.assertEqual(native.encode_material(material),
                         struct.pack('<BII', 1, 0x50000, 0x87654321) + b'preserved')

    def test_truncated_reference_rejected(self):
        for size in range(5, 9):
            with self.assertRaises(ValueError):
                native.decode_material(bytes([1]) + bytes(size - 1))
