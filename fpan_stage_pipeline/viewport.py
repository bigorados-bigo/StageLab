import bpy
import gpu
import pathlib
import math
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import fpan_binary, postprocess, pat_viewport


_DRAW_HANDLE = None
_BATCH_CACHE = {}
_TEXTURE_CACHE = {}
_IMAGE_CACHE = {}
_SHADER = None
_COMPILED_CACHE = {}
_DRAW_DIAGNOSTIC = {"serial": 0, "status": "not drawn"}


def _is_fpan_mesh(obj):
    return obj.type == "MESH" and "fpan_node_index" in obj


def _shader():
    global _SHADER
    if _SHADER is not None:
        return _SHADER
    interface = gpu.types.GPUStageInterfaceInfo("fpan_stage_interface")
    interface.smooth("VEC2", "uvInterp")
    interface.smooth("VEC4", "colorInterp")
    interface.smooth("FLOAT", "clipW")
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.push_constant("VEC2", "FogCoord")
    info.push_constant("VEC4", "FogColor")
    info.push_constant("FLOAT", "FogEnabled")
    info.push_constant("FLOAT", "TextureIsSRGB")
    info.sampler(0, "FLOAT_2D", "image")
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC2", "texCoord")
    info.vertex_in(2, "VEC4", "color")
    info.vertex_out(interface)
    info.fragment_out(0, "VEC4", "FragColor")
    info.vertex_source(
        "void main() { uvInterp = texCoord; colorInterp = color; "
        "gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0); clipW = gl_Position.w; }"
    )
    # Captured native contract: ALPHATEST GREATER, reference 0.
    info.fragment_source(
        "void main() { vec4 texel = texture(image, uvInterp); "
        "vec3 encoded = mix(texel.rgb*12.92,1.055*pow(max(texel.rgb,vec3(0)),vec3(1.0/2.4))-0.055,greaterThan(texel.rgb,vec3(0.0031308))); "
        "texel.rgb=mix(texel.rgb,encoded,TextureIsSRGB); "
        "vec4 value = texel * colorInterp; "
        "if (value.a <= 0.0) discard; float f = clipW * FogCoord.y + FogCoord.x; "
        "vec3 rgb = mix(FogColor.rgb, value.rgb, f); "
        "FragColor = vec4(mix(value.rgb, rgb, FogEnabled), value.a); }"
    )
    _SHADER = gpu.shader.create_from_info(info)
    return _SHADER


def _material_image(material):
    if material is None or not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
            return node.image
    return None


def _compiled(scene):
    source = pathlib.Path(scene.get("fpan_stage_directory", "")) / "bg.fbx.bin"
    if not source.is_file():
        return None
    key = (str(source), source.stat().st_mtime_ns, source.stat().st_size)
    cached = _COMPILED_CACHE.get(key)
    if cached is None:
        cached = fpan_binary.parse(source)
        _COMPILED_CACHE.clear()
        _COMPILED_CACHE[key] = cached
    return cached


