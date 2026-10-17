"""Disposable affine/hierarchy/loop/persistence contract for placement controls."""
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


def close(a,b):
    error=max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))
    assert error<2e-5,error


def mesh_node(child=-1):
    return dict(type=1,child=child,sibling=-1,blend=0,alpha=0,matrix=Matrix.Identity(4),
                vertices=[(p,(0,0,1),(1,1,1,1),(0,0)) for p in ((0,0,0),(1,0,0),(0,1,0))],
                sections=[(0,[(0,1,2)])])


fpan_stage_pipeline.register()
with tempfile.TemporaryDirectory(prefix='fpan-placement-test-') as folder:
    stage=pathlib.Path(folder)
    shear=Matrix.Identity(4)
    shear[0][1]=0.17
    tracks=[[],[Matrix.Translation((i,0,0))@Matrix.Rotation(i*0.15,4,'Z') for i in range(3)],
            [Matrix.Translation((0,i*0.2,1))@Matrix.Diagonal((1+i*0.1,1,1,1)) for i in range(2)]]
    document=([],[('fixture',0,-1,[0]*17)],[dict(type=0,child=1,sibling=-1),mesh_node(2),mesh_node()],tracks)
    source=stage/'bg.fbx.bin'
    source.write_bytes(fpan_binary.serialize(document))
    original_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    core.import_compiled_geometry(stage,*document[:3])
    scene=bpy.context.scene
    scene['fpan_stage_directory']=str(stage)
    scene['fpan_source_mode']='COMPILED_ONLY'
    scene.fpan_stage.animation_preview_mode='COMPILED'
    parent=bpy.data.objects['FPAN_Node_0001']
    child=bpy.data.objects['FPAN_Node_0002']
    root=bpy.data.objects['FPAN_Root_0']
    for index,obj in ((1,parent),(2,child)):
        obj['fpan_node_index']=index
        obj['fpan_imported_local_matrix']=core._flat_matrix(Matrix.Identity(4))
        obj['fpan_lazy_compiled_track']=True
    parent.matrix_parent_inverse=Matrix.Translation((0.1,0.2,0.3))@shear
    child.matrix_parent_inverse=Matrix.Translation((0.4,0.3,0.2))
    parent_inverse=parent.matrix_parent_inverse.copy()
    child_inverse=child.matrix_parent_inverse.copy()
    scene.frame_set(1)
    bpy.context.view_layer.update()
    initial=child.matrix_world.copy()
    child_control=placement.ensure_control(child)
    parent_control=placement.ensure_control(parent)
    bpy.context.view_layer.update()
    close(child.matrix_world,initial)
    assert placement.ensure_control(child)==child_control
    assert placement.target_for_object(child_control)==child
    assert placement.target_for_object(root) is None
    parent_offset=Matrix.Translation((1,-2,0.5))@Matrix.Rotation(0.2,4,'Y')
    child_offset=Matrix.Translation((0.5,0.2,-0.1))@Matrix.Diagonal((1.2,0.8,1,1))
    parent_control.matrix_basis=parent_offset@parent_control.matrix_basis
    child_control.matrix_basis=child_offset@child_control.matrix_basis
    for mode in ('COMPILED','AUTHORING'):
        scene.fpan_stage.animation_preview_mode=mode
        for frame in (1,2,3,4,5,6,1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            expected=(root.matrix_world@parent_inverse@parent_offset@tracks[1][(frame-1)%3]
                      @child_inverse@child_offset@tracks[2][(frame-1)%2])
            close(child.matrix_world,expected)
            close(child.matrix_basis,tracks[2][(frame-1)%2])
    # Materializing native keys must not bake, erase, or double the parent offset.
    bpy.context.view_layer.objects.active=child_control
    assert bpy.ops.fpan.materialize_selected_track()=={'FINISHED'}
    assert parent.animation_data is not None and child.animation_data is not None
    for frame in (1,2,3,4,5,6):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        close(child.matrix_world,root.matrix_world@parent_inverse@parent_offset@tracks[1][(frame-1)%3]
              @child_inverse@child_offset@tracks[2][(frame-1)%2])
    saved=stage/'placement.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    scene=bpy.context.scene
    child=bpy.data.objects['FPAN_Node_0002']
    parent=bpy.data.objects['FPAN_Node_0001']
    root=bpy.data.objects['FPAN_Root_0']
    assert placement.control_for_object(child) is not None
    scene.frame_set(5)
    bpy.context.view_layer.update()
    close(child.matrix_world,root.matrix_world@parent_inverse@parent_offset@tracks[1][1]
          @child_inverse@child_offset@tracks[2][0])
    # Reset the selected child control only, retaining its parent's offset.
    bpy.context.view_layer.objects.active=placement.control_for_object(child)
    assert bpy.ops.fpan.reset_placement()=={'FINISHED'}
    scene.frame_set(2)
    bpy.context.view_layer.update()
    close(child.matrix_world,root.matrix_world@parent_inverse@parent_offset@tracks[1][1]
          @child_inverse@tracks[2][1])
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original_hash
    result=dict(result='PLACEMENT_AFFINE_LOOP_RELOAD_RESET_PASS',source_sha256=original_hash,
                preview_modes=['COMPILED','AUTHORING'],independent_cycles=[3,2],source_unchanged=True,
                materialized_tracks_preserved=True)
    (ROOT/'captures/placement-offset-test.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
