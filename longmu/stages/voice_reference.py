"""固定外部或初次生成的参考录音；只缓存WAV和元数据。"""
from pathlib import Path
import gc
import tempfile
from longmu.context import settings as S
from longmu.cache import atomic_json, read_json, sha
from longmu.backends.qwen_tts import load_model






def reference_paths():
    folder = S.OUTPUT_PATH / 'voice_reference'
    return folder / 'reference.wav', folder / 'reference.json'


def reference_identity():
    wav, meta_path = reference_paths()
    if not wav.is_file() or not meta_path.is_file():
        raise FileNotFoundError('缺少固定参考声音，请先运行 longmu run --project 项目.json --stage reference')
    meta = read_json(meta_path)
    x_only = bool(meta.get('x_vector_only_mode', False))
    text = meta.get('text')
    if meta['sha256'] != sha(wav) or (not x_only and (not isinstance(text,str) or not text.strip())):
        raise RuntimeError('参考声音文件或文字被改动；请使用新的OUTPUT_PATH建立新声音版本。')
    identity = dict(sha256=meta['sha256'], text=text)
    if x_only: identity['x_vector_only_mode'] = True
    return identity


def ensure_reference(plan, cls):
    from longmu.reference_source import select_reference, validate_pinned_source
    from longmu.context import current_context
    config = current_context().config
    source, source_text = select_reference(config)
    config.REFERENCE_SOURCE_AUDIO, config.REFERENCE_SOURCE_TEXT = source, source_text
    validate_pinned_source(config)
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import set_seed
    wav, meta_path = reference_paths()
    if wav.exists() or meta_path.exists():
        reference_identity()
        return wav, read_json(meta_path)
    wav.parent.mkdir(parents=True, exist_ok=True)
    text = source_text if source is not None else plan['shots'][0]['text']
    x_only = source is not None and text is None
    if S.REFERENCE_SOURCE_AUDIO is not None:
        try:
            wave, rate = sf.read(source, dtype='float32')
        except (RuntimeError, OSError):
            from longmu.media.ffmpeg import run
            with tempfile.TemporaryDirectory() as directory:
                decoded = Path(directory)/'reference.wav'
                run(['ffmpeg','-v','error','-y','-i',source,'-vn','-ac','1','-c:a','pcm_s16le',decoded])
                wave, rate = sf.read(decoded, dtype='float32')
        origin = dict(mode='import_reference', source=str(source), source_sha256=sha(source))
        print(f'导入参考录音：{source}；克隆模式：'+('仅音色（无参考文字）' if x_only else '音频+逐字文字'), flush=True)
    else:
        if S.REFERENCE_SOURCE_TEXT is not None:
            raise ValueError('未指定参考音频时，请将REFERENCE_SOURCE_TEXT设为None；自动生成第一段。')
        print('生成第一段固定参考声音（CustomVoice），之后使用Base克隆。', flush=True)
        model = load_model(cls, S.BOOTSTRAP_MODEL_PATH, 'custom_voice')
        set_seed(S.TTS_SEED + 1)
        waves, rate = model.generate_custom_voice(text=text, language=S.TTS_LANGUAGE,
                                                  speaker=S.TTS_SPEAKER, instruct=S.TTS_INSTRUCT)
        wave = waves[0]
        origin = dict(mode='bootstrap_first_clip', model_path=str(S.BOOTSTRAP_MODEL_PATH),
                      speaker=S.TTS_SPEAKER, instruct=S.TTS_INSTRUCT, seed=S.TTS_SEED + 1)
        del model
        gc.collect()
        torch.cuda.empty_cache()
    wave = np.asarray(wave, dtype=np.float32)
    if wave.ndim == 2:
        wave = wave.mean(axis=1)
    if wave.ndim != 1 or not len(wave) or not np.isfinite(wave).all():
        raise ValueError('参考音频必须是有效的单声道/双声道录音。')
    if len(wave) / rate < 3:
        raise ValueError('参考声音少于3秒；请提供至少3秒的清晰录音。')
    if np.max(np.abs(wave)) < 1e-5:
        raise ValueError('参考音频为静音。')
    tmp = wav.with_name('reference.pending.wav')
    sf.write(tmp, wave, rate, subtype='PCM_16')
    tmp.replace(wav)
    atomic_json(meta_path, dict(text=text, sha256=sha(wav), sample_rate=rate,
                               seconds=len(wave)/rate, origin=origin, x_vector_only_mode=x_only))
    print(f'固定参考已保存：{wav}；普通--force不会更换声音。', flush=True)
    return wav, read_json(meta_path)