def _section_batches(obj, shader, node, compiled_only=False):
    mesh = obj.data
    # Normalize evaluated/original mesh identity on both sides of the cache
    # contract; depsgraph updates can identify either Mesh or owning Object.
    key = (getattr(mesh, 'original', mesh).as_pointer(), len(mesh.vertices), len(mesh.loops), len(mesh.polygons), id(shader), compiled_only)
    cached = _BATCH_CACHE.get(key)
    if cached is not None:
        return cached
    sections = node.get("sections", ())
    if compiled_only:
        vertices = node.get("vertices", ())
        # Compiled imports retain vertex indices and local coordinates exactly.
        # Read authored positions from Blender, while retaining native section
        # order/UV/color. No guessed remap for topology edits or authoring FBX.
        expected = [(tuple(t), material) for material, triangles in sections for t in triangles]
        if (len(mesh.vertices) != len(vertices)
                or [(tuple(p.vertices), p.material_index) for p in mesh.polygons] != expected):
            return None
        local_positions = [tuple(vertex.co) for vertex in mesh.vertices]
        result = []
        for material_index, triangles in sections:
            positions, texcoords, colors = [], [], []
            for triangle in triangles:
                if len(triangle) != 3 or any(index < 0 or index >= len(vertices) for index in triangle):
                    return None
                for index in triangle:
                    vertex = vertices[index]
                    positions.append(local_positions[index])
                    colors.append(tuple(vertex[2]))
                    texcoords.append(tuple(vertex[3]))
            result.append((material_index, batch_for_shader(
                shader, "TRIS", {"pos": positions, "texCoord": texcoords, "color": colors}
            )))
        _BATCH_CACHE[key] = result
        return result
    # Compiled vertices can be baked in a different local space from the FBX
    # mesh. Never combine them with Blender's imported hierarchy transform.
    # One-section nodes can safely use imported geometry plus FPAN draw state.
    # Multi-section remapping is not yet proven and therefore fails closed.
    if len(sections) != 1:
        return None
    material_index, compiled_triangles = sections[0]
    mesh.calc_loop_triangles()
    if len(mesh.loop_triangles) != len(compiled_triangles):
        return None
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return None
    color_layer = mesh.color_attributes.get("Color") or mesh.color_attributes.active_color
    positions, texcoords, colors = [], [], []
    for triangle in mesh.loop_triangles:
        for loop_index in triangle.loops:
            loop = mesh.loops[loop_index]
            positions.append(tuple(mesh.vertices[loop.vertex_index].co))
            texcoords.append(tuple(uv_layer.data[loop_index].uv))
            if color_layer is None:
                colors.append((1.0, 1.0, 1.0, 1.0))
            elif color_layer.domain == "CORNER":
                colors.append(tuple(color_layer.data[loop_index].color))
            elif color_layer.domain == "POINT":
                colors.append(tuple(color_layer.data[loop.vertex_index].color))
            else:
                colors.append((1.0, 1.0, 1.0, 1.0))
    batch = batch_for_shader(
        shader, "TRIS", {"pos": positions, "texCoord": texcoords, "color": colors}
    )
    result = [(material_index, batch)]
    _BATCH_CACHE[key] = result
    return result


def _image_for_texture(texture_name):
    wanted = pathlib.Path(texture_name).name.casefold()
    cached = _IMAGE_CACHE.get(wanted)
    if cached is not None:
        try:
            if cached.name in bpy.data.images and bpy.data.images.get(cached.name) == cached:
                return cached
        except ReferenceError:
            pass
        _IMAGE_CACHE.pop(wanted, None)
    for image in bpy.data.images:
        candidates = {pathlib.Path(image.name).name.casefold()}
        if image.get('fpan_texture_reference'):
            candidates.add(pathlib.Path(image['fpan_texture_reference']).name.casefold())
        if image.filepath:
            candidates.add(pathlib.Path(bpy.path.abspath(image.filepath)).name.casefold())
        if wanted in candidates:
            _IMAGE_CACHE[wanted] = image
            return image
    return None


def _texture(image):
    key = image.as_pointer()
    texture = _TEXTURE_CACHE.get(key)
    if texture is None:
        texture = gpu.texture.from_image(image)
        _TEXTURE_CACHE[key] = texture
    return texture


def reset_stage_caches():
    """Discard every cache whose entries belong to the previously loaded stage."""
    _BATCH_CACHE.clear()
    _TEXTURE_CACHE.clear()
    _IMAGE_CACHE.clear()
    _COMPILED_CACHE.clear()
    pat_viewport.reset()


