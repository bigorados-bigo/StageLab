"""Run with Blender --background --factory-startup --python this.py -- ZIP."""
import pathlib
import sys
import tempfile
import zipfile
archive=pathlib.Path(sys.argv[sys.argv.index('--')+1]).resolve()
with tempfile.TemporaryDirectory(prefix='stagelab-release-smoke-') as folder:
    target=pathlib.Path(folder)
    with zipfile.ZipFile(archive) as package:
        assert all(name.startswith('fpan_stage_pipeline/') and '..' not in pathlib.PurePosixPath(name).parts
                   for name in package.namelist())
        package.extractall(target)
    sys.path.insert(0,str(target))
    import fpan_stage_pipeline
    assert pathlib.Path(fpan_stage_pipeline.__file__).is_relative_to(target)
    assert fpan_stage_pipeline.bl_info['name']=='StageLab'
    assert fpan_stage_pipeline.bl_info['version']==(0,1,0)
    fpan_stage_pipeline.register()
    import bpy
    assert hasattr(bpy.types.Scene,'fpan_stage')
    assert bpy.ops.fpan.export_stage_copy.get_rna_type()
    fpan_stage_pipeline.unregister()
print('STAGELAB_RELEASE_ZIP_SMOKE_PASS',flush=True)
