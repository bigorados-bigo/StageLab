import hashlib
import pathlib
import re

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix

from . import fpan_binary
from . import render_contract
from . import assets


_RUNTIME_CACHE = {}
_IMAGE_ALPHA_CACHE = {}


def _flat_matrix(matrix):
    return [matrix[row][column] for row in range(4) for column in range(4)]


def _matrix_from_flat(values):
    return Matrix([values[row * 4:(row + 1) * 4] for row in range(4)])


def _matrix_delta(left, right):
    return max(abs(left[row][column] - right[row][column]) for row in range(4) for column in range(4))


def _compiled_cycle_samples(track, runtime_period, tolerance=1e-5):
    """Return the decoded transform cycle inside a possibly padded track."""
    limit = min(len(track), max(1, int(round(runtime_period))))
    for candidate in range(1, limit + 1):
        checks = min(len(track) - candidate, max(candidate * 3, limit - candidate))
        if checks <= 0:
            continue
        if all(_matrix_delta(track[index], track[index + candidate]) <= tolerance for index in range(checks)):
            return candidate
    return limit


def _loop_sample_index(runtime_frame, runtime_period, compiled_cycle):
    """Map a 60 Hz loop phase onto all samples of its decoded cycle."""
    phase = runtime_frame % runtime_period
    return min(compiled_cycle - 1, (phase * compiled_cycle) // runtime_period)


def _compiled_track_period(track, tolerance=2e-5):
    """Recover an exact repeated matrix cycle without naming stage assets.

    Exported tracks are sometimes padded with several copies of their object-
    local cycle.  Accept only a candidate that predicts every later sample;
    otherwise retain the complete decoded track as its runtime cycle.
    """
    length = len(track)
    if length <= 1:
        return length
    # Repetition boundaries found in retail stages are frame-aligned. Trying
    # endpoint-compatible candidates first avoids quadratic work on long tracks.
    candidates = []
    for period in range(1, length):
        if _matrix_delta(track[0], track[period]) <= tolerance:
            candidates.append(period)
    for period in candidates:
        if all(_matrix_delta(track[index], track[index % period]) <= tolerance for index in range(period, length)):
            return period
    return length


def _runtime_animations(scene):
    stage_value = scene.get("fpan_stage_directory")
    if not stage_value:
        return None
    compiled = pathlib.Path(stage_value) / "bg.fbx.bin"
    if not compiled.is_file():
        return None
    key = (str(compiled), compiled.stat().st_mtime_ns, compiled.stat().st_size)
    cached = _RUNTIME_CACHE.get(key)
    if cached is None:
        cached = fpan_binary.parse(compiled)[3]
        _RUNTIME_CACHE.clear()
        _RUNTIME_CACHE[key] = cached
    return cached


def animation_preview_mode(scene):
    settings = getattr(scene, "fpan_stage", None)
    if settings is not None and getattr(settings, "animation_preview_mode", ""):
        return settings.animation_preview_mode
    return scene.get("fpan_animation_preview_mode", "COMPILED")


@persistent
def apply_compiled_runtime_preview(scene, _depsgraph=None):
    from . import affine_transform
    mode = animation_preview_mode(scene)
    if mode not in {"COMPILED", "AUTHORING"}:
        return
    animations = _runtime_animations(scene)
    if animations is None:
        return
    runtime_frame = max(0, int(scene.frame_current) - 1)
    from .animation_clock import sample_spacing, sample_phase, affine_mix
    spacing = sample_spacing(scene)
    for obj in scene.objects:
        node_index = obj.get("fpan_node_index")
        base_values = obj.get("fpan_imported_local_matrix")
        if node_index is None or base_values is None or int(node_index) >= len(animations):
            continue
        track = animations[int(node_index)]
        # A one-sample compiled track is still authoritative. BG004 contains
        # hundreds whose sole matrix differs materially from the static node
        # matrix; skipping them multiplies the wrong parent transforms through
        # foliage/effect branches and produces displaced or giant objects.
        if not track:
            continue
        # Editable/Safe is a hybrid view: Blender Actions are authoritative
        # where materialized, while untouched lazy tracks continue to use the
        # lossless sampled matrices. Otherwise selecting Editable made most of
        # a compiled-only stage stop moving.
        if mode == "AUTHORING" and obj.animation_data is not None:
            affine_transform.release(obj)
            continue
        compiled_only = scene.get("fpan_source_mode") == "COMPILED_ONLY"
        if obj.get("fpan_infinite_post_repeat"):
            # Only source tracks explicitly marked infinite may wrap. Some
            # compiled arrays are padded with many repetitions; retain the
            # decoded first cycle without rescaling its sample rate.
            cycle = max(1, min(len(track), int(obj.get("fpan_compiled_cycle_samples", len(track)))))
            sample_index = runtime_frame % cycle
        elif compiled_only:
            # Native BG004 captures across the 400-sample boundary show the
            # child wrapping to samples 11/71 while its longer parent advances
            # to 411/471. Tracks therefore own independent full-length cycles.
            # Earlier flying geometry came from applying a false bind delta,
            # not from the independent modulo clock.
            sample_index = runtime_frame % len(track)
        else:
            # Finite tracks hold their last authored sample. Modulo here caused
            # camera masks/fog planes to respawn and late-timeline jumps.
            sample_index = min(runtime_frame, len(track) - 1)
        if spacing > 1:
            cycle_count = cycle if obj.get("fpan_infinite_post_repeat") else len(track)
            sample_index, following, fraction = sample_phase(
                runtime_frame, spacing, cycle_count,
                loop=compiled_only or bool(obj.get("fpan_infinite_post_repeat")),
            )
            sample = affine_mix(track[sample_index], track[following], fraction)
        else:
            sample = track[sample_index]
        # Diagnostic only.  This is the convention used by the community
        # fbx.bin importer: each stored sample is itself the object's local
        # transform.  Do not combine it with an inferred bind-space delta.
        local_matrix = sample.copy()
        # Preserve the exact affine matrix. Decomposing and rebuilding it loses
        # shear/pivot information and visibly displaces foliage/effects.
        affine_transform.set_native_basis(obj,local_matrix)


def refresh_animation_preview(scene):
    scene["fpan_animation_preview_mode"] = animation_preview_mode(scene)
    if animation_preview_mode(scene) == "COMPILED":
        scene.frame_end = int(scene.get("fpan_compiled_timeline_end", scene.frame_end))
    else:
        authoring_end = int(scene.get("fpan_authoring_timeline_end", scene.frame_end))
        if scene.get("fpan_source_mode") == "COMPILED_ONLY":
            authoring_end = max(authoring_end, int(scene.get("fpan_compiled_timeline_end", authoring_end)))
        scene.frame_end = authoring_end
    scene.frame_set(scene.frame_current)


def register_handlers():
    if apply_compiled_runtime_preview not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(apply_compiled_runtime_preview)


def unregister_handlers():
    if apply_compiled_runtime_preview in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(apply_compiled_runtime_preview)
    _RUNTIME_CACHE.clear()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_names(path):
    pattern = re.compile(r'^\s*Model:\s*"Model::([^"]+)",')
    names = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = pattern.match(line)
            if match:
                names.append(match.group(1))
    return names


def compiled_authoring_names(declared_names):
    """Drop FBX-only helpers while preserving compiler/declaration order.

    FbxExp retains meshes and the null ancestry needed to transform them, but
    some authoring FBXs also contain unrelated empty helpers.  Filtering by
    structural contribution avoids stage/object-name rules.
    """
    retained = set()
    for name in declared_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            continue
        current = obj
        while current is not None:
            retained.add(current.name)
            current = current.parent
    return [name for name in declared_names if name in retained]


def is_ascii_authoring_fbx(path):
    """Return true only for the retained text FBX used as authoring evidence.

    Binary FBX files in missing-source stage folders were reconstructed by our
    own batch converter.  They must not silently acquire authoring authority.
    """
    with path.open("rb") as stream:
        prefix = stream.read(4096)
    return not prefix.startswith(b"Kaydara FBX Binary") and b"FBXHeaderExtension" in prefix


def import_compiled_geometry(stage, textures, materials, nodes, stage_scale=1.0):
    """Construct a native editable Blender scene directly from FbxExp data.

    This is the source-of-truth path for stages without a retained developer
    FBX.  Node names are intentionally synthetic because FbxExp stores no
    object names.  Unknown authoring pivots and source curve metadata are not
    fabricated.
    """
    material_objects = []
    for material_index, material_record in enumerate(materials):
        material_name, _index, texture_index, _values = material_record
        material = bpy.data.materials.new(name=material_name or f"FPAN_Material_{material_index}")
        material.use_nodes = True
        nodes_tree = material.node_tree.nodes
        links = material.node_tree.links
        output = nodes_tree.get("Material Output")
        image_node = nodes_tree.new("ShaderNodeTexImage")
        if 0 <= int(texture_index) < len(textures):
            reference = textures[int(texture_index)]
            texture_path = assets.resolve_texture_path(stage, reference)
            if texture_path is not None:
                image_node.image = bpy.data.images.load(str(texture_path), check_existing=True)
                image_node.image['fpan_texture_reference'] = reference
        emission = nodes_tree.new("ShaderNodeEmission")
        if image_node.image is not None:
            links.new(image_node.outputs["Color"], emission.inputs["Color"])
        if output is not None:
            links.new(emission.outputs["Emission"], output.inputs["Surface"])
        material_objects.append(material)

    objects = []
    names = []
    for node_index, node in enumerate(nodes):
        name = "FPAN_Root_0" if node_index == 0 else f"FPAN_Node_{node_index:04d}"
        if node.get("type") == 1:
            mesh = bpy.data.meshes.new(name=f"{name}_Mesh")
            positions = [vertex[0] for vertex in node.get("vertices", ())]
            faces = []
            face_materials = []
            for material_index, triangles in node.get("sections", ()):
                faces.extend(tuple(triangle) for triangle in triangles)
                face_materials.extend([int(material_index)] * len(triangles))
            mesh.from_pydata(positions, [], faces)
            mesh.update()
            obj = bpy.data.objects.new(name, mesh)
            bpy.context.scene.collection.objects.link(obj)
            for material in material_objects:
                mesh.materials.append(material)
            for polygon, material_index in zip(mesh.polygons, face_materials):
                polygon.material_index = material_index
            uv_layer = mesh.uv_layers.new(name="UVMap")
            vertices = node.get("vertices", ())
            for loop in mesh.loops:
                uv_layer.data[loop.index].uv = vertices[loop.vertex_index][3]
            color_layer = mesh.color_attributes.new(
                name="Color", type="FLOAT_COLOR", domain="CORNER"
            )
            for loop in mesh.loops:
                color_layer.data[loop.index].color = vertices[loop.vertex_index][2]
            from . import affine_transform
            affine_transform.set_native_basis(obj,node.get("matrix", Matrix.Identity(4)))
        else:
            obj = bpy.data.objects.new(name, None)
            bpy.context.scene.collection.objects.link(obj)
        objects.append(obj)
        if node_index > 0:
            names.append(name)

    def attach_sibling_chain(first_index, parent_index, visited):
        index = first_index
        while index is not None and index >= 0 and index < len(nodes) and index not in visited:
            visited.add(index)
            objects[index].parent = objects[parent_index]
            child = int(nodes[index].get("child", -1))
            if child >= 0:
                attach_sibling_chain(child, index, visited)
            index = int(nodes[index].get("sibling", -1))

    visited = {0}
    root_child = int(nodes[0].get("child", -1)) if nodes else -1
    if root_child >= 0:
        attach_sibling_chain(root_child, 0, visited)
    objects[0].rotation_euler[0] = 1.5707963267948966
    objects[0].scale = (stage_scale, stage_scale, stage_scale)
    return names


def repeating_models(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    takes_at = text.find("Takes:")
    if takes_at < 0:
        return set()
    takes = text[takes_at:]
    starts = list(re.finditer(r'^\s*Model:\s*"Model::([^"]+)"\s*\{', takes, re.M))
    result = set()
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(takes)
        block = takes[match.end():end]
        if re.search(r'Post-Extrapolation:\s*\{\s*Type:\s*R\s*Repetition:\s*-1', block, re.S):
            result.add(match.group(1))
    return result


def source_material_opacities(path):
    """Read FBX material opacity without relying on Blender's shader import."""
    text = path.read_text(encoding="utf-8", errors="replace")
    starts = list(re.finditer(r'^\s*Material:\s*"Material::([^"]+)",', text, re.M))
    result = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.end():end]
        value = re.search(r'Property:\s*"Opacity"[^\r\n]*,([-+0-9.eE]+)\s*$', block, re.M)
        result[match.group(1)] = float(value.group(1)) if value else 1.0
    return result


def stage_render_settings(stage_directory):
    """Read the stage's own BgList record by DataFile, independent of ID."""
    path = stage_directory.parent / "BgList.txt"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="cp932", errors="replace")
    starts = list(re.finditer(r'^\s*Bg_[^=\r\n]+\s*=\s*\r?\n\s*\{', text, re.M))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = re.sub(r'//[^\r\n]*', '', text[match.end():end])
        data_file = re.search(r'\bDataFile\s*=\s*"([^"]+)"', block)
        if data_file is None or data_file.group(1).lower() != stage_directory.name.lower():
            continue
        settings = {}
        for key, raw in re.findall(
            r'\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\[[^\]]*\]|"[^"]*"|[^,\r\n}]+)',
            block,
        ):
            value = raw.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    settings[key] = tuple(float(item.strip()) for item in value[1:-1].split(","))
                except ValueError:
                    continue
            elif value.startswith('"') and value.endswith('"'):
                settings[key] = value[1:-1]
            else:
                try:
                    settings[key] = float(value)
                except ValueError:
                    continue
        return settings
    return {}