def _native_gameplay_contract(scene):
    """Rebuild the retail D3D9 stage transform from general BgList fields.

    FbxExp matrices are authored in the engine's stage space.  Compiled-only
    imports add a 90-degree Blender inspection root; remove that presentation
    transform, then apply the retail aspect, stage, camera, and projection
    matrices observed in native captures.
    """
    root = next((candidate for candidate in scene.objects if candidate.get("fpan_node_index") == 0), None)
    if root is None:
        root = bpy.data.objects.get("FPAN_Root_0")
    if root is None:
        return None

    scale_values = scene.get("fpan_bglist_Scale", (1.0, 1.0, 1.0))
    position = scene.get("fpan_bglist_Position", (0.0, 0.0, 0.0))
    stage_scale = Matrix.Diagonal((*tuple(float(v) for v in scale_values[:3]), 1.0))
    stage_position = Matrix.Translation(tuple(float(v) for v in position[:3]))

    rotation_x = math.radians(float(scene.get("fpan_bglist_ViewRotationX", 0.0)))
    # Native D3D9 captures use a fixed 1280x720 stage target. The reciprocal
    # 16:9 aspect is part of the stage transform and must not be recomputed from
    # Blender's sidebar-reduced region; doing so changes the apparent camera
    # position/zoom as panels open and close.
    engine_axis = Matrix.Rotation(rotation_x, 4, "X") @ Matrix.Diagonal(
        (9.0 / 16.0, 1.0, -1.0, 1.0)
    )

    fov = math.radians(float(scene.get("fpan_bglist_FOV", 45.0)))
    cotangent = 1.0 / math.tan(fov * 0.5)
    projection_cotangent = cotangent * float(scene.fpan_stage.gameplay_camera_zoom)
    vanishing = float(scene.get("fpan_bglist_VanishingPoint", 0.0))
    near, far = 0.2, 1000.0
    q = far / (far - near)
    projection = Matrix((
        (projection_cotangent, 0.0, 0.0, 0.0),
        (0.0, projection_cotangent, -vanishing, 0.0),
        (0.0, 0.0, q, -near * q),
        (0.0, 0.0, 1.0, 0.0),
    ))
    settings = scene.fpan_stage
    # Native captures apply this authoring offset in camera-translation space:
    # positive BgList ViewTranslationY subtracts from view Y. For example, a
    # value of 0.2 yields -0.97778, not -0.57778.
    view_y = (-7.0 / 9.0) - float(scene.get("fpan_bglist_ViewTranslationY", 0.0))
    view = Matrix.Translation((
        float(settings.gameplay_camera_x),
        view_y + float(settings.gameplay_camera_y),
        cotangent,
    ))
    d3d_to_gpu_clip = Matrix((
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 2.0, -1.0),
        (0.0, 0.0, 0.0, 1.0),
    ))
    # Native world matrices retain BgList.Position verbatim; it is not scaled,
    # aspect-compressed, axis-flipped, or view-rotated. The former
    # engine_axis @ stage_position order changed (-0.4, 0, 2) into
    # (-0.225, 0, -2) on BG004. Captured anchor matrices instead validate the
    # general affine order Position @ Axis @ Scale.
    prefix = d3d_to_gpu_clip @ projection @ view @ stage_position @ engine_axis @ stage_scale
    return prefix, root.matrix_world.inverted_safe()


def _native_gameplay_mvp(scene, obj, contract=None):
    contract = contract or _native_gameplay_contract(scene)
    if contract is None:
        return None
    prefix, root_inverse = contract
    return prefix @ root_inverse @ obj.matrix_world


def _native_fog(scene, gameplay_camera):
    if not gameplay_camera or not bool(scene.get("fpan_bglist_IsFog", 0.0)):
        return (1.0, 0.0), (0.0, 0.0, 0.0, 0.0), 0.0
    start = float(scene.get("fpan_bglist_FogStart", 0.0))
    end = float(scene.get("fpan_bglist_FogEnd", 1.0))
    span = end - start
    if abs(span) < 1e-8:
        return (1.0, 0.0), (0.0, 0.0, 0.0, 0.0), 0.0
    fog_coord = (end / span, -1.0 / span)
    color = tuple(scene.get("fpan_bglist_FogColor", (0.0, 0.0, 0.0, 0.0)))
    return fog_coord, color, 1.0


