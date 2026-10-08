"""跨环境子进程编排、单运行锁、配置快照与阶段状态。"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
import shutil
import subprocess
from longmu.cache import atomic_json
from longmu.config import snapshot
from longmu.context import settings as S, use_context

@contextmanager
def run_lock(output):
    directory=output.parent/'.longmu-locks'
    directory.mkdir(parents=True,exist_ok=True)
    lock=directory/(sha256(str(output.resolve()).encode()).hexdigest()+'.lock')
    try:
        fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as error:
        raise RuntimeError(f'运行目录正在使用：{output}；锁文件：{lock}。若进程已异常退出，请确认无任务运行后删除该锁。') from error
    try:
        with os.fdopen(fd,'w') as handle: handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)

def worker(args):
    if args.stage in ('check','video','compose'):
        from longmu.stages.video import main
        command=[]
        if args.stage=='check':command.append('--check-interface')
        if args.stage=='compose':command.append('--compose-only')
        if args.only:command += ['--only',args.only]
        if getattr(args, 'no_compose', False):command.append('--no-compose')
        if getattr(args, 'progress_file', None):command += ['--progress-file',args.progress_file]
    else:
        from longmu.stages.speech import main
        command=['--reference-only'] if args.stage=='reference' else []
    if args.force: command.append('--force')
    main(command)

def execute(context,args):
    with use_context(context):
        return _execute(context, args)


def prepare_video_audio(launch):
    from longmu.project import load_plan
    from longmu.cache import prepared_audio
    plan = load_plan()
    missing = []
    for shot in plan['shots']:
        path = S.OUTPUT_PATH/'audio'/f"clip_{shot['id']:02d}_tts.wav"
        if not path.is_file() or not path.with_suffix('.json').is_file():
            missing.append(shot['id'])
        else:
            prepared_audio(shot)  # 过期/损坏缓存明确报错，不偷偷换声音或重生成。
    if missing:
        print(f'缺少配音镜头{missing}，先建立参考声音并生成配音，再启动视频。',flush=True)
        launch('tts', S.TTS_PYTHON, force=False)
    for shot in plan['shots']:
        prepared_audio(shot)  # TTS完成后核对真实时长/完整缓存。


def _execute(context,args):
    stage=args.stage
    if stage!='import-audio':
        for name in ('ffmpeg','ffprobe'):
            if not shutil.which(name):raise RuntimeError(f'缺少系统程序：{name}')
        if S.BURN_SUBTITLES and stage in ('all','video','compose'):
            filters=subprocess.check_output(['ffmpeg','-hide_banner','-filters'],stderr=subprocess.STDOUT,text=True)
            if not any(line.split()[1:2]==['ass'] for line in filters.splitlines()):
                raise RuntimeError('ffmpeg缺少libass；安装支持字幕的版本或设置burn_subtitles=false')
    with run_lock(S.OUTPUT_PATH):
        if stage=='import-audio':
            from longmu.stages.import_audio import import_audio
            import_audio(args.source)
        S.OUTPUT_PATH.mkdir(parents=True,exist_ok=True)
        snap=S.OUTPUT_PATH/'config.snapshot.json'
        atomic_json(snap,snapshot(context.config))
        status_path=S.OUTPUT_PATH/'state.json'
        status=dict(stage=stage,status='running',updated_at=datetime.now(timezone.utc).isoformat())
        atomic_json(status_path,status)
        def launch(name,python,force=None):
            status.update(active_stage=name)
            atomic_json(status_path,status)
            command=[python,'-m','longmu','_worker','--snapshot',str(snap),'--stage',name]
            if (args.force if force is None else force) and name!='check':command.append('--force')
            if args.only and name=='video':command += ['--only',args.only]
            subprocess.run(command,check=True)
        try:
            if stage in ('all','video','tts','reference'):
                from longmu.reference_source import select_reference, validate_pinned_source
                source, text = select_reference(context.config)
                context.config.REFERENCE_SOURCE_AUDIO = source
                context.config.REFERENCE_SOURCE_TEXT = text
                validate_pinned_source(context.config)
                atomic_json(snap,snapshot(context.config))
            if stage in ('all','video'):
                if not (S.H3_MODEL_PATH/'FL2VA').is_dir():raise FileNotFoundError(f'H3模型缺少FL2VA：{S.H3_MODEL_PATH}')
                launch('check',S.H3_PYTHON)
            if stage in ('all','tts','reference'):
                launch('reference' if stage=='reference' else 'tts',S.TTS_PYTHON)
            if stage == 'video':
                prepare_video_audio(launch)
            if stage in ('all','video','compose'):
                if stage in ('all','video') and getattr(args, 'gpus', None):
                    from longmu.parallel_video import run_parallel
                    status.update(active_stage='video', gpus=args.gpus, manifest=str(S.OUTPUT_PATH/'parallel/manifest.json'))
                    atomic_json(status_path,status)
                    run_parallel(snap,args.gpus,args.only,args.force)
                else:
                    launch('compose' if stage=='compose' else 'video',S.H3_PYTHON)
        except BaseException as error:
            status.update(status='failed',error=str(error),updated_at=datetime.now(timezone.utc).isoformat())
            atomic_json(status_path,status)
            raise
        else:
            status.update(status='complete',updated_at=datetime.now(timezone.utc).isoformat())
            atomic_json(status_path,status)