def clear_scene_data():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)
    for image in list(bpy.data.images):
        bpy.data.images.remove(image)
    _IMAGE_ALPHA_CACHE.clear()


def replace_material(material, additive, alpha_visibility, opacity_scale, alpha_mode):
    image = next(
        (node.image for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and node.image),
        None,
    )
    if image is None:
        return
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    links.new(texture.outputs["Color"], emission.inputs["Color"])
    if alpha_visibility:
        mix = nodes.new("ShaderNodeMixShader")
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        alpha_socket = texture.outputs["Alpha"]
        if opacity_scale != 1.0:
            opacity = nodes.new("ShaderNodeMath")
            opacity.operation = "MULTIPLY"
            opacity.inputs[1].default_value = opacity_scale
            links.new(alpha_socket, opacity.inputs[0])
            alpha_socket = opacity.outputs[0]
        links.new(alpha_socket, mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emission.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs[0])
        material.surface_render_method = alpha_mode
        material.use_transparent_shadow = False
    else:
        links.new(emission.outputs[0], output.inputs[0])
    # Do not inherit an FBX material's stale hashed/dithered mode. The shader
    # graph determines whether alpha participates; BLENDED is the common
    # non-stochastic surface mode for this approximation.
    material.surface_render_method = alpha_mode
    emission.inputs["Strength"].default_value = 1.0
    material["fpan_additive"] = additive
    material["fpan_uses_texture_alpha_for_visibility"] = alpha_visibility
    material["fpan_preview_opacity_scale"] = opacity_scale
    material["fpan_blend_equation"] = "SRC_ALPHA,ONE" if additive else "SRC_ALPHA,INV_SRC_ALPHA"