def _additive_compatibility_policy(camera_mode, additive, fog_compatibility, free_depth_compatibility):
    """Return the two independent additive-card preview decisions."""
    native_look = camera_mode in {"FREE", "LOCKED"}
    suppress_fog = bool(additive and native_look and fog_compatibility)
    suppress_depth_write = bool(
        additive and camera_mode == "FREE" and free_depth_compatibility
    )
    return suppress_fog, suppress_depth_write


def invalidate_updated_geometry(depsgraph):
    """Drop only GPU batches whose Blender mesh geometry changed."""
    updated_meshes = {
        getattr(update.id, 'original', update.id).as_pointer()
        for update in depsgraph.updates
        if isinstance(update.id, bpy.types.Mesh) and update.is_updated_geometry
    }
    # Blender may flag the owning Object rather than the Mesh ID on edits.
    updated_meshes.update(
        getattr(update.id, 'original', update.id).data.as_pointer()
        for update in depsgraph.updates
        if isinstance(update.id, bpy.types.Object) and update.is_updated_geometry
        and update.id.type == 'MESH'
    )
    if not updated_meshes:
        return
    for key in tuple(_BATCH_CACHE):
        if key[0] in updated_meshes:
            del _BATCH_CACHE[key]


def draw_render_engine(engine, context, depsgraph):
    """Render stage geometry, then UNI2's background composition passes."""
    viewport = gpu.state.viewport_get()
    destination = gpu.state.active_framebuffer_get()
    width, height = viewport[2:]
    if width <= 0 or height <= 0:
        return
    # D16 is part of the captured gameplay contract, not a suitable inspection
    # depth buffer with Blender's much wider free-camera clipping range.
    depth_format = ('DEPTH_COMPONENT16' if depsgraph.scene.fpan_stage.native_camera_mode == 'LOCKED'
                    else 'DEPTH_COMPONENT32F')
    cached = getattr(engine, '_fpan_stage_target', None) if engine is not None else None
    if cached is not None and (cached[:2] != (width, height) or len(cached) < 6 or cached[5] != depth_format):
        cached = None
    if cached is None:
        color = gpu.types.GPUTexture((width, height), format='RGBA8')
        # Retail UNI2's 1280x720 stage target uses D3DFMT_D16, not the
        # desktop swapchain's D24X8. Quantization is part of LESSEQUAL author
        # ordering at near-coplanar contacts; more precision is not equivalent.
        # BG020: create6579885, bind19227536, draws19228536/19230721.
        depth = gpu.types.GPUTexture((width, height), format=depth_format)
        cached = (width, height,
                  gpu.types.GPUFrameBuffer(color_slots=color, depth_slot=depth),
                  color, depth, depth_format)
        if engine is not None:
            engine._fpan_stage_target = cached
    target = cached[2]
    try:
        with target.bind():
            gpu.state.viewport_set(0, 0, width, height)
            _draw_stage_geometry(engine, context, depsgraph)
        effects = None
        if engine is not None and bool(depsgraph.scene.get('fpan_experimental_pat',depsgraph.scene.fpan_stage.scripted_effects)):
            try:
                effects, status = pat_viewport.draw(depsgraph.scene,engine,width,height,
                                                    _pat_mvp(depsgraph.scene,context.region_data))
                _DRAW_DIAGNOSTIC['pat'] = status
            except Exception as error:
                _DRAW_DIAGNOSTIC['pat'] = f'PAT unsupported: {error}'
        else:
            _DRAW_DIAGNOSTIC['pat'] = 'PAT effects disabled'
        gpu.state.viewport_set(*viewport)
        postprocess.compose(depsgraph.scene, cached[3],
                            destination, viewport, owner=engine, depth=cached[4],
                            linear_output=engine is not None and isinstance(engine, bpy.types.RenderEngine),
                            effects=effects)
    finally:
        gpu.state.viewport_set(*viewport)


