"""先生成全部TTS；有外部参考时全部使用Base克隆，否则首段建立声音。"""
import argparse
import os
from pathlib import Path
from longmu.context import settings as S
from longmu.project import load_plan
from longmu.cache import atomic_json, read_json, sha, tts_request
from longmu.media.ffmpeg import run
from longmu.media.audio import aligned_frames



def reuse_bootstrap_clip(shot, reference):
    return (shot['id'] == 1 and shot['text'] == reference.get('text') and
            reference.get('origin', {}).get('mode') == 'bootstrap_first_clip')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--force', action='store_true')
    p.add_argument('--reference-only', action='store_true')
    args = p.parse_args(argv)
    plan = load_plan()
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import torch
    import soundfile as sf
    import numpy as np
    from transformers import set_seed
    from qwen_tts import Qwen3TTSModel
    if not torch.cuda.is_available():
        raise RuntimeError('本配置需要可用CUDA GPU')
    folder = S.OUTPUT_PATH / 'audio'
    folder.mkdir(parents=True, exist_ok=True)
    if not 0.5 <= S.TTS_TEMPO <= 2.0:
        raise ValueError('TTS_TEMPO建议设在0.5至2.0之间')
    from longmu.stages.voice_reference import ensure_reference
    from longmu.backends.qwen_tts import load_model
    reference_path, reference_meta = ensure_reference(plan, Qwen3TTSModel)
    if args.reference_only:
        return
    model = None
    clone_prompt = None
    timeline, errors = [], []
    for shot in plan['shots']:
        path = folder / f"clip_{shot['id']:02d}_tts.wav"
        meta_path = path.with_suffix('.json')
        request = tts_request(shot)
        if path.exists() and meta_path.exists() and not args.force:
            old = read_json(meta_path)
            if old['request'] != request or old['sha256'] != sha(path):
                raise RuntimeError(f'旧TTS缓存不匹配：{path}；用--force重生成。')
            speech_seconds = old['speech_seconds']
            print(f"复用TTS {shot['id']:02d}", flush=True)
        else:
            print(f"克隆配音 {shot['id']:02d}：{shot['text']}", flush=True)
            set_seed(request['seed'])
            # 仅自动生成的首段可以复用；外部参考录音从第一镜起也走克隆。
            if reuse_bootstrap_clip(shot, reference_meta):
                reference_wave, rate = sf.read(reference_path, dtype='float32')
                wavs = [reference_wave]
            else:
                if model is None:
                    model = load_model(Qwen3TTSModel, S.TTS_MODEL_PATH, 'base')
                    clone_prompt = model.create_voice_clone_prompt(
                        ref_audio=str(reference_path), ref_text=reference_meta.get('text'),
                        x_vector_only_mode=bool(reference_meta.get('x_vector_only_mode',False)))
                wavs, rate = model.generate_voice_clone(
                    text=shot['text'], language=S.TTS_LANGUAGE,
                    voice_clone_prompt=clone_prompt)
            waveform = np.asarray(wavs[0], dtype=np.float32).squeeze()
            if waveform.ndim != 1 or not len(waveform) or not np.isfinite(waveform).all():
                raise RuntimeError('TTS返回无效单声道音频')
            raw = folder / f"clip_{shot['id']:02d}_unprocessed.wav"
            sf.write(raw, waveform, rate, subtype='PCM_16')
            temporary = path.with_name(path.stem + '.pending.wav')
            run(['ffmpeg', '-v', 'error', '-y', '-i', raw, '-af', f'atempo={S.TTS_TEMPO}',
                 '-ar', '32000', '-ac', '1', '-c:a', 'pcm_s16le', temporary])
            temporary.replace(path)
            info = sf.info(path)
            speech_seconds = info.frames / info.samplerate
            atomic_json(meta_path, dict(request=request, speech_seconds=speech_seconds,
                                        sample_rate=info.samplerate, sha256=sha(path)))
        try:
            frames = aligned_frames(speech_seconds)
            timeline.append(dict(id=shot['id'], text=shot['text'], speech_seconds=speech_seconds,
                                 frames=frames, video_seconds=frames / S.FPS))
        except ValueError as error:
            errors.append(f"镜头{shot['id']}: {error}")
    atomic_json(folder / 'tts_timing_report.json', dict(shots=timeline, errors=errors,
                                                       total_seconds=sum(x['video_seconds'] for x in timeline)))
    if errors:
        raise RuntimeError('全部TTS已生成，但以下段落需调整；尚未启动H3：\n' + '\n'.join(errors))
    print(f"全部{len(timeline)}段TTS准备完成；预计视频总长{sum(x['video_seconds'] for x in timeline):.2f}秒。", flush=True)


if __name__ == '__main__':
    main()
