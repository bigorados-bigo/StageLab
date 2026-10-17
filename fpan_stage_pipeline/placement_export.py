"""Vertex-position and affine placement export without timeline baking.

Each node retains its independent native sample count. The placement delta
premultiplies its bind and every ORIGINAL local sample around the saved pivot.
Unified scene export also maps existing local vertex positions.
"""
import hashlib
import pathlib
from mathutils import Matrix
from . import fpan_binary, geometry_export, placement, affine_transform


def _near(a, b, tolerance=1e-6):
    return max(abs(x-y) for ra,rb in zip(a,b) for x,y in zip(ra,rb)) <= tolerance


def translation_edit_bytes(source, offsets):
    original = source.read_bytes()
    document = fpan_binary.parse(source)
    if fpan_binary.serialize(document) != original:
        raise ValueError('Source fails lossless serialization')
    _apply_translations(document, offsets)
    return fpan_binary.serialize(document)


def _apply_translations(document, offsets):
    nodes, tracks = document[2:]
    import math
    for index, offset in offsets.items():
        if not isinstance(index,int) or isinstance(index,bool) or not 0 < index < len(nodes):
            raise ValueError('Placement requires a native node')
        if len(offset) != 3 or not all(math.isfinite(v) for v in offset):
            raise ValueError('Invalid translation')
        matrices = [nodes[index]['matrix']] if nodes[index]['type']==1 else []
        if index < len(tracks):
            matrices += tracks[index]
        if not matrices:
            raise ValueError('Node has no native matrix storage for this placement')
        for matrix in matrices:
            for axis, delta in enumerate(offset):
                matrix[axis][3] += delta


def _apply_affine_offsets(document, offsets):
    """Fold a static parent-space edit into each ORIGINAL local sample.

    Never decompose/recompose native matrices or resample independent clocks.
    C * inverse(R) is the placement delta, including its authoring pivot.
    """
    import math
    nodes,tracks=document[2:]
    identity=Matrix.Identity(4)
    for index,delta in offsets.items():
        if not all(math.isfinite(v) for row in delta for v in row):
            raise ValueError('Nonfinite placement transform')
        if any(abs(a-b)>1e-6 for a,b in zip(delta[3],(0,0,0,1))):
            raise ValueError('Non-affine placement transform')
        if _near(delta.to_3x3(),identity.to_3x3(),tolerance=0):
            _apply_translations(document,{index:tuple(delta.translation)})
            continue
        if nodes[index]['type']==1:
            nodes[index]['matrix']=delta @ nodes[index]['matrix']
        if index<len(tracks) and tracks[index]:
            tracks[index]=[delta @ sample for sample in tracks[index]]
        elif nodes[index]['type']!=1:
            raise ValueError('Node has no native matrix storage for this placement')


def scene_translation_copy(scene, destination):
    return scene_edit_copy(scene, destination, include_vertices=False, translation_only=True)['placements']


def scene_edit_copy(scene, destination, *, include_vertices=True, translation_only=False, overwrite=False):
    if scene.get('fpan_source_mode') != 'COMPILED_ONLY':
        raise ValueError('Placement export requires compiled-only import')
    stage = pathlib.Path(scene.get('fpan_stage_directory','')).resolve()
    source = stage/'bg.fbx.bin'
    original = source.read_bytes()
    expected = scene.get('fpan_compiled_sha256')
    if hashlib.sha256(original).hexdigest() != expected:
        raise ValueError('Source changed since import; reimport first')
    output = pathlib.Path(destination).resolve()
    document = fpan_binary.parse(source)
    if fpan_binary.serialize(document) != original:
        raise ValueError('Source fails lossless serialization')
    nodes = document[2]
    objects = {}
    for obj in scene.objects:
        if obj.get('fpan_node_index') is not None:
            index = int(obj['fpan_node_index'])
            if index in objects:
                raise ValueError('Duplicate native node in scene')
            objects[index] = obj
    # Production import tags native nodes 1..N; its inspection root is not a
    # native animation target and intentionally lacks fpan_node_index.
    if 0 not in objects:
        root = scene.objects.get('FPAN_Root_0')
        if root is not None:
            objects[0] = root
    if set(objects) != set(range(len(nodes))):
        raise ValueError('Native nodes were added/deleted; reimport a complete stage')
    # Reconstruct the unchanged native hierarchy rather than inferring it from
    # current selection or names. Controls may be the only extra parent layer.
    parents = {}
    def visit(first, parent):
        index = first
        while 0 <= index < len(nodes):
            if index in parents or index == 0:
                raise ValueError('Invalid native hierarchy')
            parents[index] = parent
            visit(nodes[index]['child'],index)
            index = nodes[index]['sibling']
    visit(nodes[0]['child'],0)
    offsets = {}
    vertex_edits = {}
    identity = Matrix.Identity(4)
    for index,obj in objects.items():
        if obj.mode != 'OBJECT' or obj.constraints or obj.animation_data is not None:
            raise ValueError('Leave Edit Mode; Blender keys/constraints are not exported')
        if obj.type == 'MESH':
            if obj.modifiers or obj.data.shape_keys:
                raise ValueError('Modifiers/shape keys are not supported')
            positions = geometry_export._validated_positions(nodes[index],obj.data)
            if positions != [v[0] for v in nodes[index]['vertices']]:
                if not include_vertices:
                    raise ValueError('Vertex edits present: placement test copy retains original geometry. Use a separate unedited import for this test.')
                vertex_edits[index] = positions
        control = placement.control_for_object(obj)
        prefix=affine_transform.parent_prefix(obj)
        if not _near(obj.matrix_parent_inverse,prefix @ affine_transform.correction(obj)):
            raise ValueError('Native affine parent inverse changed outside placement editing')
        parent = control.parent if control else obj.parent
        if index and parent != objects.get(parents.get(index)):
            raise ValueError('Native parenting changed; export refused')
        if control is None:
            if index and not _near(affine_transform.parent_prefix(obj),identity):
                raise ValueError('Native parent inverse changed')
            continue
        if control.constraints or control.animation_data is not None:
            raise ValueError('Animated/constrained placement controls are unsupported')
        values = control.get('fpan_placement_rest_matrix',[])
        if len(values) != 16:
            raise ValueError('Placement rest matrix missing')
        rest = Matrix([values[i:i+4] for i in range(0,16,4)])
        if not _near(control.matrix_parent_inverse,identity) or not _near(affine_transform.parent_prefix(obj),rest.inverted()):
            raise ValueError('Placement parent inverse changed')
        if translation_only and not _near(control.matrix_basis.to_3x3(),identity.to_3x3()):
            raise ValueError('This first placement export supports movement (G) only; rotation/scale export is not validated yet')
        if abs(control.matrix_basis.to_3x3().determinant())<1e-12:
            raise ValueError('Zero/near-zero placement scale cannot round-trip faithfully; use a nonzero scale')
        if not _near(control.matrix_basis,rest,tolerance=0):
            offsets[index] = control.matrix_basis @ rest.inverted()
    if not offsets and not include_vertices:
        raise ValueError('No moved placement controls to export')
    for index,positions in vertex_edits.items():
        node = nodes[index]
        for vertex_index,position in enumerate(positions):
            node['vertices'][vertex_index] = (position,*node['vertices'][vertex_index][1:])
    _apply_affine_offsets(document,offsets)
    candidate = fpan_binary.serialize(document)
    if source.read_bytes() != original:
        raise ValueError('Source changed during export')
    from . import export_output
    export_output.write_candidate(output,candidate,source=source,overwrite=overwrite)
    return dict(placements=len(offsets),vertex_meshes=len(vertex_edits))
