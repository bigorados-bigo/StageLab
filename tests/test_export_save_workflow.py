"""Actual unified operator overwrite, unrestricted folder, backup, source guard."""
import hashlib
import json
import pathlib
import sys
import tempfile
import bpy
from mathutils import Matrix
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT) if '--installed' not in sys.argv else str(pathlib.Path(bpy.utils.user_resource('SCRIPTS'))/'addons'))
import fpan_stage_pipeline
from fpan_stage_pipeline import core,fpan_binary,placement
fpan_stage_pipeline.register()
with tempfile.TemporaryDirectory(prefix='fpan-save-workflow-') as folder:
    root=pathlib.Path(folder)
    stage=root/'source-stage'
    stage.mkdir()
    source=stage/'bg.fbx.bin'
    node=dict(type=1,child=-1,sibling=-1,blend=0,alpha=0,matrix=Matrix.Identity(4),
              vertices=[(p,(0,0,1),(1,1,1,1),(0,0)) for p in ((0,0,0),(1,0,0),(0,1,0))],sections=[(0,[(0,1,2)])])
    original=fpan_binary.serialize(([],[('fixture',0,-1,[0]*17)],[dict(type=0,child=1,sibling=-1),node],[[],[Matrix.Identity(4)]]))
    source.write_bytes(original)
    core.import_stage(stage,clear_scene=True)
    obj=bpy.data.objects['FPAN_Node_0001']
    obj.data.vertices[0].co.y=.25
    control=placement.ensure_control(obj)
    control.location.x=.5
    control.rotation_euler.z=.2
    control.scale=(1.2,.8,1.1)
    # Sibling under source.parent used to be rejected as a whole folder tree.
    destination=root/'edited.fbx.bin'
    destination.write_bytes(b'prior user export')
    assert bpy.ops.fpan.export_stage_copy(filepath=str(destination))=={'FINISHED'}
    backups=list(root.glob('edited.fbx.bin.*.bak'))
    assert len(backups)==1 and backups[0].read_bytes()==b'prior user export'
    first=destination.read_bytes()
    decoded=fpan_binary.parse(destination)
    assert decoded[2][1]['vertices'][0][0]==(0,.25,0)
    assert abs(decoded[3][1][0][0][3]-.5)<1e-6
    # Unchanged repeat doesn't churn another backup.
    assert bpy.ops.fpan.export_stage_copy(filepath=str(destination))=={'FINISHED'}
    assert destination.read_bytes()==first and len(list(root.glob('*.bak')))==1
    control.location.x=.75
    assert bpy.ops.fpan.export_stage_copy(filepath=str(destination))=={'FINISHED'}
    backups=list(root.glob('edited.fbx.bin.*.bak'))
    assert len(backups)==2 and first in [p.read_bytes() for p in backups]
    assert source.read_bytes()==original
    try:
        bpy.ops.fpan.export_stage_copy(filepath=str(source))
    except RuntimeError as error:
        assert 'imported source file' in str(error)
    else:
        raise AssertionError('Imported baseline must be preserved')
    assert source.read_bytes()==original
    assert not list(root.glob('.fpan-export-*.tmp'))
result=dict(result='EXPORT_SAVE_WORKFLOW_PASS',version=fpan_stage_pipeline.bl_info['version'],
            same_parent_folder_allowed=True,overwrite_backup_verified=True,source_unchanged=True,
            default_overwrite_confirmation=bpy.ops.fpan.export_stage_copy.get_rna_type().properties['check_existing'].default)
assert result['default_overwrite_confirmation'] is True
(ROOT/'captures'/('export-save-workflow-installed.json' if '--installed' in sys.argv else 'export-save-workflow.json')).write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)