def add_loop_preview(source, names, animations):
    repeating = repeating_models(source)
    node_index_by_name = {name: index for index, name in enumerate(names, start=1)}
    if not bpy.data.actions:
        return 0
    action = bpy.data.actions[0]
    slot_by_handle = {slot.handle: slot for slot in action.slots}
    looped = 0
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for bag in strip.channelbags:
                slot = slot_by_handle.get(bag.slot_handle)
                if slot is None:
                    continue
                name = slot.identifier[2:] if slot.identifier.startswith("OB") else slot.identifier
                obj = bpy.data.objects.get(name)
                frames = [point.co.x for curve in bag.fcurves for point in curve.keyframe_points]
                if obj is not None and frames:
                    obj["fpan_authored_track_start"] = min(frames)
                    obj["fpan_authored_track_end"] = max(frames)
                    obj["fpan_authored_loop_period"] = max(frames) - min(frames)
                if name not in repeating:
                    continue
                for curve in bag.fcurves:
                    modifier = curve.modifiers.new(type="CYCLES")
                    modifier.mode_before = "REPEAT"
                    modifier.mode_after = "REPEAT"
                if obj is not None:
                    obj["fpan_infinite_post_repeat"] = True
                    node_index = node_index_by_name.get(name)
                    if node_index is not None and node_index < len(animations):
                        runtime_period = (max(frames) - min(frames)) * 2.0
                        obj["fpan_compiled_cycle_samples"] = _compiled_cycle_samples(
                            animations[node_index], runtime_period
                        )
                looped += 1
    for index, name in enumerate(names, start=1):
        obj = bpy.data.objects.get(name)
        if obj is not None and index < len(animations):
            obj["fpan_compiled_track_samples"] = len(animations[index])
    action["fpan_loop_preview"] = "Source FBX repetition mapped to Blender Cycles modifiers; source keys remain editable"
    return looped


