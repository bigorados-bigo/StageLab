"""Changing native shear + placement TRS: world, repeat, save/reload, reset."""
import hashlib
import json
import pathlib
import sys
import tempfile
import bpy
from mathutils import Matrix
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import fpan_stage_pipeline
from fpan_stage_pipeline import core,fpan_binary,placement
fpan_stage_pipeline.register()

def node(child=-1):
    return dict(type=1,child=child,sibling=-1,blend=0,alpha=0,matrix=Matrix.Identity(4),
                vertices=[(p,(0,0,1),(1,1,1,1),(0,0)) for p in ((0,0,0),(1,0,0),(0,1,0))],sections=[(0,[(0,1,2)])])

with tempfile.TemporaryDirectory(prefix='fpan-affine-proof-') as folder:
    stage=pathlib.Path(folder)
    tracks=[[],[],[]]
    for index,count in ((1,3),(2,2)):
        for t in range(count):
            shear=Matrix.Identity(4)
            shear[0][1]=.2+.13*t
            shear[1][2]=-.1*t
            tracks[index].append(Matrix.Translation((t*.2,index,t*.1)) @
                                 Matrix.Rotation(t*.23,4,'Z') @ shear @ Matrix.Diagonal((1.2,.8,1.1,1)))
    source=stage/'bg.fbx.bin'
    source.write_bytes(fpan_binary.serialize(([],[('fixture',0,-1,[0]*17)],
                       [dict(type=0,child=1,sibling=-1),node(2),node()],tracks)))
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    core.import_stage(stage,clear_scene=True)
    scene=bpy.context.scene
    scene.frame_set(2)
    controls=[placement.ensure_control(scene.objects[f'FPAN_Node_{i:04d}']) for i in (1,2)]
    for i,control in enumerate(controls):
        control.location.x+=.3
        control.rotation_euler=(.1,.2,.4)
        control.scale=(-1.2,.7,1.1) if i else (1.4,.9,.8)
    deltas=[]
    for control in controls:
        values=control['fpan_placement_rest_matrix']
        rest=Matrix([values[i:i+4] for i in range(0,16,4)])
        deltas.append(control.matrix_basis @ rest.inverted())
    maximum=0
    def verify(frame,offsets):
        global maximum
        scene=bpy.context.scene
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        world=scene.objects['FPAN_Root_0'].matrix_world.copy()
        for i in (1,2):
            world=world @ offsets[i-1] @ tracks[i][(frame-1)%len(tracks[i])]
            error=core._matrix_delta(scene.objects[f'FPAN_Node_{i:04d}'].matrix_world,world)
            maximum=max(maximum,error)
            assert error<1e-5,(frame,i,error)
    for frame in range(1,601):
        verify(frame,deltas)
    blend=stage/'affine.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    for frame in (1,2,3,4,401,600):
        verify(frame,deltas)
    for i in (1,2):
        placement.reset_control(placement.control_for_object(bpy.context.scene.objects[f'FPAN_Node_{i:04d}']))
    for frame in (1,2,3,4,401,600):
        verify(frame,[Matrix.Identity(4)]*2)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
report=dict(result='AFFINE_PRESERVATION_RELOAD_RESET_PASS',max_world_error=maximum,repeated_frames=600,
            independent_periods=[3,2],source_unchanged=True)
(ROOT/'captures/affine-preservation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
