from pathlib import Path
import argparse
import json
import shutil
import sys
import time
from .runner import Job
from .engine import InputError, MAX_BYTES
from .demo import demo_files

def main():
    parser=argparse.ArgumentParser(description='Local ordered duplex sheet revision planner. No printer control.')
    sub=parser.add_subparsers(dest='command',required=True)
    cli=sub.add_parser('plan',help='Create a verified local evidence packet')
    cli.add_argument('old',type=Path);cli.add_argument('new',type=Path)
    cli.add_argument('--out',type=Path,required=True,help='New output directory; existing paths are never overwritten')
    cli.add_argument('--dpi',type=int,choices=[72,144,216],default=144)
    cli.add_argument('--force',type=int,nargs='*',default=[],help='One-based new-sheet numbers to reprint')
    web=sub.add_parser('serve',help='Start the loopback-only browser workbench')
    web.add_argument('--port',type=int,default=0);web.add_argument('--no-open',action='store_true')
    demo=sub.add_parser('demo',help='Write synthetic before/after PDFs')
    demo.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='serve':
        from .server import serve
        serve(args.port,not args.no_open);return 0
    if args.out.exists() or args.out.is_symlink():
        parser.error('Output path already exists; choose a new directory.')
    if args.command=='demo':
        args.out.mkdir(parents=True,exist_ok=False)
        for name,data in zip(('old.pdf','new.pdf'),demo_files()):(args.out/name).write_bytes(data)
        print(args.out);return 0
    job=None
    try:
        for path in (args.old,args.new):
            if not path.is_file() or path.stat().st_size>MAX_BYTES:raise InputError('Input must be a regular PDF file of at most 16 MiB.')
        job=Job(args.old.read_bytes(),args.new.read_bytes(),old_name=args.old.name,new_name=args.new.name,dpi=args.dpi,force=args.force)
        previous=''
        while True:
            state=job.snapshot()
            if state['progress']!=previous:print(state['progress'],file=sys.stderr);previous=state['progress']
            if state['status']!='running':break
            time.sleep(.1)
        if state['status']!='done':raise InputError(state.get('error','Analysis cancelled.'))
        args.out.mkdir(parents=True,exist_ok=False)
        for name in ('plan.json','assembly.html','packet.zip','replacement.pdf'):
            source=job.work/name
            if source.exists():shutil.copyfile(source,args.out/name)
        print(json.dumps(dict(output=str(args.out),summary=state['result']['summary'])));return 0
    except KeyboardInterrupt:
        if job:job.cancel()
        print('Cancelled; temporary PDFs removed.',file=sys.stderr);return 130
    except (InputError,OSError) as exc:
        print(f'Error: {exc}',file=sys.stderr);return 2
    finally:
        if job:job.close()

if __name__=='__main__':raise SystemExit(main())
