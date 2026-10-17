import struct

from mathutils import Matrix


def _i32(stream):
    return struct.unpack("<i", stream.read(4))[0]


def _u32(stream):
    return struct.unpack("<I", stream.read(4))[0]


def _matrix(stream):
    value = Matrix([struct.unpack("<4f", stream.read(16)) for _ in range(4)])
    value.transpose()
    return value


def parse(path):
    """Parse the known retail FbxExp stream without normalizing unknown fields."""
    with path.open("rb") as stream:
        stream.seek(0x14)
        textures = [
            struct.unpack("128s", stream.read(0x80))[0].split(b"\0", 1)[0].decode()
            for _ in range(_i32(stream))
        ]
        stream.seek(4, 1)
        materials = []
        for _ in range(_i32(stream)):
            name = struct.unpack("128s", stream.read(0x80))[0].split(b"\0", 1)[0].decode()
            materials.append((name, _i32(stream), _i32(stream), [_i32(stream) for _ in range(17)]))
        stream.seek(4, 1)
        nodes = []
        for _ in range(_i32(stream)):
            stream.seek(4, 1)
            node_type, child, sibling = struct.unpack("<iii", stream.read(12))
            node = {"type": node_type, "child": child, "sibling": sibling}
            if node_type == 1:
                node["blend"] = _i32(stream)
                # The second render field is a u32 flag in the maintained
                # Blender-MBTL-BG-IO format pattern/writer.  Reading it as a
                # float turned raw value 1 into the denormal 1.401298e-45 and
                # encouraged false opacity semantics.
                node["alpha"] = _u32(stream)
                node["matrix"] = _matrix(stream)
                vertices = []
                for _ in range(_i32(stream)):
                    vertices.append(
                        (
                            struct.unpack("<3f", stream.read(12)),
                            struct.unpack("<3f", stream.read(12)),
                            struct.unpack("<4f", stream.read(16)),
                            struct.unpack("<2f", stream.read(8)),
                        )
                    )
                node["vertices"] = vertices
                sections = []
                for _ in range(_i32(stream)):
                    material_index = _i32(stream)
                    index_count = _i32(stream)
                    indices = struct.unpack(f"<{index_count}i", stream.read(index_count * 4))
                    sections.append((material_index, [indices[n:n + 3] for n in range(0, index_count, 3)]))
                node["sections"] = sections
            nodes.append(node)
        stream.seek(4, 1)
        animations = []
        for _ in range(_i32(stream)):
            animations.append([_matrix(stream) for _ in range(_i32(stream))])
        if stream.tell() != path.stat().st_size:
            raise RuntimeError(f"FbxExp parse ended at {stream.tell()} of {path.stat().st_size} bytes")
    return textures, materials, nodes, animations


def _fixed_string(value, size=0x80):
    encoded = value.encode("utf-8")
    if len(encoded) >= size:
        raise ValueError(f"FbxExp string is too long for {size} bytes: {value!r}")
    return encoded + (b"\0" * (size - len(encoded)))


def _stored_matrix(value):
    matrix = value.copy()
    matrix.transpose()
    return struct.pack("<16f", *(component for row in matrix for component in row))


def serialize(document):
    """Serialize a parsed FbxExp document without Blender normalization.

    This is the lossless binary-layer gate. Editable Blender export must not
    use it until changes are mapped back into this document deliberately.
    """
    textures, materials, nodes, animations = document
    texture_blob = b"".join(_fixed_string(name) for name in textures)

    material_parts = []
    for name, material_index, texture_index, parameters in materials:
        if len(parameters) != 17:
            raise ValueError("FbxExp material must contain exactly 17 raw parameters")
        material_parts.append(_fixed_string(name))
        material_parts.append(struct.pack("<ii17i", material_index, texture_index, *parameters))
    material_blob = b"".join(material_parts)

    node_parts = []
    for node in nodes:
        payload = bytearray(struct.pack("<iii", node["type"], node["child"], node["sibling"]))
        if node["type"] == 1:
            payload.extend(struct.pack("<iI", node["blend"], node["alpha"]))
            payload.extend(_stored_matrix(node["matrix"]))
            vertices = node["vertices"]
            payload.extend(struct.pack("<i", len(vertices)))
            for position, normal, color, uv in vertices:
                payload.extend(struct.pack("<12f", *position, *normal, *color, *uv))
            sections = node["sections"]
            payload.extend(struct.pack("<i", len(sections)))
            for material_index, triangles in sections:
                indices = [index for triangle in triangles for index in triangle]
                payload.extend(struct.pack("<ii", material_index, len(indices)))
                if indices:
                    payload.extend(struct.pack(f"<{len(indices)}i", *indices))
        node_parts.append(struct.pack("<i", len(payload) + 4) + payload)
    node_blob = b"".join(node_parts)

    animation_parts = []
    for track in animations:
        animation_parts.append(struct.pack("<i", len(track)))
        animation_parts.extend(_stored_matrix(matrix) for matrix in track)
    animation_blob = b"".join(animation_parts)

    output = bytearray(b"fbxex" + (b"\0" * 11))
    for blob, count in (
        (texture_blob, len(textures)),
        (material_blob, len(materials)),
        (node_blob, len(nodes)),
        (animation_blob, len(animations)),
    ):
        # Retail sectionSize includes its own size/count header (8 bytes).
        output.extend(struct.pack("<ii", len(blob) + 8, count))
        output.extend(blob)
    return bytes(output)
