"""每卡一个独立H3进程；续接组件同卡串行，最终按镜头ID合成。"""
import os
import re
import signal
import subprocess
import time
from longmu.cache import atomic_json, prepared_audio, read_json
from longmu.context import settings as S
from longmu.project import load_plan


def parse_gpus(value):
    ids = [part.strip() for part in value.split(',')]
    if not ids or any(not re.fullmatch(r'\d+|GPU-[A-Za-z0-9-]+|MIG-[A-Za-z0-9_/-]+', x) for x in ids):
        raise ValueError('--gpus需要逗号分隔的GPU编号或UUID，例如0,1,2')
    ids = [str(int(x)) if x.isdigit() else x for x in ids]
    if len(set(ids)) != len(ids):
        raise ValueError('--gpus不能重复指定同一显卡')
    visible = os.environ.get('CUDA_VISIBLE_DEVICES')
    if visible is not None:
        allowed = [x.strip() for x in visible.split(',')]
        if any(x not in allowed for x in ids):
            raise ValueError('--gpus必须属于当前CUDA_VISIBLE_DEVICES允许的编号/UUID，不使用重映射后的逻辑编号')
    return ids


def assignments(plan, gpu_ids, frames, selected=None):
    """同一续接组件不可拆到多卡；按帧数贪心分配，以免重复加载模型。"""
    shots = [s for s in plan['shots'] if selected is None or s['id'] in selected]
    if not shots:
        raise ValueError('未选择任何镜头')
    components, roots = {}, {}
    for shot in shots:
        ident, previous = shot['id'], shot['continue_from']
        root = roots.get(previous, ident)
        roots[ident] = root
        components.setdefault(root, []).append(ident)
    bins = [dict(gpu=gpu, shots=[], frames=0) for gpu in gpu_ids]
    for group in sorted(components.values(), key=lambda ids: (-sum(frames[i] for i in ids), ids[0])):
        target = min(bins, key=lambda item: item['frames'])
        target['shots'].extend(group)
        target['frames'] += sum(frames[i] for i in group)
    for item in bins:
        item['shots'].sort()
    return [item for item in bins if item['shots']]


def stop_workers(workers):
    for worker in workers:
        process = worker['process']
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for worker in workers:
        process = worker['process']
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def run_parallel(snapshot, gpu_ids, only=None, force=False):
    from longmu.stages.video import validate_cached
    from longmu.stages.compose import compose
    plan = load_plan()
    selected = {int(x) for x in only.split(',')} if only else None
    # 在启动任何模型之前核对全部配音；与单卡执行保持一致。
    audio = {s['id']: prepared_audio(s) for s in plan['shots']}
    jobs = assignments(plan, gpu_ids, {i: info[2] for i, info in audio.items()}, selected)
    ordered = [s for s in plan['shots'] if selected is None or s['id'] in selected]
    folder = S.OUTPUT_PATH / 'parallel'
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / 'manifest.json'
    manifest = dict(project_id=plan['project_id'], status='running', shot_order=[s['id'] for s in ordered],
                    workers=[], shots=[])
    by_id = {}
    for job in jobs:
        index = len(manifest['workers']) + 1
        job['progress'] = folder / f'worker_{index:02d}.json'
        job['log'] = folder / f'worker_{index:02d}.log'
        # 本次状态不混入上次成功记录；视频缓存仍由原有请求校验复用。
        atomic_json(job['progress'], dict(status='pending', completed=[]))
        manifest['workers'].append(dict(gpu=job['gpu'], shot_ids=job['shots'],
                                       progress=str(job['progress']), log=str(job['log'])))
        for ident in job['shots']:
            by_id[ident] = dict(id=ident, gpu=job['gpu'], continue_from=plan['shots'][ident-1]['continue_from'],
                               aligned_video=f'aligned/clip_{ident:02d}.mp4', status='pending')
    manifest['shots'] = [by_id[s['id']] for s in ordered]
    atomic_json(manifest_path, manifest)
    workers = []
    try:
        for job in jobs:
            command = [S.H3_PYTHON, '-m', 'longmu', '_worker', '--snapshot', str(snapshot),
                       '--stage', 'video', '--only', ','.join(map(str, job['shots'])),
                       '--no-compose', '--progress-file', str(job['progress'])]
            if force:
                command.append('--force')
            env = dict(os.environ, CUDA_VISIBLE_DEVICES=job['gpu'], PYTHONUNBUFFERED='1')
            handle = job['log'].open('w', encoding='utf-8')
            try:
                process = subprocess.Popen(command, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                           start_new_session=True)
            except BaseException:
                handle.close()
                raise
            workers.append(dict(job=job, process=process, log_handle=handle))
            print(f"GPU {job['gpu']}：镜头 {job['shots']}；日志 {job['log']}", flush=True)
        last_states = None
        composed_count = 0
        def ready_clips(shots):
            result = []
            for shot in shots:
                ident = shot['id']
                metadata = read_json(S.OUTPUT_PATH / 'aligned' / f'clip_{ident:02d}.json')
                validate_cached(shot, plan, audio[ident][0], audio[ident][2], metadata)
                result.append(dict(shot=shot, meta=metadata))
            return result
        while True:
            statuses = []
            for worker in workers:
                job, process = worker['job'], worker['process']
                code = process.poll()
                progress = read_json(job['progress'])
                completed = set(progress.get('completed', []))
                for ident in job['shots']:
                    by_id[ident]['status'] = ('complete' if ident in completed else
                                               'running' if progress.get('active_id') == ident else 'pending')
                statuses.append(code)
                if code is not None and code != 0:
                    for ident in job['shots']:
                        if ident not in completed:
                            by_id[ident]['status'] = 'failed'
                    raise RuntimeError(f"GPU {job['gpu']}视频进程退出码{code}；查看{job['log']}。已生成片段保留。")
                if code == 0 and completed != set(job['shots']):
                    raise RuntimeError(f"GPU {job['gpu']}未报告全部镜头完成；查看{job['log']}")
            states = [item['status'] for item in manifest['shots']]
            if states != last_states:
                atomic_json(manifest_path, manifest)
                last_states = states
            if S.SAVE_PROGRESS_AFTER_EACH_CLIP:
                prefix = []
                for shot in ordered:
                    if by_id[shot['id']]['status'] != 'complete':
                        break
                    prefix.append(shot)
                if len(prefix) > composed_count:
                    compose(ready_clips(prefix))
                    composed_count = len(prefix)
            if all(code == 0 for code in statuses):
                break
            time.sleep(0.2)
        # 合成由父进程独占，顺序来自项目ID，不使用GPU完成顺序。
        ready = ready_clips(ordered)
        manifest['status'] = 'composing'
        atomic_json(manifest_path, manifest)
        if selected is None:
            compose(ready, final=True)
        elif not S.SAVE_PROGRESS_AFTER_EACH_CLIP:
            compose(ready)
        manifest['status'] = 'complete'
        atomic_json(manifest_path, manifest)
    except BaseException as error:
        stop_workers(workers)
        manifest['status'] = 'failed'
        manifest['error'] = str(error)
        for worker in workers:
            completed = set(read_json(worker['job']['progress']).get('completed', []))
            for ident in worker['job']['shots']:
                if ident in completed:
                    by_id[ident]['status'] = 'complete'
                elif by_id[ident]['status'] != 'failed':
                    by_id[ident]['status'] = 'cancelled'
        atomic_json(manifest_path, manifest)
        raise
    finally:
        for worker in workers:
            worker['log_handle'].close()
