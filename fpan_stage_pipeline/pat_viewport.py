"""Isolated additive BgObject pass, after background composition in code space."""
import pathlib
import tempfile
import time
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from . import pat_binary, pat_packets, stage_components

_CACHE = {}
_SHADER = None
_PENDING = set()
_TRACE = []


def _trace(event, **values):
    _TRACE.append(dict(event=event,**values))
    del _TRACE[:-32]


def diagnostic():
    return list(_TRACE)


def reset():
    for entry in _CACHE.values():
        if not entry:
            continue
        for image in entry.get('images',{}).values():
            try:
                if image.users == 0:
                    bpy.data.images.remove(image)
            except ReferenceError:
                pass
    _CACHE.clear()
    _PENDING.clear()


def _program():
    global _SHADER
    if _SHADER is not None:
        return _SHADER
    interface = gpu.types.GPUStageInterfaceInfo('fpan_pat_interface')
    interface.smooth('VEC2','uv')
    interface.smooth('VEC4','diffuse')
    interface.smooth('VEC3','specular')
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant('MAT4','mvp')
    info.push_constant('INT','linearFilter')
    info.sampler(0,'FLOAT_2D','source')
    info.vertex_in(0,'VEC4','pos')
    info.vertex_in(1,'VEC2','texCoord')
    info.vertex_in(2,'VEC4','color')
    info.vertex_in(3,'VEC3','addColor')
    info.vertex_out(interface)
    info.fragment_out(0,'VEC4','outColor')
    # Blender's decoded DDS image is vertically flipped relative to the raw
    # D3D9 atlas. Verified by GPU readback vs replayed native texture bytes.
    info.vertex_source('void main(){uv=vec2(texCoord.x,1.0-texCoord.y);diffuse=color;specular=addColor;'
                       'gl_Position=mvp*pos;gl_Position.z=0.0;}')
    # Replayed fixed-function state (not the stale shader name left in the
    # textual trace across StateBlock.Apply): MODULATE texture/diffuse for RGB
    # and alpha; enabled specular adds RGB. No background +0.1 lift here.
    info.fragment_source('vec4 fetchClamped(ivec2 p){ivec2 size=textureSize(source,0);'
                         'return texelFetch(source,clamp(p,ivec2(0),size-ivec2(1)),0);}'
                         'void main(){vec2 xy=uv*vec2(textureSize(source,0));'
                         'vec4 t=fetchClamped(ivec2(floor(xy)));'
                         'if(linearFilter!=0){xy-=vec2(0.5);ivec2 p=ivec2(floor(xy));vec2 f=fract(xy);'
                         't=mix(mix(fetchClamped(p),fetchClamped(p+ivec2(1,0)),f.x),'
                         'mix(fetchClamped(p+ivec2(0,1)),fetchClamped(p+ivec2(1,1)),f.x),f.y);}'
                         'outColor=vec4(clamp(t.rgb*diffuse.rgb+specular,0.0,1.0),t.a*diffuse.a);}')
    _SHADER = gpu.shader.create_from_info(info)
    return _SHADER


def prepare(stage):
    """Prepare image datablocks ONLY from an operator/load timer, never draw."""
    stage=pathlib.Path(stage)
    key=str(stage)
    if key in _CACHE:
        return _CACHE[key]
    _trace('prepare_begin',stage=key)
    dependencies = stage_components.inventory(stage)
    if not dependencies:
        _CACHE[key]=None
        return None
    objects = stage_components.script_objects(stage)
    if not objects:
        # An empty BgObject table cannot submit parts. Preserve its dependency
        # inventory, but do not load a stale/absent authoring PAT just to draw
        # zero objects (retail BG012 is an example, not a special-case key).
        _CACHE[key]=None
        _trace('prepare_inactive',stage=key,references=len(dependencies))
        return None
    if len(dependencies)!=1:
        raise ValueError('Multiple PAT dependencies require native verification')
    path = stage/pathlib.Path(dependencies[0]['reference'].replace('\\','/')).name
    content=dict(document=pat_binary.parse(path),objects=objects,
                 images={},textures={},frame=None,batches=[],packet_builds=0)
    try:
        for texture_id,texture in content['document']['textures'].items():
            with tempfile.TemporaryDirectory(prefix='fpan-pat-') as folder:
                source=pathlib.Path(folder)/'embedded.dds'
                source.write_bytes(texture['dds'])
                image=bpy.data.images.load(str(source),check_existing=False)
                content['images'][texture_id]=image
                image.colorspace_settings.name='Non-Color'
                image.pack()
        _CACHE[key]=content
        _trace('prepare_ready',stage=key,images=len(content['images']))
        return content
    except Exception:
        for image in content['images'].values():
            if image.users==0:
                bpy.data.images.remove(image)
        raise


