"""Build an addon-only ZIP from an explicit allowlist; never collect assets."""
import ast
import hashlib
import pathlib
import zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
package=ROOT/'fpan_stage_pipeline'
module=ast.parse((package/'__init__.py').read_text(encoding='utf-8'))
info=next(ast.literal_eval(n.value) for n in module.body
          if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='bl_info' for t in n.targets))
version='.'.join(map(str,info['version']))
output=ROOT/'dist'/f'StageLab-v{version}.zip'
output.parent.mkdir(exist_ok=True)
files=sorted(p for p in package.iterdir() if p.is_file() and (p.suffix=='.py' or p.name=='README.md'))
assert files and all(p.stat().st_size<2_000_000 for p in files)
for source in files:
    if source.suffix=='.py':
        compile(source.read_text(encoding='utf-8'),str(source),'exec')
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for source in files:
        entry=zipfile.ZipInfo('fpan_stage_pipeline/'+source.name,date_time=(2026,10,17,0,0,0))
        entry.compress_type=zipfile.ZIP_DEFLATED
        entry.external_attr=0o644<<16
        archive.writestr(entry,source.read_bytes().replace(b'\r\n',b'\n'))
checksum=hashlib.sha256(output.read_bytes()).hexdigest()
(output.parent/'SHA256SUMS.txt').write_text(f'{checksum}  {output.name}\n',encoding='utf-8')
print(output)
print(checksum)
