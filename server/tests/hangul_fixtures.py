"""Small original document fixtures, generated without Hancom or external downloads."""

import io
import struct
import zipfile
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def compound(streams):
    """Write a minimal CFB v3 container including its FAT and miniFAT."""
    free, end = 0xFFFFFFFF, 0xFFFFFFFE
    nodes = {"": {"name": "Root Entry", "kind": 5, "children": []}}
    for path, content in streams.items():
        components = path.split("/")
        for depth, name in enumerate(components, 1):
            key, parent = "/".join(components[:depth]), "/".join(components[:depth - 1])
            if key not in nodes:
                nodes[key] = {"name": name, "kind": 2 if depth == len(components) else 1,
                              "children": [], "data": content if depth == len(components) else b""}
                nodes[parent]["children"].append(key)
    indexes = {key: index for index, key in enumerate(nodes)}
    sectors, fat, mini, mini_fat = [], [], bytearray(), []

    def allocate(data):
        if not data:
            return end
        first = len(sectors)
        for offset in range(0, len(data), 512):
            sectors.append(data[offset:offset + 512].ljust(512, b"\0"))
            fat.append(len(sectors))
        fat[-1] = end
        return first

    for node in list(nodes.values())[1:]:
        data = node["data"]
        node["size"] = len(data)
        if node["kind"] == 1 or not data:
            node["start"] = end
        elif len(data) < 4096:
            node["start"] = len(mini_fat)
            for offset in range(0, len(data), 64):
                mini.extend(data[offset:offset + 64].ljust(64, b"\0"))
                mini_fat.append(len(mini_fat) + 1)
            mini_fat[-1] = end
        else:
            node["start"] = allocate(data)
    nodes[""]["start"], nodes[""]["size"] = allocate(mini), len(mini)
    mini_bytes = b"".join(struct.pack("<I", value) for value in mini_fat)
    mini_bytes += b"\xff" * (-len(mini_bytes) % 512)
    mini_start = allocate(mini_bytes)
    directory = bytearray()
    for key, node in nodes.items():
        name = (node["name"] + "\0").encode("utf-16le")
        entry = bytearray(128)
        entry[:len(name)] = name
        struct.pack_into("<HBB", entry, 64, len(name), node["kind"], 1)
        parent = nodes.get(key.rpartition("/")[0]) if key else None
        siblings = parent["children"] if parent else []
        position = siblings.index(key) if key in siblings else -1
        right = indexes[siblings[position + 1]] if 0 <= position < len(siblings) - 1 else free
        child = indexes[node["children"][0]] if node["children"] else free
        struct.pack_into("<III", entry, 68, free, right, child)
        struct.pack_into("<IQ", entry, 116, node["start"], node["size"])
        directory.extend(entry)
    directory_start = allocate(directory)
    fat_sector = len(sectors)
    fat.append(0xFFFFFFFD)
    assert len(fat) <= 128, "Fixture requires a larger FAT"
    sectors.append(struct.pack("<128I", *(fat + [free] * (128 - len(fat)))))
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, directory_start, 0, 4096,
                     mini_start, len(mini_bytes) // 512, end, 0)
    struct.pack_into("<109I", header, 76, fat_sector, *([free] * 108))
    return bytes(header) + b"".join(sectors)


def record(tag, payload, level=0):
    size = len(payload)
    header = struct.pack("<I", tag | (level << 10) | (min(size, 4095) << 20))
    return header + (struct.pack("<I", size) if size >= 4095 else b"") + payload


def paragraph(text, level=0):
    return record(66, b"\0" * 22, level) + record(67, (text + "\r").encode("utf-16le"), level + 1)


def compress(data, trailer=False):
    compressor = zlib.compressobj(wbits=-15)
    result = compressor.compress(data) + compressor.flush()
    return result + (struct.pack("<II", zlib.crc32(data), len(data)) if trailer else b"")


def distribution(data):
    seed, key = 12345, b"0123456789abcdef"
    header = bytearray(256)
    struct.pack_into("<I", header, 0, seed)
    offset = 4 + (seed & 15)
    header[offset:offset + 16] = key
    masks, state = [], seed
    while len(masks) < 256:
        state = (state * 214013 + 2531011) & 0xFFFFFFFF
        mask = (state >> 16) & 255
        state = (state * 214013 + 2531011) & 0xFFFFFFFF
        masks.extend([mask] * (((state >> 16) & 15) + 1))
    for index in range(4, 256):
        header[index] ^= masks[index]
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = encryptor.update(data + b"\0" * (-len(data) % 16)) + encryptor.finalize()
    return record(28, header) + ciphertext


def hwp(sections=None, *, flags=1, trailer=False, version=5):
    sections = sections if sections is not None else [paragraph("한글 문서 본문")]
    header = b"HWP Document File" + b"\0" * 15 + struct.pack("<II", version << 24, flags)
    info = record(16, struct.pack("<H", len(sections)) + b"\0" * 24)
    streams = {"FileHeader": header.ljust(256, b"\0"),
               "DocInfo": compress(info, trailer) if flags & 1 else info,
               "PrvText": "오래된 미리보기".encode("utf-16le")}
    for index, section in enumerate(sections):
        data = compress(section, trailer) if flags & 1 else section
        streams[("ViewText" if flags & 4 else "BodyText") + f"/Section{index}"] = (
            distribution(data) if flags & 4 else data)
    return compound(streams)


def section(body):
    return ('<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
            'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">' + body + '</hs:sec>')


def hwpx(sections=None, order=None, *, extra=None, relative=False):
    sections = sections if sections is not None else ['<hp:p><hp:run><hp:t>한글 문서 본문</hp:t></hp:run></hp:p>']
    order = order if order is not None else list(range(len(sections)))
    prefix = "" if relative else "Contents/"
    manifest = ''.join(f'<opf:item id="s{i}" href="{prefix}section{i}.xml" media-type="application/xml"/>'
                       for i in range(len(sections)))
    spine = ''.join(f'<opf:itemref idref="s{i}"/>' for i in order)
    package = (f'<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
               f'<opf:manifest>{manifest}</opf:manifest><opf:spine>{spine}</opf:spine></opf:package>')
    members = {"mimetype": "application/hwp+zip", "Contents/content.hpf": package,
               "Preview/PrvText.txt": "오래된 미리보기"}
    members.update({f"Contents/section{i}.xml": section(body) for i, body in enumerate(sections)})
    members.update(extra or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()