def retime_source_actions_for_runtime_preview(frame_scale=1.0):
    """Keep authored key numbers on the observed 60 Hz engine playback grid."""
    for action in bpy.data.actions:
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type != "KEYFRAME":
                    continue
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            point.co.x *= frame_scale
                            point.handle_left.x *= frame_scale
                            point.handle_right.x *= frame_scale
        action["fpan_source_time_mode_fps"] = 30.0
        action["fpan_runtime_preview_fps"] = 60.0
        action["fpan_time_scale"] = frame_scale
    for obj in bpy.data.objects:
        for key in ("fpan_authored_track_start", "fpan_authored_track_end", "fpan_authored_loop_period"):
            if key in obj:
                obj[key] = float(obj[key]) * frame_scale


def materialize_compiled_track(obj, node_index, track):
    """Create editable keys for one compiled track on explicit request."""
    if obj is None or len(track) <= 1 or obj.animation_data is not None:
        return False
    first = track[0]
    if not any(
        max(abs(value[row][column] - first[row][column]) for row in range(4) for column in range(4)) > 1e-6
        for value in track[1:]
    ):
        return False
    compiled_only = bool(obj.get("fpan_lazy_compiled_track"))
    from .animation_clock import sample_spacing
    spacing = sample_spacing(bpy.context.scene) if compiled_only else 1
    base_values = obj.get("fpan_imported_local_matrix")
    imported_local = _matrix_from_flat(base_values) if base_values is not None else obj.matrix_local.copy()
    # Native BG004 captures and both community importers agree that compiled
    # samples are complete object-local matrices.  For a compiled-only import,
    # adding a bind delta corrupts the transform.  The delta path is retained
    # only for an ASCII-FBX object whose coordinate conversion has not yet been
    # capture-validated against the compiled hierarchy.
    compiled_to_imported = None if compiled_only else imported_local @ first.inverted_safe()
    action = bpy.data.actions.new(name=f"FPAN_Compiled_{node_index}_{obj.name}")
    action_slot = action.slots.new("OBJECT", obj.name)
    obj.animation_data_create()
    obj.animation_data.action = action
    obj.animation_data.action_slot = action_slot
    obj.rotation_mode = "QUATERNION"
    previous_rotation = None
    for sample_index, compiled_matrix in enumerate(track):
        local_matrix = compiled_matrix if compiled_to_imported is None else compiled_to_imported @ compiled_matrix
        location, rotation, scale = local_matrix.decompose()
        if previous_rotation is not None and rotation.dot(previous_rotation) < 0.0:
            rotation.negate()
        previous_rotation = rotation.copy()
        obj.location = location
        obj.rotation_quaternion = rotation
        obj.scale = scale
        frame = sample_index * spacing + 1
        obj.keyframe_insert(data_path="location", frame=frame, group="FPAN Transform")
        obj.keyframe_insert(data_path="rotation_quaternion", frame=frame, group="FPAN Transform")
        obj.keyframe_insert(data_path="scale", frame=frame, group="FPAN Transform")
    if compiled_only:
        # Blender Cycles repeats over the distance between its first and last
        # keys. Duplicate sample zero at N+1 so N stored discrete samples have
        # an N-frame period rather than the off-by-one period N-1.
        location, rotation, scale = track[0].decompose()
        if previous_rotation is not None and rotation.dot(previous_rotation) < 0.0:
            rotation.negate()
        obj.location = location
        obj.rotation_quaternion = rotation
        obj.scale = scale
        closing_frame = len(track) * spacing + 1
        obj.keyframe_insert(data_path="location", frame=closing_frame, group="FPAN Transform")
        obj.keyframe_insert(data_path="rotation_quaternion", frame=closing_frame, group="FPAN Transform")
        obj.keyframe_insert(data_path="scale", frame=closing_frame, group="FPAN Transform")
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type != "KEYFRAME":
                    continue
                for bag in strip.channelbags:
                    if bag.slot_handle != action_slot.handle:
                        continue
                    for curve in bag.fcurves:
                        modifier = curve.modifiers.new(type="CYCLES")
                        modifier.mode_before = "REPEAT"
                        modifier.mode_after = "REPEAT"
    obj.matrix_local = imported_local
    obj["fpan_animation_source"] = "compiled_selected_track"
    obj["fpan_authored_track_start"] = 1
    obj["fpan_authored_track_end"] = len(track) * spacing + 1 if compiled_only else len(track)
    obj["fpan_authored_loop_period"] = len(track) * spacing if compiled_only else 0
    obj["fpan_infinite_post_repeat"] = compiled_only
    obj["fpan_lazy_compiled_track"] = False
    obj["fpan_editable_matrix_contract"] = (
        "DIRECT_COMPILED_LOCAL" if compiled_only else "ASCII_FBX_BIND_DELTA_PROVISIONAL"
    )
    action["fpan_animation_source"] = "bg.fbx.bin sampled local matrices"
    action["fpan_node_index"] = node_index
    return True