def _pat_mvp(scene, region3d):
    """Map PAT screen-authored coordinates to the same camera as stage meshes."""
    root = next((obj for obj in scene.objects if obj.get('fpan_node_index')==0),None)
    if root is None:
        root = bpy.data.objects.get('FPAN_Root_0')
    if root is None:
        raise ValueError('Missing stage inspection root')
    scale = Matrix.Diagonal((*tuple(scene.get('fpan_bglist_Scale',(1,1,1)))[:3],1))
    axis = Matrix.Rotation(math.radians(float(scene.get('fpan_bglist_ViewRotationX',0))),4,'X') @ Matrix.Diagonal((9/16,1,-1,1))
    placement = Matrix.Translation(tuple(scene.get('fpan_bglist_Position',(0,0,0)))[:3]) @ axis @ scale
    normalized = Matrix.Diagonal((1/640,-1/360,1/720,1))
    if scene.fpan_stage.native_camera_mode=='LOCKED':
        contract = _native_gameplay_contract(scene)
        if contract is None:
            raise ValueError('Missing native camera contract')
        return contract[0] @ placement.inverted() @ normalized
    return region3d.window_matrix @ region3d.view_matrix @ root.matrix_world @ placement.inverted() @ normalized


def _draw_stage_geometry(engine, context, depsgraph):
    """Draw FPAN meshes in native author order inside Blender's RenderEngine."""
    global _DRAW_DIAGNOSTIC
    scene = depsgraph.scene
    settings = getattr(scene, "fpan_stage", None)
    region3d = getattr(context, "region_data", None)
    if settings is None or region3d is None:
        _DRAW_DIAGNOSTIC = {"status": "render-engine:no-context"}
        return
    compiled = _compiled(scene)
    if compiled is None:
        _DRAW_DIAGNOSTIC = {"status": "render-engine:no-compiled-data"}
        return
    textures, materials, nodes, _animations = compiled
    shader = _shader()
    compiled_only = scene.get("fpan_source_mode") == "COMPILED_ONLY"
    objects = sorted(
        (obj for obj in scene.objects if _is_fpan_mesh(obj) and obj.visible_get()),
        key=lambda obj: int(obj.get("fpan_draw_order", obj.get("fpan_node_index", 0))),
    )
    # Camera projection is a stage/profile contract, not a source-format
    # contract. Editable-FBX and compiled-only imports must use the same locked
    # retail view; only their geometry/batch source differs.
    gameplay_camera = settings.native_camera_mode == "LOCKED"
    native_fog = (gameplay_camera and settings.locked_camera_fog) or (
        settings.native_camera_mode == "FREE" and settings.free_camera_fog
    )
    gameplay_contract = _native_gameplay_contract(scene) if gameplay_camera else None
    fog_coord, fog_color, fog_enabled = _native_fog(scene, native_fog)
    framebuffer = gpu.state.active_framebuffer_get()
    framebuffer.clear(color=(0.025, 0.025, 0.025, 1.0), depth=1.0)
    drawn = skipped = 0
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(True)
    gpu.state.front_facing_set(False)
    gpu.state.face_culling_set("NONE" if settings.two_sided_compatibility else "BACK")
    try:
        for obj in objects:
            additive = int(obj.get("fpan_blend_mode", 0)) > 0
            if settings.rear_inspection_mode and additive:
                continue
            node_index = int(obj.get("fpan_node_index", -1))
            if not 0 <= node_index < len(nodes):
                skipped += 1
                continue
            sections = _section_batches(obj, shader, nodes[node_index], compiled_only=compiled_only)
            if sections is None:
                skipped += 1
                continue
            gpu.state.blend_set("ADDITIVE" if additive else "ALPHA")
            # Fog and depth require separate compatibility policies. Fogging an
            # opaque-alpha additive rectangle creates a visible color box in
            # either camera. Suppressing additive depth writes, however, changes
            # author-order occlusion and is safe only for arbitrary free-camera
            # inspection; locked gameplay retains the captured depth contract.
            suppress_additive_fog, suppress_additive_depth_write = (
                _additive_compatibility_policy(
                    settings.native_camera_mode,
                    additive,
                    settings.additive_fog_compatibility,
                    settings.free_camera_additive_depth_compatibility,
                )
            )
            gpu.state.depth_mask_set(not suppress_additive_depth_write)
            mvp = _native_gameplay_mvp(scene, obj, gameplay_contract) if gameplay_camera else None
            if mvp is None:
                mvp = region3d.window_matrix @ region3d.view_matrix @ obj.matrix_world
            for material_index, batch in sections:
                if not 0 <= material_index < len(materials):
                    continue
                texture_index = int(materials[material_index][2])
                if not 0 <= texture_index < len(textures):
                    continue
                image = _image_for_texture(textures[texture_index])
                if image is None:
                    continue
                shader.bind()
                shader.uniform_float("ModelViewProjectionMatrix", mvp)
                shader.uniform_float("FogCoord", fog_coord)
                shader.uniform_float("FogColor", fog_color)
                # Native fog is evaluated before SRC_ALPHA/ONE blending. Many
                # DXT1 additive cards store alpha=1 across their otherwise black
                # rectangle, so applying the authored fog equation from an
                # camera can turn that rectangle into a solid fog-coloured
                # contribution. Default native-look compatibility suppresses
                # both this fog box and the matching invisible depth write;
                # disabling it restores the literal captured contract.
                object_fog_enabled = 0.0 if (
                    suppress_additive_fog
                ) else fog_enabled
                shader.uniform_float("FogEnabled", object_fog_enabled)
                shader.uniform_float("TextureIsSRGB", 1.0 if image.colorspace_settings.name == 'sRGB' else 0.0)
                shader.uniform_sampler("image", _texture(image))
                batch.draw(shader)
                drawn += 1
    finally:
        gpu.state.face_culling_set("NONE")
        gpu.state.front_facing_set(False)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
    _DRAW_DIAGNOSTIC = {
        "serial": int(_DRAW_DIAGNOSTIC.get("serial", 0)) + 1,
        "status": f"render-engine:drawn={drawn}:skipped={skipped}",
        "show_gizmo": getattr(context.space_data, "show_gizmo", None),
        "show_overlays": getattr(getattr(context.space_data, "overlay", None), "show_overlays", None),
        "source_mode": scene.get("fpan_source_mode", ""),
        "camera_mode": settings.native_camera_mode,
        "gameplay_camera": gameplay_camera,
        "gameplay_contract": gameplay_contract is not None,
        "additive_fog_compatibility": bool(
            settings.native_camera_mode in {"FREE", "LOCKED"}
            and settings.additive_fog_compatibility
        ),
        "free_additive_depth_compatibility": bool(
            settings.native_camera_mode == "FREE"
            and settings.free_camera_additive_depth_compatibility
        ),
    }


