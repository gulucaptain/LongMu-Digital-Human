"""本地FL2VA首帧/首尾帧 + retake_audio保留音频的实验性视频生成。"""
import argparse
import inspect
import math
import uuid
from pathlib import Path
from longmu.context import settings as S
from longmu.project import load_plan, shot_type
from longmu.cache import prepared_audio, read_json, atomic_json, sha
from longmu.media.ffmpeg import run, validate_video
from longmu.stages.compose import compose


def check_interface():
    from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline
    loaded = Path(inspect.getfile(MiniMaxH3Pipeline)).resolve()
    if loaded != S.H3_SOURCE_PATH.resolve():
        raise RuntimeError(f'H3加载了其他仓库：{loaded}；期望{S.H3_SOURCE_PATH}。请使用本仓库环境。')
    print(f'H3实际加载文件：{loaded}', flush=True)
    params = inspect.signature(MiniMaxH3Pipeline.__call__).parameters
    required = {'keyframes', 'keyframe_indices', 'retake_audio', 'retake_audio_sample_rate', 'seconds_regions_to_retake'}
    if not required <= params.keys():
        raise RuntimeError(f'DiffSynth版本缺少输入音频保留接口：{required - params.keys()}。不会退回独立生成语音。')
    if S.H3_AUDIO_MODE != 'retake_preserve':
        raise ValueError('本版本只实现retake_preserve实验路径')
    print('H3接口检查通过；这不等于口型同步效果已验证。', flush=True)


def base_settings():
    return dict(pipeline_sha=sha(S.H3_SOURCE_PATH), model_path=str(S.H3_MODEL_PATH), revision=S.H3_REVISION_TAG, width=S.WIDTH,
                height=S.HEIGHT, steps=S.H3_STEPS, fps=S.FPS, audio_mode=S.H3_AUDIO_MODE,
                backend_sha=sha(Path(__file__).parents[1] / 'backends/minimax_h3.py'),
                lead=S.AUDIO_LEAD_SECONDS, tail=S.AUDIO_TAIL_SECONDS,
                min_seconds=S.MIN_VIDEO_SECONDS, max_seconds=S.MAX_VIDEO_SECONDS)


def source_images(shot, plan):
    if shot['first_image']:
        start = S.ASSET_ROOT / shot['first_image']
    else:
        ident = shot['continue_from']
        previous = next(s for s in plan['shots'] if s['id'] == ident)
        prev_audio, _, prev_frames = prepared_audio(previous)
        video = S.OUTPUT_PATH / 'aligned' / f'clip_{ident:02d}.mp4'
        meta = read_json(video.with_suffix('.json'))
        validate_cached(previous, plan, prev_audio, prev_frames, meta)
        validate_video(video, prev_frames)
        start = S.OUTPUT_PATH / 'keyframes' / f"clip_{shot['id']:02d}_first.png"
        start.parent.mkdir(parents=True, exist_ok=True)
        temporary = start.with_name(start.stem + '.' + uuid.uuid4().hex + '.pending.png')
        try:
            run(['ffmpeg', '-v', 'error', '-y', '-i', video, '-vf',
                 f'select=eq(n\\,{prev_frames-1})', '-frames:v', '1', temporary])
            if not temporary.is_file():
                raise RuntimeError('未提取到前段实际末帧')
            temporary.replace(start)
        finally:
            temporary.unlink(missing_ok=True)
    tail = shot['last_image']
    end = start if tail == 'same_as_start' else S.ASSET_ROOT / tail if tail else None
    return start, end


