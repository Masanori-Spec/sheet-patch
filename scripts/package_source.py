"""Create a reviewed source ZIP and per-file SHA-256 manifest (no dependencies)."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'.git','.venv','node_modules','__pycache__','browser-artifacts','test-results','demo-input','demo-packet','forced-packet'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    files=[]
    for file in sorted(ROOT.rglob('*')):
        rel=file.relative_to(ROOT)
        if not file.is_file() or file.is_symlink() or any(p in EXCLUDED for p in rel.parts) or file.suffix in ('.pyc','.log'):continue
        if file.name=='benchmark-ci.json':continue
        files.append(file)
    manifest=[]
    target=args.out/'sheet-patch.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            data=file.read_bytes();name=file.relative_to(ROOT).as_posix()
            manifest.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
            archive.writestr('sheet-patch/'+name,data)
    result=dict(project='sheet-patch',version='0.1.0',fileCount=len(files),files=manifest,archive=dict(name=target.name,bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    (args.out/'sheet-patch-source-manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(archive=str(target),fileCount=len(files),sha256=result['archive']['sha256'])))
if __name__=='__main__':main()