def draw_native_contract():
    global _DRAW_DIAGNOSTIC
    scene = bpy.context.scene
    settings = getattr(scene, "fpan_stage", None)
    area = getattr(bpy.context, "area", None)
    space = getattr(bpy.context, "space_data", None)
    _DRAW_DIAGNOSTIC = {
        "serial": int(_DRAW_DIAGNOSTIC.get("serial", 0)) + 1,
        "status": "entered",
        "area": getattr(area, "type", "none"),
        "shading": getattr(getattr(space, "shading", None), "type", "none"),
        "show_gizmo": getattr(space, "show_gizmo", None),
        "show_overlays": getattr(getattr(space, "overlay", None), "show_overlays", None),
    }
    if settings is None or not settings.exact_additive_viewport:
        _DRAW_DIAGNOSTIC["status"] = "disabled"
        return
    # Suspended in v0.22: the POST_VIEW path disappears with Blender's native
    # overlay/gizmo masters and cannot safely own visibility of the editable
    # meshes.  Keep the implementation available for contract research, but
    # never draw a second/deep-fried scene in normal authoring sessions.
    _DRAW_DIAGNOSTIC["status"] = "suspended:render-engine-required"
    return
    shading = getattr(getattr(space, "shading", None), "type", "SOLID")
    textured = area is not None and area.type == "VIEW_3D" and shading in {"MATERIAL", "RENDERED"}
    sync_scene(scene, textured=textured)
    if not textured:
        _DRAW_DIAGNOSTIC["status"] = "non-textured"
        return
    shader = _shader()
    compiled = _compiled(scene)
    if compiled is None:
        _DRAW_DIAGNOSTIC["status"] = "no-compiled-data"
        return
    textures, materials, nodes, _animations = compiled
    objects = sorted(
        (obj for obj in scene.objects if _is_fpan_mesh(obj)),
        key=lambda obj: int(obj.get("fpan_node_index", 0)),
    )
    camera_mode = settings.native_camera_mode
    gameplay_camera = bool(
        camera_mode == "LOCKED"
        and scene.get("fpan_source_mode") == "COMPILED_ONLY"
    )
    native_fog = gameplay_camera or (camera_mode == "FREE" and settings.free_camera_fog)
    fog_coord, fog_color, fog_enabled = _native_fog(scene, native_fog)
    compiled_only = scene.get("fpan_source_mode") == "COMPILED_ONLY"
    gameplay_contract = _native_gameplay_contract(scene) if gameplay_camera else None
    # D3DCULL_CW discards clockwise faces, so counter-clockwise remains front.
    # Blender's default front-facing convention is counter-clockwise.
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(True)
    gpu.state.front_facing_set(False)
    gpu.state.face_culling_set("NONE" if settings.two_sided_compatibility else "BACK")
    try:
        for obj in objects:
            if settings.rear_inspection_mode and int(obj.get("fpan_blend_mode", 0)) > 0:
                continue
            node = nodes[int(obj["fpan_node_index"])]
            sections = _section_batches(obj, shader, node, compiled_only=compiled_only)
            if sections is None:
                continue
            gpu.state.blend_set(
                # Blender ADDITIVE is SRC_ALPHA,ONE, matching the captured
                # FPAN state. ADDITIVE_PREMULT is ONE,ONE and ignores DDS
                # alpha in RGB, producing saturated cards.
                "ADDITIVE" if int(obj.get("fpan_blend_mode", 0)) > 0 else "ALPHA"
            )
            gpu.matrix.push()
            try:
                mvp = _native_gameplay_mvp(scene, obj, gameplay_contract) if gameplay_camera else None
                if mvp is None:
                    gpu.matrix.multiply_matrix(obj.matrix_world)
                    mvp = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
                for material_index, batch in sections:
                    if material_index >= len(materials):
                        continue
                    texture_index = int(materials[material_index][2])
                    if texture_index >= len(textures):
                        continue
                    image = _image_for_texture(textures[texture_index])
                    if image is None:
                        continue
                    shader.bind()
                    shader.uniform_float("ModelViewProjectionMatrix", mvp)
                    shader.uniform_float("FogCoord", fog_coord)
                    shader.uniform_float("FogColor", fog_color)
                    shader.uniform_float("FogEnabled", fog_enabled)
                    shader.uniform_sampler("image", _texture(image))
                    batch.draw(shader)
            finally:
                gpu.matrix.pop()
    finally:
        gpu.state.face_culling_set("NONE")
        gpu.state.front_facing_set(False)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
    _DRAW_DIAGNOSTIC["status"] = f"drawn:{len(objects)}"


