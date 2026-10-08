"""LongMu公开命令；plan与doctor不加载GPU模型。"""
import argparse
from pathlib import Path
import sys
import subprocess
from longmu import __version__
from longmu.config import load_config, from_snapshot, ROOT
from longmu.context import RunContext, use_context

STAGES=['all','reference','tts','video','compose','import-audio']

def parser():
    p=argparse.ArgumentParser(prog='longmu',description='LongMu 教育视频创作')
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='command',required=True)
    for command in ('plan','doctor','run'):
        q=sub.add_parser(command)
        q.add_argument('--project',required=command!='doctor',help='项目JSON路径')
        q.add_argument('--config',help='部署TOML路径')
        q.add_argument('--output',help='本次运行目录；复用同一目录可恢复')
        if command=='run':
            q.add_argument('--stage',choices=STAGES,default='all')
            q.add_argument('--force',action='store_true',help='重做所选阶段；all会同时重做配音和视频')
            q.add_argument('--shots','--only',dest='only',help='仅all/video阶段筛选镜头，例如2,3')
            q.add_argument('--source',help='import-audio阶段的旧配音目录')
            q.add_argument('--gpus',help='视频并行使用的GPU编号或UUID，例如0,1；仅all/video')
    return p

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['_worker']:
        p = argparse.ArgumentParser(prog='longmu _worker')
        p.add_argument('--snapshot', required=True)
        p.add_argument('--stage', required=True, choices=['check','reference','tts','video','compose'])
        p.add_argument('--force', action='store_true')
        p.add_argument('--only')
        p.add_argument('--no-compose', action='store_true')
        p.add_argument('--progress-file')
        args = p.parse_args(argv[1:])
        from longmu.workflow import worker
        with use_context(RunContext(from_snapshot(args.snapshot))):
            worker(args)
        return
    p=parser(); args=p.parse_args(argv)
    try:
        context=RunContext(load_config(args.project,args.config,args.output))
        with use_context(context):
            if args.command=='doctor':
                from longmu.doctor import main as doctor
                return doctor(project=bool(args.project))
            from longmu.project import load_plan
            plan=load_plan()
            if args.command=='plan':
                for shot in plan['shots']:
                    count=sum('\u4e00' <= c <= '\u9fff' for c in shot['text'])
                    print(f"{shot['id']:02d} | {count}字，估计{count/4.5:.1f}秒 | {shot['text']}")
                print('实际时长由TTS决定，完整保留17n+5帧。')
                return
            if args.gpus is not None:
                if args.stage not in ('all','video'):
                    p.error('--gpus只用于all/video')
                from longmu.parallel_video import parse_gpus
                args.gpus = parse_gpus(args.gpus)
            if args.source and args.stage!='import-audio':
                p.error('--source只用于import-audio')
            if args.stage=='import-audio' and not args.source:
                p.error('import-audio需要--source')
            if args.only and args.stage not in ('all','video'):
                p.error('--shots只用于all/video')
            if args.only:
                selected={int(x) for x in args.only.split(',')}
                if not selected <= {s['id'] for s in plan['shots']}:
                    p.error('镜头编号不在计划内')
            from longmu.workflow import execute
            execute(context,args)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.CalledProcessError) as error:
        p.exit(1,f'LongMu：{error}\n')

def legacy_main(argv=None):
    """兼容原run_all.py参数；业务实现统一走公开CLI。"""
    p=argparse.ArgumentParser(description='旧LongMu入口，建议改用python -m longmu')
    p.add_argument('--stage',choices=STAGES+['plan','doctor'],default='all')
    p.add_argument('--project',default=str(ROOT/'scripts/dry-eye/project.json'))
    p.add_argument('--config')
    p.add_argument('--output')
    p.add_argument('--force',action='store_true')
    p.add_argument('--only')
    p.add_argument('--source')
    a=p.parse_args(argv)
    command=[a.stage if a.stage in ('plan','doctor') else 'run','--project',a.project]
    for name in ('config','output'):
        if getattr(a,name): command += ['--'+name,getattr(a,name)]
    if command[0]=='run':
        command += ['--stage',a.stage]
        if a.force: command.append('--force')
        if a.only: command += ['--shots',a.only]
        if a.source: command += ['--source',a.source]
    print('旧入口已转发到LongMu；部署参数请使用--config。',file=sys.stderr)
    main(command)
