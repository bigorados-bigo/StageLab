"""Local PAT geometry, separate from stage-script placement/projection."""
import math


def quads(document, cutout_id):
    cut = document['cutouts'][cutout_id]
    texture_id = cut.get('PPGR',cut.get('PPTP',(0,)))[0]
    texture = document['textures'][texture_id]
    shape_id = cut.get('PPVT',cut.get('PPPP',(0,)))[0]
    shape = document['shapes'][shape_id]
    uv = cut.get('PPUV',(0,0,0,0))
    width,height = cut.get('PPWH',cut.get('PPSS',(0,0)))
    origin = cut.get('PPXY',cut.get('PPCC',(0,0)))
    if shape[0] in (1,2):
        count = 1
    elif shape[0] == 4:
        count = shape[5]
        if not 1 <= count <= 65536:
            raise ValueError('Invalid PAT arc subdivision count')
    else:
        raise ValueError(f'Unsupported PAT geometry type {shape[0]}')
    result=[]
    for segment in range(count):
        vertices=[]
        for radial,along in ((0,0),(1,0),(0,1),(1,1)):
            phase=(segment+along)/count
            if shape[0] == 4:
                radius=shape[3]-(1-radial)*shape[4]
                if not (segment+along == count and shape[6] == 10000):
                    radius-=shape[8]*phase
                angle=math.tau*shape[6]/10000*phase
                position=(radius*math.sin(angle),-radius*math.cos(angle),-shape[7]*phase)
                vertical=phase
            else:
                position=(-origin[0]+width*radial,-origin[1]+height*along,0)
                vertical=along
            texcoord=((uv[0]+uv[2]*radial)/texture['width'],
                      (uv[1]+uv[3]*vertical)/texture['height'])
            # Native plane path VA0x4C068A/+0x6BB adds these globals only
            # to the starting U/V edges. Arc geometry uses a separate path.
            if shape[0] in (1,2):
                texcoord=(texcoord[0]+(0.0002 if radial==0 else 0),
                          texcoord[1]+(0.000195 if along==0 else 0))
            vertices.append((position,texcoord))
        result.append(vertices)
    return result