def draw_diagnostic():
    return dict(_DRAW_DIAGNOSTIC)


def sync_scene(scene, textured=None):
    settings = getattr(scene, "fpan_stage", None)
    # See draw_native_contract: the experimental renderer is deliberately
    # suspended, so ordinary Blender meshes remain the visible authority.
    enabled = False
    rear_inspection = bool(settings and settings.rear_inspection_mode)
    if textured is None:
        space = getattr(bpy.context, "space_data", None)
        shading = getattr(getattr(space, "shading", None), "type", "SOLID")
        textured = shading in {"MATERIAL", "RENDERED"}
    changed = False
    # Blender's ordinary Solid/Wireframe views use the View3D clipping range,
    # independently of this add-on's custom shader.  FPAN backdrop cards can
    # sit tens of thousands of Blender units from the playable foreground.
    # Extend only the far plane and preserve the user's near plane so this
    # does not throw away additional depth precision near the stage.
    if settings and settings.extended_inspection_clipping:
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if space.type == "VIEW_3D" and space.clip_end < 100000.0:
                        space.clip_end = 100000.0
                        changed = True
    if settings and settings.native_camera_mode == "FREE":
        fov = math.radians(float(scene.get("fpan_bglist_FOV", 45.0)))
        # View3D uses a 32 mm virtual sensor for its perspective lens control.
        native_lens = 16.0 / math.tan(fov * 0.5)
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if space.type == "VIEW_3D" and abs(space.lens - native_lens) > 1e-5:
                        space.lens = native_lens
                        changed = True
    for obj in scene.objects:
        if _is_fpan_mesh(obj):
            edit_overlay = bool(settings and settings.geometry_edit_mode)
            custom_hidden = enabled and textured and not edit_overlay
            wanted_hidden = custom_hidden or (rear_inspection and int(obj.get("fpan_blend_mode", 0)) > 0)
            if obj.hide_get() != wanted_hidden:
                obj.hide_set(wanted_hidden)
                changed = True
            wanted_display = "WIRE" if edit_overlay else "TEXTURED"
            if obj.display_type != wanted_display:
                obj.display_type = wanted_display
                changed = True
            if obj.show_in_front != edit_overlay:
                obj.show_in_front = edit_overlay
                changed = True
            obj["fpan_native_contract_hidden"] = custom_hidden
    if changed:
        for area in getattr(bpy.context.screen, "areas", ()) if bpy.context.screen else ():
            if area.type == "VIEW_3D":
                area.tag_redraw()


