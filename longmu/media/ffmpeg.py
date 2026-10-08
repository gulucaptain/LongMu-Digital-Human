import json
import subprocess
from longmu.context import settings as S


def run(cmd, **kwargs):
    subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], text=True))


def validate_video(path, frames):
    data = probe(path)
    v = next(s for s in data['streams'] if s['codec_type'] == 'video')
    if int(v.get('nb_frames', 0)) != frames:
        raise RuntimeError(f'帧数不匹配：{path}')
    if abs(float(v['duration']) - frames / S.FPS) > 1 / S.FPS:
        raise RuntimeError(f'时长不匹配：{path}')