def make_prompt(shot, frames, speech_seconds, has_end, plan=None):
    duration = frames / S.FPS
    plan = plan or load_plan()
    character = plan['characters'][shot['scene']]
    subject = character['description']
    continuity = 'Continue exactly from the supplied preceding final frame; do not reset the head, shoulders or hands.' if shot['continue_from'] else 'Begin in the exact supplied first-frame composition and pose.'
    ending = 'Gradually settle into the supplied target last-frame pose near the end; never teleport or abruptly snap to it.' if has_end else 'End with a stable, natural pose and minimal ongoing body motion.'
    mode = character['speech_mode']
    speaking = ('The visible character speaks the supplied audio with synchronized mouth motion; use the given audio timing, not a newly invented speaking pace. (S1) says:'
                if mode == 'on_camera' else
                'The visible character remains silent, with lips closed and no talking mouth movements wherever the face is visible. (S1) says in an off-screen voiceover:')
    performance = ('During speech use only subtle natural head movements and relaxed hands, consistent with the stated action.'
                   if shot_type(shot, character) == 'talking_head' else
                   'Perform only the stated single demonstration action in a smooth, physically plausible sequence from the supplied initial state to the stated end state. Move existing props only as required by that action; do not add extra procedure steps. This is a voiceover demonstration, not an on-camera speech performance.')
    if shot_type(shot, character) == 'speaking_action':
        speaking = ('The doctor herself delivers the supplied dialogue while performing the stated action. '
                    'Whenever her face is visible, show clear natural articulating lips and jaw movements synchronized '
                    'with the voiced portions of the supplied audio. In close-ups where her face is outside the crop, '
                    'the same doctor continues her explanation; preserve the planned framing. (S1) says:')
        performance = ('Coordinate the stated single prop action with engaged speech: natural breathing, small shoulder '
                       'and elbow adjustments, a responsive wrist, and brief gaze shifts between the task and viewer '
                       'where the face is visible. Keep hand movement readable and physically grounded. '
                       'Let the doctor remain naturally alive throughout the shot rather than freezing her body while '
                       'only the prop moves. Preserve the supplied audio timing; animate the mouth only during voiced '
                       'speech, not during silence. Keep to the stated task without extra procedure steps.')
        ending = ('Arrive at the supplied target hand-and-prop state near the final frame without reaching it early '
                  'and waiting motionless. Keep facial articulation responsive through the actual voiced interval; '
                  'the target facial expression belongs to the ending instant, not the whole clip.' if has_end else
                  'Carry natural breathing and responsive posture through the end. Finish the stated movement smoothly '
                  'without a separate staged still-photo hold or farewell gesture.')
    references = 'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.'
    if has_end:
        references += f' At {(frames-1)/S.FPS:.2f} seconds into the target video, <Picture 2> (from [Shot 1]) is fully referenced.'
    aspect = f'{S.WIDTH}:{S.HEIGHT}'
    constraints = plan.get('visual_constraints', '')
    return f'''{references}

integrated_multimodal_description: [Shot 1] Live-action, professional medical education video, a single continuous {duration:.3f}-second shot, aspect ratio {aspect}, showing {subject}. Use the framing, room and lighting of the supplied reference. {continuity} Preserve identity, facial features, hairstyle, clothing, room, lighting and the appearance of existing props. Keep props in place except for movements explicitly described in the action. The camera remains steady with fixed framing, no cuts or zooms. No added people or unrelated props. {shot['action']} {speaking} <d>[{S.TTS_LANGUAGE}] {shot['text']}</d> Speech begins around {S.AUDIO_LEAD_SECONDS:.2f} seconds and lasts {speech_seconds:.3f} seconds. {performance} {ending} No generated subtitles, captions, labels, logos, watermarks or other readable text. {constraints}

overall_soundscape: Preserve the supplied TTS waveform, speaker identity (S1), timbre, pacing and pauses rather than generating a new voice or paraphrasing. The supplied speech determines delivery and timing. After it finishes, retain the supplied silence. No other dialogue or vocal sounds. Do not add room ambience absent from the supplied audio.

non_diegetic_music: No background music.
'''


def request_fingerprint(shot, frames, audio_path, start_path, end_path, prompt):
    return dict(base_settings=base_settings(), audio_sha=sha(audio_path),
                first_sha=sha(start_path), last_sha=sha(end_path) if end_path else None,
                frames=frames, prompt=prompt, seed=S.H3_SEED+shot['id'])