def extend_authoring_timeline(scene, sample_count):
    """Expose newly materialized keys without changing compiled source data."""
    end = max(int(scene.get("fpan_authoring_timeline_end", 1)), int(sample_count))
    scene["fpan_authoring_timeline_end"] = end
    if animation_preview_mode(scene) == "AUTHORING":
        scene.frame_end = end


def supplement_compiled_tracks(names, animations):
    """Add editable actions for compiled tracks absent from the source FBX.

    FbxExp matrices are sampled local transforms.  The source FBX import is
    retained as the coordinate-system authority, so each compiled track is
    transferred as a delta from its first sample onto the imported local
    matrix.  This applies to every missing changing track; it does not identify
    effects by name or stage.
    """
    supplemented = 0
    for node_index, name in enumerate(names, start=1):
        if node_index >= len(animations):
            break
        track = animations[node_index]
        obj = bpy.data.objects.get(name)
        if obj is None or len(track) <= 1 or obj.animation_data is not None:
            continue
        if materialize_compiled_track(obj, node_index, track):
            obj["fpan_animation_source"] = "compiled_missing_source_track"
            supplemented += 1
    return supplemented


def image_alpha_stats(material):
    image = next(
        (node.image for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and node.image),
        None,
    )
    if image is None:
        return 1.0, 1.0, 0.0, 0.0
    key = (image.filepath_raw, tuple(image.size))
    cached = _IMAGE_ALPHA_CACHE.get(key)
    if cached is not None:
        return cached
    pixels = image.pixels[:]
    alpha = pixels[3::4]
    cached = (
        min(alpha),
        max(alpha),
        sum(value < 0.999 for value in alpha) / len(alpha),
        sum(value < 0.01 for value in alpha) / len(alpha),
    ) if alpha else (1.0, 1.0, 0.0, 0.0)
    _IMAGE_ALPHA_CACHE[key] = cached
    return cached


