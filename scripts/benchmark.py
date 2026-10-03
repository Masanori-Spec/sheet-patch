"""Reproducible synthetic benchmark. Measures wall time; no speed guarantee."""
from pathlib import Path
import argparse
import json
import platform
import resource
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sheet_patch.demo import make_pdf,demo_files
from sheet_patch.runner import Job

def run(label,old,new,dpi):
    start=time.monotonic();job=Job(old,new,dpi=dpi)
    try:
        while job.snapshot()['status']=='running':time.sleep(.05)
        state=job.snapshot()
        if state['status']!='done':raise RuntimeError(state)
        result=state['result']
        return dict(case=label,oldBytes=len(old),newBytes=len(new),oldSides=result['old']['sideCount'],newSides=result['new']['sideCount'],dpi=dpi,inputPixels=result['verification']['inputPixels'],replacementSides=result['verification']['replacementSideCount'],wallSeconds=round(time.monotonic()-start,3),workerSeconds=result['verification']['elapsedSeconds'],summary=result['summary'])
    finally:job.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path('docs/benchmark.json'));args=parser.parse_args()
    cases=[]
    cases.append(run('synthetic 3-to-4 sheet revision',*demo_files(),144))
    old=make_pdf([f'sheet {i//2+1} '+('front' if i%2==0 else 'back') for i in range(80)])
    new=make_pdf([f'revised {i//2+1} '+('front' if i%2==0 else 'back') for i in range(80)])
    cases.append(run('80+80 sides, all changed, 216 DPI',old,new,216))
    cases.append(run('80+80 sides, all unchanged, 216 DPI',old,old,216))
    data=dict(python=platform.python_version(),platform=platform.platform(),renderer=subprocess.run(['pdftoppm','-v'],capture_output=True,text=True).stderr.splitlines()[0],cases=cases,childPeakRssKiB=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,notes=['Synthetic simple vector/text PDFs, not arbitrary real-world documents.','Peak RSS is the maximum reported child process, not aggregate worker+renderer+server memory.','Local test used system Poppler 25.03.0 with a writable temporary Fontconfig cache; bundled environment Poppler cache emitted errors.','180-second wall limit is enforced, not a promise that every accepted-size PDF succeeds.'])
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))
if __name__=='__main__':main()
