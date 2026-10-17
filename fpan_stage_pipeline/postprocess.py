"""UNI2 background passes recovered from native D3D9 draw snapshots."""

import math
import gpu
from gpu_extras.batch import batch_for_shader

_SHADERS = {}


def _program(kind):
    if kind in _SHADERS:
        return _SHADERS[kind]
    interface = gpu.types.GPUStageInterfaceInfo('fpan_post_' + kind)
    interface.smooth('VEC2', 'uv')
    info = gpu.types.GPUShaderCreateInfo()
    info.vertex_in(0, 'VEC2', 'pos')
    info.vertex_out(interface)
    info.fragment_out(0, 'VEC4', 'outColor')
    info.sampler(0, 'FLOAT_2D', 'source')
    info.vertex_source('void main(){uv=pos*0.5+0.5;gl_Position=vec4(pos,0,1);}')
    if kind == 'bloom':
        info.push_constant('VEC4', 'params')
        info.push_constant('VEC3', 'bias')
        info.push_constant('INT', 'halfKernel')
        # Captured ps_3_0 loop uses |y-x| < radius, not a Gaussian weight.
        # Offsets are [-halfKernel, halfKernel), and all accepted taps have
        # equal weight. Exponentiation occurs BEFORE averaging, including alpha.
        info.fragment_source('''void main(){
            vec4 sum=vec4(0); float count=0;
            for(int y=-halfKernel;y<halfKernel;y++){
              for(int x=-halfKernel;x<halfKernel;x++){
                if(float(abs(y-x))>=params.w) continue;
                vec4 v=texture(source,clamp(uv+vec2(x,y)*params.z,vec2(0),vec2(1)));
                v=pow(max(v*params.x,vec4(0)),vec4(params.y));
                v.rgb*=bias; sum+=v; count+=1;
              }
            }
            outColor=sum/max(count,1.0);
        }''')
    else:
        info.sampler(1, 'FLOAT_2D', 'bloom')
        info.sampler(2, 'FLOAT_2D', 'sourceDepth')
        info.push_constant('FLOAT', 'hasDepth')
        info.push_constant('FLOAT', 'linearOutput')
        info.push_constant('FLOAT', 'finalLift')
        info.sampler(3, 'FLOAT_2D', 'effects')
        info.push_constant('FLOAT', 'hasEffects')
        info.depth_write('ANY')
        info.push_constant('FLOAT', 'bloomAlpha')
        # Native composition: SRC_ALPHA/ONE bloom, then final background shader
        # adds 0.1. Background textures are UNORM and sRGB writes are disabled.
        info.fragment_source('''void main(){
            vec4 base=texture(source,uv); vec4 glow=texture(bloom,uv);
            vec3 rgb=clamp(base.rgb+glow.rgb*glow.a*bloomAlpha,0.0,1.0);
            rgb=clamp(rgb+vec3(finalLift),0.0,1.0);
            if(hasEffects>0.5) rgb=clamp(rgb+texture(effects,uv).rgb,0.0,1.0);
            vec3 linear=mix(rgb/12.92,pow((rgb+0.055)/1.055,vec3(2.4)),greaterThan(rgb,vec3(0.04045)));
            outColor=vec4(mix(rgb,linear,linearOutput),1.0);
            gl_FragDepth=hasDepth>0.5?texture(sourceDepth,uv).r:1.0;
        }''')
    shader=gpu.shader.create_from_info(info)
    batch=batch_for_shader(shader,'TRI_STRIP',{'pos':[(-1,-1),(1,-1),(-1,1),(1,1)]})
    _SHADERS[kind]=(shader,batch)
    return shader,batch


def compose(scene, source, destination, viewport, owner=None, depth=None, linear_output=False, effects=None):
    """Run the captured stage bloom and final background lift in code space."""
    apply_post=bool(getattr(getattr(scene,'fpan_stage',None),'stage_postprocess',True))
    enabled=apply_post and bool(scene.get('fpan_bglist_BGBloomEnable',0))
    size=max(1,min(2048,int(scene.get('fpan_bglist_BGBloomTextureSize',256))))
    radius=max(0.0,float(scene.get('fpan_bglist_BGBloomBlurRadius',0.0)))
    # Native shader family supplies 2,4,...,22 tap widths according to radius.
    half=max(1,min(11,math.ceil(radius)))
    cached=getattr(owner,'_fpan_bloom_target',None) if owner is not None else None
    if cached is not None and cached[:1] != (size,):
        cached[1].free()
        cached=None
    if cached is None:
        cached=(size,gpu.types.GPUOffScreen(size,size,format='RGBA8'))
        if owner is not None:
            owner._fpan_bloom_target=cached
    target=cached[1]
    old_viewport=viewport
    try:
        gpu.state.face_culling_set('NONE')
        gpu.state.scissor_test_set(False)
        with target.bind():
            gpu.state.viewport_set(0,0,size,size)
            gpu.state.active_framebuffer_get().clear(color=(0,0,0,0))
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
            gpu.state.depth_mask_set(False)
            if enabled and radius>0:
                shader,batch=_program('bloom')
                shader.bind()
                shader.uniform_sampler('source',source)
                shader.uniform_float('params',(
                    float(scene.get('fpan_bglist_BGBloomBlightness',1)),
                    float(scene.get('fpan_bglist_BGBloomPower',1)),1.0/size,radius))
                shader.uniform_float('bias',tuple(float(scene.get('fpan_bglist_BGBloomBiass'+c,1)) for c in 'RGB'))
                shader.uniform_int('halfKernel',half)
                batch.draw(shader)
        with destination.bind():
            gpu.state.viewport_set(*old_viewport)
            gpu.state.depth_test_set('ALWAYS')
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)
            shader,batch=_program('composite')
            shader.bind()
            shader.uniform_sampler('source',source)
            shader.uniform_sampler('bloom',target.texture_color)
            shader.uniform_sampler('sourceDepth',depth if depth is not None else source)
            shader.uniform_sampler('effects',effects if effects is not None else source)
            shader.uniform_float('hasEffects',1.0 if effects is not None else 0.0)
            shader.uniform_float('hasDepth',1.0 if depth is not None else 0.0)
            shader.uniform_float('linearOutput',1.0 if linear_output else 0.0)
            shader.uniform_float('finalLift',0.1 if apply_post else 0.0)
            shader.uniform_float('bloomAlpha',float(scene.get('fpan_bglist_BGBloomAlpha',0)) if enabled else 0.0)
            batch.draw(shader)
    finally:
        gpu.state.viewport_set(*old_viewport)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set('NONE')
        if owner is None:
            target.free()