def material_policy(compiled_blend_mode, compiled_alpha_flag, source_opacity, alpha_stats):
    """Map only decoded FPAN fields to a conservative Blender preview.

    No stage, object, material, or texture names may participate here.  The
    shader is explicitly a preview adapter; the original decoded values remain
    attached to the object for a future exact renderer/exporter.
    """
    additive = compiled_blend_mode > 0
    _alpha_min, _alpha_max, nonopaque_fraction, _nearzero_fraction = alpha_stats
    if additive:
        render_class = "ADDITIVE"
    elif source_opacity < 0.999999 or compiled_alpha_flag != 0:
        render_class = "TRANSLUCENT"
    elif nonopaque_fraction <= 1e-6:
        render_class = "OPAQUE"
    else:
        render_class = "TRANSLUCENT"
    alpha_visibility = render_class != "OPAQUE"
    # Captured UNI2 draws combine alpha blending with D3DCMP_GREATER/0 alpha
    # testing. Blender's DITHERED mode is not that contract: it introduces a
    # visible stochastic screen-door pattern throughout graded alpha. BLENDED
    # naturally contributes nothing for alpha == 0 and is the least-lossy
    # ordinary-material approximation until the dedicated RenderEngine owns
    # alpha test, blend equation, author draw order, and depth writes.
    alpha_mode = "BLENDED"
    return alpha_visibility, source_opacity, alpha_mode, render_class