def validate_cached(shot, plan, audio_path, frames, metadata, fingerprint=None):
    """生成、仅合成与续接来源共享完整请求校验。"""
    if fingerprint is None:
        start, end = source_images(shot, plan)
        _, audio_meta, _ = prepared_audio(shot)
        prompt = make_prompt(shot, frames, audio_meta['speech_seconds'], end is not None, plan)
        fingerprint = request_fingerprint(shot, frames, audio_path, start, end, prompt)
    ident = shot['id']
    video = S.OUTPUT_PATH/'aligned'/f'clip_{ident:02d}.mp4'
    condition = S.OUTPUT_PATH/'audio'/f'clip_{ident:02d}_condition.wav'
    if metadata.get('request') != fingerprint:
        raise RuntimeError(f'第{ident}镜缓存参数已变化，请重新生成该镜头及续接镜头。')
    if metadata.get('aligned_sha') != sha(video):
        raise RuntimeError(f'第{ident}镜视频文件已变化')
    if not condition.is_file() or metadata.get('condition_sha') != sha(condition):
        raise RuntimeError(f'第{ident}镜条件音轨缺失或已变化')
    validate_video(video, frames)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-interface', action='store_true')
    p.add_argument('--force', action='store_true')
    p.add_argument('--only', help='指定镜头，例如1,2,3；续接镜头要求前段已存在且参数匹配')
    p.add_argument('--compose-only', action='store_true')
    p.add_argument('--no-compose', action='store_true', help='并行worker只生成镜头，合成由父进程负责')
    p.add_argument('--progress-file', help='该worker独占的完成记录')
    args = p.parse_args(argv)
    plan = load_plan()
    if args.check_interface:
        check_interface()
        return
    selected = {int(x) for x in args.only.split(',')} if args.only else None
    if selected and not selected <= {s['id'] for s in plan['shots']}:
        p.error('镜头编号不在计划内')
    # 首先核对全部音频，超时/过期就停止，避免加载昂贵视频模型后才失败。
    audio_info = {s['id']: prepared_audio(s) for s in plan['shots']}
    if args.compose_only:
        ready = []
        for shot in plan['shots']:
            if selected and shot['id'] not in selected:
                continue
            video = S.OUTPUT_PATH / 'aligned' / f"clip_{shot['id']:02d}.mp4"
            metadata = read_json(video.with_suffix('.json'))
            audio_path, _, _ = audio_info[shot['id']]
            validate_cached(shot, plan, audio_path, audio_info[shot['id']][2], metadata)
            ready.append(dict(shot=shot, meta=metadata))
        compose(ready, final=selected is None)
        return
    check_interface()
    import torch
    import soundfile as sf
    import numpy as np
    from PIL import Image, ImageOps
    from diffsynth.utils.data.audio_video import write_video_audio
    from longmu.backends.minimax_h3 import load_pipeline
    for folder in ('raw', 'aligned', 'prompts', 'audio'):
        (S.OUTPUT_PATH / folder).mkdir(parents=True, exist_ok=True)
    pipe, ready = None, []
    def record_progress(status, active_id=None):
        if args.progress_file:
            atomic_json(Path(args.progress_file), dict(status=status, active_id=active_id, completed=[item['shot']['id'] for item in ready]))
    record_progress('running')
    for shot in plan['shots']:
        if selected and shot['id'] not in selected:
            continue
        ident = shot['id']
        record_progress('running', ident)
        audio_path, audio_meta, frames = audio_info[ident]
        start_path, end_path = source_images(shot, plan)
        prompt = make_prompt(shot, frames, audio_meta['speech_seconds'], end_path is not None, plan)
        (S.OUTPUT_PATH / 'prompts' / f'clip_{ident:02d}.txt').write_text(prompt, encoding='utf-8')
        fingerprint = request_fingerprint(shot, frames, audio_path, start_path, end_path, prompt)
        aligned = S.OUTPUT_PATH / 'aligned' / f'clip_{ident:02d}.mp4'
        meta_path = aligned.with_suffix('.json')
        if aligned.exists() and meta_path.exists() and not args.force:
            cached = read_json(meta_path)
            validate_cached(shot, plan, audio_path, frames, cached, fingerprint)
            ready.append(dict(shot=shot, meta=cached))
            print(f'复用视频 {ident:02d}', flush=True)
        else:
            voice, rate = sf.read(audio_path, dtype='float32', always_2d=True)
            if rate != 32000:
                raise ValueError('准备的TTS应为32000Hz')
            lead = round(S.AUDIO_LEAD_SECONDS * rate)
            samples = math.ceil(frames / S.FPS * rate)
            stereo = np.zeros((samples, 2), dtype=np.float32)
            if lead + len(voice) > samples:
                raise RuntimeError('不会截断TTS音频：条件音轨时长不足')
            stereo[lead:lead+len(voice)] = np.repeat(voice[:, :1], 2, axis=1)
            condition_path = S.OUTPUT_PATH / 'audio' / f'clip_{ident:02d}_condition.wav'
            sf.write(condition_path, stereo, rate, subtype='PCM_16')
            condition = torch.from_numpy(stereo.T.copy())
            if pipe is None:
                pipe = load_pipeline(S.H3_MODEL_PATH)
            images = []
            for path in ([start_path, end_path] if end_path else [start_path]):
                with Image.open(path) as im:
                    images.append(ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'),
                                               (S.WIDTH, S.HEIGHT), Image.Resampling.LANCZOS))
            indices = [0, -1] if end_path else [0]
            print(f'生成视频{ident:02d}：{frames/S.FPS:.3f}秒，首帧索引{indices}，给定TTS保留模式', flush=True)
            with torch.inference_mode():
                video, reconstructed_audio = pipe(
                    prompt=prompt, height=S.HEIGHT, width=S.WIDTH, num_frames=frames,
                    num_inference_steps=S.H3_STEPS, seed=S.H3_SEED+ident,
                    keyframes=images, keyframe_indices=indices,
                    retake_audio=condition, retake_audio_sample_rate=rate,
                    seconds_regions_to_retake=[])
            if len(video) != frames:
                raise RuntimeError('视频返回帧数不匹配；不会裁掉尾帧')
            raw = S.OUTPUT_PATH / 'raw' / f'clip_{ident:02d}_h3.mp4'
            raw_tmp = raw.with_name(raw.stem+'.pending.mp4')
            write_video_audio(video=video, audio=reconstructed_audio, output_path=str(raw_tmp),
                              fps=S.FPS, audio_sample_rate=pipe.audio_vae.sample_rate)
            validate_video(raw_tmp, frames)
            raw_tmp.replace(raw)
            tmp = aligned.with_name(aligned.stem+'.pending.mp4')
            # 配回原始TTS；VAE解码声音仅在raw里保留以供诊断。
            run(['ffmpeg', '-v', 'error', '-y', '-i', raw, '-i', condition_path,
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
                 '-t', f'{frames/S.FPS:.9f}', '-movflags', '+faststart', tmp])
            validate_video(tmp, frames)
            tmp.replace(aligned)
            metadata = dict(shot_id=ident, project_id=plan['project_id'], request=fingerprint, frames=frames, speech_seconds=audio_meta['speech_seconds'],
                            audio_sha=sha(audio_path), condition_sha=sha(condition_path),
                            aligned_sha=sha(aligned), base_settings=base_settings(),
                            mode='FL2VA首尾帧+retake_audio保留：实验性，口型未验证')
            atomic_json(meta_path, metadata)
            ready.append(dict(shot=shot, meta=metadata))
            del video, reconstructed_audio, condition, images
        record_progress('running')
        if S.SAVE_PROGRESS_AFTER_EACH_CLIP and not args.no_compose:
            try:
                compose(ready)
            except Exception as error:
                print(f'累计拼接失败，原始短片已保留：{error}', flush=True)
    if not args.no_compose:
        if selected is None:
            compose(ready, final=True)
        elif not S.SAVE_PROGRESS_AFTER_EACH_CLIP:
            compose(ready)
    record_progress('complete')


if __name__ == '__main__':
    main()
