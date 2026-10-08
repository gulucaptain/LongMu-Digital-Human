"""按实际帧数拼接；音轨始终读取原始TTS，不使用H3重新解码的声音。"""
import math
import shutil
from longmu.context import settings as S
from longmu.media.ffmpeg import run, probe, validate_video
from longmu.cache import atomic_json
from longmu.project import load_plan
from longmu.media.subtitles import captions


def compose(ready, final=False):
    if not ready:
        return
    ready = sorted(ready, key=lambda item: item['shot']['id'])
    ids = [item['shot']['id'] for item in ready]
    if len(set(ids)) != len(ids):
        raise ValueError('合成列表包含重复镜头ID')
    folder = S.OUTPUT_PATH / ('final' if final else 'stitched')
    folder.mkdir(parents=True, exist_ok=True)
    captions(ready, folder)
    cmd, filters, links = ['ffmpeg', '-v', 'error', '-y'], [], []
    frames = sum(item['meta']['frames'] for item in ready)
    for i, item in enumerate(ready):
        ident, count = item['shot']['id'], item['meta']['frames']
        video = S.OUTPUT_PATH / 'aligned' / f'clip_{ident:02d}.mp4'
        audio = S.OUTPUT_PATH / 'audio' / f'clip_{ident:02d}_condition.wav'
        validate_video(video, count)
        cmd += ['-i', video, '-i', audio]
        filters += [f'[{2*i}:v]fps=24,trim=end_frame={count},setpts=PTS-STARTPTS,setsar=1[v{i}]',
                    f'[{2*i+1}:a]atrim=duration={count/S.FPS:.9f},asetpts=PTS-STARTPTS[a{i}]']
        links.append(f'[v{i}][a{i}]')
    filters.append(''.join(links) + f'concat=n={len(ready)}:v=1:a=1[v][a]')
    if S.BURN_SUBTITLES:
        filters.append('[v]ass=captions.ass[captioned]')
    tmp = folder / 'compose.pending.mp4'
    cmd += ['-filter_complex', ';'.join(filters), '-map', '[captioned]' if S.BURN_SUBTITLES else '[v]',
            '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-r', '24', '-frames:v', str(frames),
            '-c:a', 'aac', '-ar', '32000', '-ac', '2', '-t', f'{frames/S.FPS:.9f}',
            '-movflags', '+faststart', tmp]
    run(cmd, cwd=folder)
    validate_video(tmp, frames)
    if final:
        target = folder / (load_plan()['project_id'] + '.mp4')
    else:
        target = folder / f'progress_{len(ready):02d}_{frames}frames.mp4'
    tmp.replace(target)
    if not final:
        latest = folder / 'latest.pending.mp4'
        shutil.copyfile(target, latest)
        latest.replace(folder / 'latest.mp4')
    atomic_json(folder / 'progress.json', dict(file=target.name, shots=[x['shot']['id'] for x in ready],
                                               frames=frames, seconds=frames/S.FPS, audio='原始TTS条件音轨'))
    print(f'拼接已保存：{target}（{frames/S.FPS:.2f}秒）', flush=True)

