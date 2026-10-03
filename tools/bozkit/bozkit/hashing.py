"""IwHashString, the 32-bit name hash the game uses for classes, fields, events and resources."""


def iw_hash(text: str) -> int:
    """h = 5381; for each byte (A-Z lowercased): h = h * 33 + c, 32-bit (game image 0x24ba2c)."""
    h = 5381
    for c in text.encode('latin-1'):
        if 0x41 <= c <= 0x5a:
            c += 0x20
        h = (h * 33 + c) & 0xFFFFFFFF
    return h