def _prepare_pending():
    pending=tuple(_PENDING)
    _PENDING.clear()
    for key in pending:
        try:
            prepare(key)
        except Exception as error:
            _CACHE[key]={'error':str(error)}
            _trace('prepare_error',stage=key,error=str(error))
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':
                area.tag_redraw()
    return None


def request(scene):
    key=str(pathlib.Path(scene.get('fpan_stage_directory','')))
    if key not in _CACHE and key not in _PENDING:
        _PENDING.add(key)
        if not bpy.app.timers.is_registered(_prepare_pending):
            bpy.app.timers.register(_prepare_pending,first_interval=0.01)
    return key


def draw(scene, owner, width, height, mvp):
    """Return code-space additive contribution texture; never own mesh state."""
    started=time.perf_counter()
    key=request(scene)
    if key not in _CACHE:
        return None,'PAT preparing textures'
    content = _CACHE[key]
    if content is None:
        return None, 'no scripted PAT'
    if 'error' in content:
        raise ValueError(content['error'])
    shader = _program()
    frame=max(0,scene.frame_current-1)
    if content['frame']!=frame:
        packets=pat_packets.packets(content['document'],content['objects'],frame)
        if any(packet['blend']!=1 for packet in packets):
            raise ValueError('Non-additive PAT composition requires native verification')
        groups=[]
        for packet in packets:
            key=(packet['texture_id'],packet['filtering'],packet['blend'])
            if not groups or groups[-1][0]!=key:
                groups.append((key,{'pos':[],'texCoord':[],'color':[],'addColor':[]}))
            attributes=groups[-1][1]
            vertices=packet['vertices']
            order=[index+corner for index in range(0,len(vertices),4) for corner in (0,1,2,2,1,3)]
            attributes['pos'].extend(vertices[i][0] for i in order)
            attributes['texCoord'].extend(vertices[i][1] for i in order)
            color=tuple(v/255 for v in reversed(packet['color'][:3]))+(packet['color'][3]/255,)
            specular=tuple(v/255 for v in reversed(packet['specular'][:3]))
            attributes['color'].extend([color]*len(order))
            attributes['addColor'].extend([specular]*len(order))
        content['batches']=[(key,batch_for_shader(shader,'TRIS',attributes)) for key,attributes in groups]
        content['groups']=len(packets)
        content['frame']=frame
        content['packet_builds']+=1
    cached = getattr(owner,'_fpan_pat_target',None)
    if cached is None or cached[:2]!=(width,height):
        texture = gpu.types.GPUTexture((width,height),format='RGBA16F')
        cached = (width,height,gpu.types.GPUFrameBuffer(color_slots=texture),texture)
        owner._fpan_pat_target = cached
    with cached[2].bind():
        gpu.state.viewport_set(0,0,width,height)
        cached[2].clear(color=(0,0,0,0))
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)
        gpu.state.face_culling_set('NONE')
        gpu.state.blend_set('ADDITIVE')
        try:
            shader.bind()
            shader.uniform_float('mvp',mvp)
            for (texture_id,filtering,blend),batch in content['batches']:
                texture=content['textures'].get(texture_id)
                if texture is None:
                    texture=gpu.texture.from_image(content['images'][texture_id])
                    content['textures'][texture_id]=texture
                shader.uniform_int('linearFilter',filtering)
                shader.uniform_sampler('source',texture)
                batch.draw(shader)
        finally:
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)
    content['last_draw_ms']=(time.perf_counter()-started)*1000
    return cached[3],f"PAT: {content['groups']} groups / {len(content['batches'])} draws"