def import_stage(stage_directory, clear_scene=True, use_authoring_fbx=False):
    from . import placement_session
    placement_session.stop(False)
    # Imports can replace Blender meshes/images while the add-on remains
    # registered. Never carry GPU batches or Image RNA references from the
    # previous stage into the next one.
    from . import viewport
    viewport.reset_stage_caches()
    stage = pathlib.Path(stage_directory).resolve()
    source = stage / "bg.fbx"
    compiled = stage / "bg.fbx.bin"
    if not compiled.is_file():
        raise RuntimeError(f"Retail compiled metadata is missing: {compiled}")
    _textures, _materials, nodes, animations = fpan_binary.parse(compiled)
    render_settings = stage_render_settings(stage)
    from .animation_clock import sample_spacing
    sample_spacing({'fpan_bglist_' + key: value for key, value in render_settings.items()})
    if clear_scene:
        clear_scene_data()
    scale_values = render_settings.get("Scale", (1.0, 1.0, 1.0))
    stage_scale = float(scale_values[0]) if scale_values else 1.0
    # The shipped binary defines geometry, hierarchy, and sampled transforms
    # together. Merely finding a developer FBX is not evidence that its bind
    # spaces/node order match the compiled stream. Default to one authoritative
    # representation for every stage; keep the older FBX path explicit for
    # research rather than choosing it implicitly based on directory contents.
    has_authoring_source = bool(
        use_authoring_fbx and source.is_file() and is_ascii_authoring_fbx(source)
    )
    if has_authoring_source:
        bpy.ops.wm.fbx_import(
            filepath=str(source),
            global_scale=stage_scale,
            use_anim=True,
            import_colors="SRGB",
            use_custom_normals=True,
        )
        names = model_names(source)
        material_opacities = source_material_opacities(source)
        if len(names) + 1 != len(nodes):
            # An authoring FBX may contain nodes the retail compiler omitted.
            # Until a deterministic node join is proven, mixing its hierarchy
            # with positional compiled records would corrupt both materials and
            # animation. Fall back atomically to the compiled source of truth.
            clear_scene_data()
            names = import_compiled_geometry(stage, _textures, _materials, nodes, stage_scale)
            material_opacities = {}
            has_authoring_source = False
    else:
        names = import_compiled_geometry(stage, _textures, _materials, nodes, stage_scale)
        material_opacities = {}
    if len(names) + 1 != len(nodes):
        raise RuntimeError(f"FBX model/node mismatch: {len(names)} names, {len(nodes)} compiled nodes")
    looped = add_loop_preview(source, names, animations) if has_authoring_source else 0
    if has_authoring_source:
        retime_source_actions_for_runtime_preview()
    # Compiled-only stages can contain hundreds of thousands of transform
    # samples. Keep those binary-backed until the user explicitly makes one
    # selected track editable; eagerly expanding every matrix can exhaust
    # Blender before the stage opens.
    supplemented = supplement_compiled_tracks(names, animations) if has_authoring_source else 0

    additive_collection = bpy.data.collections.new("FPAN_Additive_SRC_ALPHA_ONE")
    bpy.context.scene.collection.children.link(additive_collection)
    variants = {}
    for node_index, name in enumerate(names, start=1):
        obj = bpy.data.objects.get(name)
        node = nodes[node_index]
        if obj is None:
            continue
        obj["fpan_node_index"] = node_index
        obj["fpan_node_type"] = node["type"]
        obj["fpan_imported_local_matrix"] = _flat_matrix(obj.matrix_basis.copy())
        obj["fpan_compiled_track_samples"] = len(animations[node_index])
        obj["fpan_lazy_compiled_track"] = bool(
            not has_authoring_source and len(animations[node_index]) > 1
        )
        if node["type"] != 1 or obj.type != "MESH":
            continue
        additive = bool(node.get("blend", 0))
        obj["fpan_blend_mode"] = int(node.get("blend", 0))
        draw_state = render_contract.uni2_draw_state(obj["fpan_blend_mode"])
        obj["fpan_draw_order"] = node_index
        obj["fpan_rgb_blend"] = f"{draw_state.rgb_source},{draw_state.rgb_destination}"
        obj["fpan_alpha_blend"] = f"{draw_state.alpha_source},{draw_state.alpha_destination}"
        obj["fpan_alpha_test"] = f"{draw_state.alpha_test},{draw_state.alpha_reference}"
        obj["fpan_depth_test"] = draw_state.depth_test
        obj["fpan_depth_write"] = draw_state.depth_write
        obj["fpan_cull"] = draw_state.cull
        # Preserve the decoded integer without claiming that it is an opacity.
        obj["fpan_compiled_alpha_flag"] = int(node.get("alpha", 0))
        # Preserve compiler section boundaries and order for the native-contract viewport.
        obj["fpan_section_triangle_counts"] = [
            len(triangles) for _material_index, triangles in node.get("sections", ())
        ]
        obj["fpan_section_material_indices"] = [
            material_index for material_index, _triangles in node.get("sections", ())
        ]
        if additive:
            for collection in tuple(obj.users_collection):
                collection.objects.unlink(obj)
            additive_collection.objects.link(obj)
        for slot in obj.material_slots:
            base = slot.material
            if base is None:
                continue
            source_opacity = material_opacities.get(base.name, 1.0)
            alpha_stats = image_alpha_stats(base)
            alpha_visibility, opacity_scale, alpha_mode, render_class = material_policy(
                int(node.get("blend", 0)),
                int(node.get("alpha", 0)),
                source_opacity,
                alpha_stats,
            )
            key = (base.name, additive, alpha_visibility, opacity_scale, alpha_mode, render_class)
            variant = variants.get(key)
            if variant is None:
                variant = base.copy()
                variant.name = f"{base.name}_{'Additive' if additive else 'Normal'}"
                replace_material(variant, additive, alpha_visibility, opacity_scale, alpha_mode)
                variant["fpan_render_class"] = render_class
                variant["fpan_texture_alpha_min"] = alpha_stats[0]
                variant["fpan_texture_alpha_max"] = alpha_stats[1]
                variant["fpan_texture_alpha_nonopaque_fraction"] = alpha_stats[2]
                variant["fpan_texture_alpha_nearzero_fraction"] = alpha_stats[3]
                variants[key] = variant
            slot.material = variant

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.fps = 60
    scene.sync_mode = "FRAME_DROP"
    scene.frame_start = 1
    authoring_end = max((int(action.frame_range[1]) for action in bpy.data.actions), default=1)
    compiled_end = max((len(track) for track in animations), default=1)
    # A compiled-only stage has no Blender actions until a track is explicitly
    # materialized, but its binary-backed preview still needs a playable range.
    scene.frame_end = authoring_end if has_authoring_source else compiled_end
    scene["fpan_stage_directory"] = str(stage)
    if source.is_file():
        scene["fpan_source_fbx_sha256"] = sha256(source)
    scene["fpan_compiled_sha256"] = sha256(compiled)
    scene["fpan_source_mode"] = "AUTHORING_ASCII_FBX" if has_authoring_source else "COMPILED_ONLY"
    scene["fpan_profile"] = "UNI2"
    scene["fpan_model_count"] = len(names)
    scene["fpan_node_count"] = len(nodes)
    scene["fpan_loop_preview_objects"] = looped
    scene["fpan_compiled_changing_tracks"] = sum(len(track) > 1 for track in animations)
    scene["fpan_animation_binding_status"] = (
        f"ACTIVE: {scene['fpan_compiled_changing_tracks']} compiled tracks"
        if scene["fpan_compiled_changing_tracks"]
        else "STATIC: no multi-sample compiled tracks"
    )
    scene["fpan_supplemented_compiled_tracks"] = supplemented
    scene["fpan_source_authoring_fps"] = 30
    scene["fpan_runtime_preview_fps"] = 60
    scene["fpan_playback_sync"] = "FRAME_DROP"
    # With no retained developer FBX, compiled matrices are the only animation
    # authority. Import directly into that lossless runtime view instead of
    # presenting a valid animated retail stage as an authoring preview.
    preview_mode = "AUTHORING" if has_authoring_source else "COMPILED"
    scene["fpan_animation_preview_mode"] = preview_mode
    if getattr(scene, "fpan_stage", None) is not None:
        scene.fpan_stage.animation_preview_mode = preview_mode
        # Captured retail stages use D3DCULL_CW. Compiled-only input is not
        # evidence that a stage should be two-sided.
        scene.fpan_stage.two_sided_compatibility = False
    scene["fpan_compiled_timeline_end"] = compiled_end
    scene["fpan_authoring_timeline_end"] = compiled_end if not has_authoring_source else authoring_end
    scene["fpan_export_status"] = "BLOCKED: no validated binary writer yet"
    # Scene ID properties outlive object/material deletion. Optional BgList
    # fields must not inherit values from the stage imported immediately before
    # this one (e.g. bloom enable/bias, camera tilt or lighting controls).
    for key in tuple(scene.keys()):
        if key.startswith('fpan_bglist_'):
            del scene[key]
    for key, value in render_settings.items():
        if isinstance(value, tuple):
            scene[f"fpan_bglist_{key}"] = list(value)
        elif isinstance(value, (str, int, float)):
            scene[f"fpan_bglist_{key}"] = value
    from .animation_clock import sample_spacing
    from .stage_components import inventory
    import json
    spacing = sample_spacing(scene)
    scene['fpan_runtime_sample_spacing'] = spacing
    scene['fpan_unrendered_components'] = json.dumps(inventory(stage))
    from . import pat_viewport
    pat_viewport.request(scene)
    if not has_authoring_source:
        scene.frame_end = compiled_end * spacing
        scene['fpan_compiled_timeline_end'] = scene.frame_end
        scene['fpan_authoring_timeline_end'] = scene.frame_end
    register_handlers()
    apply_compiled_runtime_preview(scene)
    return {
        "stage": stage.name,
        "models": len(names),
        "nodes": len(nodes),
        "loops": looped,
        "supplemented": supplemented,
        "animations": len(animations),
    }