def update_exact_additive(self, context):
    sync_scene(context.scene)


@persistent
def _load_post(_unused):
    # File loading invalidates prior Image/Mesh datablocks even when the same
    # stage path is reopened. Never retain their GPU or PAT preparation cache.
    reset_stage_caches()
    for scene in bpy.data.scenes:
        settings = getattr(scene, "fpan_stage", None)
        if settings is not None:
            # Preserve only the proper RenderEngine state. Old files that
            # saved the unsafe POST_VIEW toggle still fail closed because
            # their render engine is Eevee rather than FPAN_NATIVE.
            settings.exact_additive_viewport = scene.render.engine == "FPAN_NATIVE"
        sync_scene(scene)


def register():
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)
    # The old POST_VIEW renderer must not be registered. It ran after Blender's
    # scene pass, ignored the render-engine lifecycle, and caused both incorrect
    # alpha ordering and overlay/gizmo-dependent black or flashing frames.
    # FPANNativeRenderEngine.view_draw is now the sole native-preview owner.


def unregister():
    global _DRAW_HANDLE, _SHADER
    for scene in bpy.data.scenes:
        settings = getattr(scene, "fpan_stage", None)
        if settings is not None:
            settings.exact_additive_viewport = False
        sync_scene(scene)
    # Remove a stale handler left behind by an earlier live add-on reload.
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    _BATCH_CACHE.clear()
    _TEXTURE_CACHE.clear()
    _IMAGE_CACHE.clear()
    _COMPILED_CACHE.clear()
    _SHADER = None
