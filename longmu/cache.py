import hashlib
import json
import uuid
from pathlib import Path
from longmu.context import settings as S
from longmu.media.audio import aligned_frames


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tts_request(shot):
    # 缓存绑定固定参考录音，换声音后旧配音/视频不会被误复用。
    from longmu.stages.voice_reference import reference_identity, reference_paths
    identity = reference_identity()
    request = dict(text=shot['text'], model_path=str(S.TTS_MODEL_PATH), revision=S.TTS_REVISION_TAG,
                language=S.TTS_LANGUAGE, reference=identity,
                seed=S.TTS_SEED + shot['id'], tempo=S.TTS_TEMPO)
    if shot['id'] == 1 and shot['text'] == identity.get('text'):
        meta = read_json(reference_paths()[1])
        if meta.get('origin', {}).get('mode') != 'bootstrap_first_clip':
            request['first_clip_generation'] = 'voice_clone'
    return request


def prepared_audio(shot):
    folder = S.OUTPUT_PATH / 'audio'
    path = folder / f"clip_{shot['id']:02d}_tts.wav"
    meta_path = path.with_suffix('.json')
    if not path.is_file() or not meta_path.is_file():
        raise FileNotFoundError(f'先生成全部TTS音频：缺少{path}')
    meta = read_json(meta_path)
    if meta['request'] != tts_request(shot) or meta['sha256'] != sha(path):
        raise RuntimeError(f"第{shot['id']}段TTS设置或文件已变化，请重做TTS。")
    # 时长/帧数参数修改后重新计算，而不是复用旧的帧数。
    frames = aligned_frames(meta['speech_seconds'])
    return path, meta, frames
