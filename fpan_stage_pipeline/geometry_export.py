"""Experimental local-position export; deliberately not a public export operator.

Only compiled-local vertex positions with unchanged indexed topology are mapped.
Object transforms, normals, UVs, colors, materials and animation are retained
from the source. Never infer an authoring-FBX-to-compiled mapping.
"""
import math
import hashlib
import pathlib
from . import fpan_binary


def position_edit_bytes(source, node_index, mesh, *, source_mode):
    return position_edits_bytes(source, [(node_index, mesh)], source_mode=source_mode)


def position_edits_bytes(source, edits, *, source_mode):
    """Build one candidate from multiple meshes, without writing any file.

    Validate the complete request before changing the private parsed document.
    Callers must separately gate object placement/animation edits: this function
    accepts meshes, not a scene, and exports ONLY their local vertex positions.
    """
    if source_mode != 'COMPILED_ONLY':
        raise ValueError('Position export requires compiled-local geometry')
    original = source.read_bytes()
    document = fpan_binary.parse(source)
    if fpan_binary.serialize(document) != original:
        raise ValueError('Source does not pass byte-exact serialization gate')
    nodes = document[2]
    pending = []
    seen = set()
    for node_index, mesh in edits:
        if not isinstance(node_index, int) or isinstance(node_index, bool):
            raise ValueError('Mesh node index must be an integer')
        if node_index in seen:
            raise ValueError(f'Duplicate mesh node {node_index}')
        seen.add(node_index)
        if not 0 <= node_index < len(nodes) or nodes[node_index]['type'] != 1:
            raise ValueError('Invalid mesh node')
        positions = _validated_positions(nodes[node_index], mesh)
        pending.append((node_index, positions))
    for node_index, positions in pending:
        node = nodes[node_index]
        for index, position in enumerate(positions):
            _old, normal, color, uv = node['vertices'][index]
            node['vertices'][index] = (position, normal, color, uv)
    return fpan_binary.serialize(document)


def _validated_positions(node, mesh):
    if len(mesh.vertices) != len(node['vertices']):
        raise ValueError('Vertex count changed; topology export is unsupported')
    expected = [(tuple(t), material) for material, triangles in node['sections'] for t in triangles]
    actual = [(tuple(p.vertices), p.material_index) for p in mesh.polygons]
    if actual != expected:
        raise ValueError('Indexed topology or material assignment changed')
    positions = []
    for vertex in mesh.vertices:
        position = tuple(vertex.co)
        if not all(math.isfinite(value) for value in position):
            raise ValueError('Nonfinite vertex position')
        positions.append(position)
    return positions


def selected_position_copy(scene, objects, destination):
    """Explicit selected-local-vertices experiment, never a full scene export.

    Refuse existing destinations and the extracted BG tree. Nothing is written
    until validation and candidate construction have both succeeded.
    """
    from . import placement
    if scene.get('fpan_source_mode') != 'COMPILED_ONLY':
        raise ValueError('Vertex copy requires a compiled-only import')
    stage = pathlib.Path(scene.get('fpan_stage_directory', '')).resolve()
    source = stage/'bg.fbx.bin'
    expected_hash = scene.get('fpan_compiled_sha256')
    if not expected_hash or hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
        raise ValueError('Source changed since import; reimport before exporting')
    output = pathlib.Path(destination).resolve()
    if output.is_relative_to(stage.parent):
        raise ValueError('Save outside the extracted BG tree; originals are protected')
    if output.exists():
        raise ValueError('Destination already exists; choose a new filename')
    targets = {}
    for obj in objects:
        target = placement.target_for_object(obj)
        if target is None or target.type != 'MESH':
            raise ValueError('Select only imported FPAN meshes or their placement controls')
        targets[target.as_pointer()] = target
    if not targets:
        raise ValueError('Select at least one imported FPAN mesh')
    edits = []
    for target in targets.values():
        if target.mode != 'OBJECT':
            raise ValueError('Leave Edit Mode before creating a vertex copy')
        if target.modifiers or target.data.shape_keys:
            raise ValueError('Modifiers/shape keys are not supported by vertex-copy export')
        current = target
        while current is not None:
            if current.constraints or current.animation_data is not None:
                raise ValueError('Blender animation/constraints are not exported; use native compiled tracks')
            if current.get('fpan_placement_control'):
                rest = current.get('fpan_placement_rest_matrix', [])
                values = [v for row in current.matrix_basis for v in row]
                if len(rest) != 16 or any(abs(a-b) > 1e-6 for a,b in zip(values, rest)):
                    raise ValueError(f'{target.name}: placement was moved/rotated/scaled. Vertex test copy saves Edit Mode vertices only. Keep your .blend; use Reset Placement Offset only if you want to discard that placement edit.')
            current = current.parent
        edits.append((int(target['fpan_node_index']), target.data))
    candidate = position_edits_bytes(source, edits, source_mode='COMPILED_ONLY')
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
        raise ValueError('Source changed during export; nothing written')
    # Exclusive creation also protects against a destination appearing after
    # the initial check. No game install or automatic replacement is performed.
    with output.open('xb') as stream:
        stream.write(candidate)
    return len(edits)
