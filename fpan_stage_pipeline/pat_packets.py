"""Blender-independent BgObject draw packets; no stage-specific placement.

Unsupported changing cutouts/3D rotations fail explicitly instead of silently
dropping an effect. The native vertex fixture is the renderer integration gate.
"""
import math
from . import pat_animation, pat_geometry, pat_projection


def packets(document, objects, tick):
    parts = {part['name']: part for part in document['parts'].values()}
    if len(parts) != len(document['parts']):
        raise ValueError('Ambiguous PAT part names')
    result = []
    part_camera = pat_projection.parts_projection()
    for object_index, obj in enumerate(objects):
        commands = obj['commands']
        unknown = {c['tag'] for c in commands} - {'frm','prio','startpos','startdelay'}
        if unknown:
            raise ValueError(f'Unsupported BgObject commands: {sorted(unknown)}')
        pair = pat_animation.frame_pair(commands, tick)
        if pair is None:
            continue
        current, following, fraction = pair
        first, second = parts[current]['groups'], parts[following]['groups']
        start = next((c for c in commands if c['tag']=='startpos'), {})
        origin = tuple(float(start.get(axis,0)) for axis in 'xyz')
        priority = next((c['val'] for c in commands if c['tag']=='prio'), 0)
        # Native author priority is descending; equal priorities retain reverse
        # object insertion order in the recovered BG003 batch.
        for group_id, group in first.items():
            # Maintained Parts::Draw iterates CURRENT groups and interpolates
            # only when a matching next group exists. Incoming groups appear
            # on their own frame; missing matches must not delete the batch.
            other = second.get(group_id,group)
            if group.get('PRID',(-1,)) != other.get('PRID',(-1,)):
                raise ValueError('Changing PAT cutout requires native verification')
            cutout_id = group.get('PRID',(-1,))[0]
            if cutout_id < 0:
                continue
            cutout = document['cutouts'][cutout_id]
            texture_id = cutout.get('PPGR',cutout.get('PPTP',(0,)))[0]
            if texture_id not in document['textures']:
                raise ValueError(f'Unresolved PAT texture {texture_id}')
            mix = lambda tag, default: pat_animation.mix_property(group,other,tag,fraction,default)
            scale = mix('PRZM',(1,1))
            offset = mix('PRXY',(0,0))
            a = group.get('PRA3',(0,0,0,group.get('PRAN',(0,))[0]))
            b = other.get('PRA3',(0,0,0,other.get('PRAN',(0,))[0]))
            if any(a[:3]) or any(b[:3]):
                raise ValueError('PAT 3D rotation requires native verification')
            # Preserve the authored direction at exactly half a turn. Native
            # interpolation wraps only STRICTLY beyond +/-0.5; modulo-based
            # normalization incorrectly reverses every positive180deg segment.
            delta = b[3]-a[3]
            if delta > 0.5:
                delta -= 1
            elif delta < -0.5:
                delta += 1
            angle = (a[3]+delta*fraction)*math.tau
            cosine,sine = math.cos(angle), math.sin(angle)
            flip = group.get('PRRV',(0,))[0]
            if flip != other.get('PRRV',(0,))[0] or flip & ~3:
                raise ValueError('Unsupported changing PAT flip')
            # Native VA0x413940 (diffuse) /0x413BA0 (specular) truncate
            # interpolated channels to integers before packing vertex bytes.
            color = tuple(max(0,min(255,int(v))) for v in mix('PRCL',(255,255,255,255)))
            specular = tuple(max(0,min(255,int(v))) for v in mix('PRSP',(0,0,0,0)))
            # VA0x415183..0x41519C rejects zero diffuse-alpha ordinary
            # stage parts before submission, even when the bound pixel shader
            # does not multiply diffuse alpha into texture alpha.
            if color[3] == 0:
                continue
            filtering = group.get('PRFL',(0,))[0]
            if filtering not in (0,1):
                raise ValueError(f'Unsupported PAT filter flag {filtering}')
            vertices = []
            for quad in reversed(pat_geometry.quads(document,cutout_id)):
                output = []
                for position,uv in quad:
                    x = position[0]*scale[0]*(-1 if flip&1 else 1)
                    y = position[1]*scale[1]*(-1 if flip&2 else 1)
                    local = (x*cosine-y*sine+offset[0], x*sine+y*cosine+offset[1],position[2],1)
                    transformed = tuple(sum(local[k]*part_camera[k*4+column] for k in range(4))
                                        for column in range(4))
                    output.append((tuple(transformed[k]+origin[k]*transformed[3] for k in range(3))
                                   +(transformed[3],),uv))
                vertices.extend(output)
            result.append(dict(object_name=obj['name'], group_id=group_id,
                               priority=(priority,object_index,group.get('PRPR',(0,))[0],group_id),
                               texture_id=texture_id, blend=group.get('PRAL',(0,))[0],
                               color=color, specular=specular, filtering=filtering, vertices=vertices))
    return sorted(result,key=lambda item:item['priority'],reverse=True)


def screen_vertices(packet, projection):
    return [(pat_projection.project(position,projection),uv)
            for position,uv in packet['vertices']]