def validate_scene(scene):
    errors = []
    warnings = []
    import json
    for component in json.loads(scene.get('fpan_unrendered_components', '[]')):
        warnings.append(
            f"PAT dependency: {component['object_count']} scripted objects "
            f"in {component['reference']} (asset {'present' if component['exists'] else 'missing'}); "
            "check native viewport PAT status for unsupported records"
        )
    if "fpan_stage_directory" not in scene:
        errors.append("Scene was not imported by FPAN Stage Pipeline")
        return errors, warnings
    node_objects = [obj for obj in bpy.data.objects if "fpan_node_index" in obj]
    if len(node_objects) != int(scene.get("fpan_model_count", -1)):
        errors.append(f"Model count changed: expected {scene.get('fpan_model_count')}, found {len(node_objects)}")
    if int(scene.get("fpan_compiled_changing_tracks", 0)) > 0:
        if apply_compiled_runtime_preview not in bpy.app.handlers.frame_change_post:
            errors.append("Compiled animation tracks exist but the runtime preview handler is not registered")
        elif animation_preview_mode(scene) not in {"COMPILED", "AUTHORING"}:
            errors.append("Compiled animation tracks exist but the selected preview mode does not evaluate them")
    looped = [obj for obj in bpy.data.objects if obj.get("fpan_infinite_post_repeat")]
    if len(looped) != int(scene.get("fpan_loop_preview_objects", -1)):
        errors.append(f"Loop metadata count changed: expected {scene.get('fpan_loop_preview_objects')}, found {len(looped)}")
    missing_tracks = [
        obj.name for obj in node_objects
        if int(obj.get("fpan_compiled_track_samples", 1)) > 1
        and obj.animation_data is None
        and not obj.get("fpan_authored_loop_period")
        and not obj.get("fpan_lazy_compiled_track")
    ]
    if missing_tracks:
        warnings.append(f"{len(missing_tracks)} compiled animation tracks still need supplementation: {', '.join(missing_tracks[:8])}")
    return errors, warnings
