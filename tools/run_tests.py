"""Run isolated synthetic Blender tests; fail on traceback even if Blender exits0."""
import argparse
import pathlib
import subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--blender',required=True,help='Path to Blender executable')
args=parser.parse_args()
(ROOT/'captures').mkdir(exist_ok=True)
for name,marker in [('test_affine_preservation.py','AFFINE_PRESERVATION_RELOAD_RESET_PASS'),
                    ('test_export_save_workflow.py','EXPORT_SAVE_WORKFLOW_PASS'),
                    ('test_placement_offsets.py','PLACEMENT_AFFINE_LOOP_RELOAD_RESET_PASS')]:
    result=subprocess.run([args.blender,'--background','--factory-startup','--python',str(ROOT/'tests'/name)],
                          cwd=ROOT,capture_output=True,text=True,errors='replace')
    print(result.stdout)
    print(result.stderr)
    if result.returncode or marker not in result.stdout or 'Traceback (most recent call last)' in result.stdout+result.stderr:
        raise SystemExit(f'FAIL: {name}')
print('STAGELAB_SYNTHETIC_TESTS_PASS')
