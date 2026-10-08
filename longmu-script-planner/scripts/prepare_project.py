#!/usr/bin/env python3
"""通过真实LongMu接口校验剧本、估算预算、预览H3提示；不运行模型。"""
import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path


def find_repo(explicit):
    if explicit:
        candidates = [Path(explicit).expanduser().resolve()]
    else:
        candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for path in candidates:
        if (path / 'longmu/project.py').is_file():
            return path
    raise ValueError('未找到LongMu仓库，请传--repo；不会退回过时模板。')


def estimated_seconds(text):
    # 只作初筛；数字、字母缩写与标点的真实读法需人工核对/TTS实测。
    han = len(re.findall(r'[\u4e00-\u9fff]', text))
    latin = len(re.findall(r'[A-Za-z]+|\d+(?:\.\d+)?', text))
    return max(0.5, han / 4.5 + latin / 2.5), han


def prepare(repo, project, runtime=None, output=None, use_audio=False):
    sys.path.insert(0, str(repo))
    import longmu
    if Path(longmu.__file__).resolve().parent != repo / 'longmu':
        raise ValueError('加载了其他LongMu安装，请在本仓库的环境中运行。')
    from longmu.config import load_config
    from longmu.context import RunContext, use_context
    from longmu.project import load_plan, shot_type
    from longmu.media.audio import aligned_frames
    from longmu.stages.video import make_prompt
    config = load_config(project, runtime, output)
    with use_context(RunContext(config)):
        plan = load_plan()
        # 这些字段会被当前产品忽略，不能声称相应需求可执行。
        unsupported = {'voices', 'speakers', 'timeline', 'chapters'} & plan.keys()
        if unsupported:
            raise ValueError(f'当前产品不消费{sorted(unsupported)}，请移到planning.json并说明待扩展。')
        for key, character in plan['characters'].items():
            unsupported = {'speaker','speaker_id','voice_id','reference_audio'} & character.keys()
            if unsupported:
                raise ValueError(f'角色{key}逐角色声音配置尚不支持：{sorted(unsupported)}')
        warnings = ['项目共用一套声音；字数估算不代表TTS实测；画面/道具/操作准确性仍需看图和试生成。']
        warnings.append('首尾帧的身份、姿态可达性、裁切与操作准确性未自动校验；音频缓存通过也不代表画面审核通过。')
        rows = []
        for shot in plan['shots']:
            ignored = {'duration','duration_seconds','video_prompt','speaker','speech_mode'} & shot.keys()
            if ignored:
                raise ValueError(f'镜头{shot["id"]}包含未消费或层级不正确字段：{sorted(ignored)}')
            estimate, han = estimated_seconds(shot['text'])
            if re.search(r'\d|[A-Za-z]', shot['text']):
                warnings.append(f'镜头{shot["id"]}含数字/字母，核对实际读法。')
            if re.search(r'<d>|</d>|\[Chinese\]|停顿\d*秒', shot['text']):
                warnings.append(f'镜头{shot["id"]}疑似含标签/导演指令，确认text只含台词。')
            if use_audio:
                from longmu.cache import prepared_audio
                _, metadata, frames = prepared_audio(shot)
                seconds = metadata['speech_seconds']
                if not math.isfinite(seconds) or seconds <= 0:
                    raise ValueError('音频记录的时长无效。')
                basis = 'validated_audio_cache'
            else:
                seconds = estimate
                basis = 'estimated_not_measured'
                try:
                    frames = aligned_frames(seconds)
                except ValueError as error:
                    frames = None
                    warnings.append(f'镜头{shot["id"]}估算超预算：{error}')
            rows.append(dict(id=shot['id'], scene=shot['scene'], shot_type=shot_type(shot, plan['characters'][shot['scene']]), text=shot['text'], action=shot['action'],
                             speech_mode=plan['characters'][shot['scene']]['speech_mode'],
                             first_image=shot['first_image'], continue_from=shot['continue_from'],
                             last_image=shot['last_image'], han_characters=han, timing_basis=basis,
                             speech_seconds=seconds, frames=frames,
                             video_seconds=frames / config.FPS if frames else None,
                             prompt=make_prompt(shot, frames, seconds, shot['last_image'] is not None, plan)
                                    if frames else None))
        maximum = (math.floor((config.MAX_VIDEO_SECONDS * config.FPS - 5) / 17) * 17 + 5) / config.FPS
        return dict(project_id=plan['project_id'], schema_version=plan['schema_version'],
                    project=str(config.PLAN_PATH), output=str(config.OUTPUT_PATH),
                    status=('audio_cache_validated' if use_audio else 'project_validated_timing_estimated')
                        if all(row['frames'] for row in rows) else 'needs_resegmentation',
                    visual_review_required=True,
                    single_voice=True, audio_budget_seconds=maximum-config.AUDIO_LEAD_SECONDS-config.AUDIO_TAIL_SECONDS,
                    total_video_seconds=sum(row['video_seconds'] or 0 for row in rows)
                        if all(row['frames'] for row in rows) else None,
                    warnings=warnings, shots=rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo')
    p.add_argument('--project', required=True)
    p.add_argument('--config')
    p.add_argument('--output', help='真实音频缓存所在运行目录，不是预览目录')
    p.add_argument('--use-audio', action='store_true', help='严格校验全部已生成TTS，以真实时长预览')
    p.add_argument('--preview-dir', required=True)
    args = p.parse_args()
    try:
        report = prepare(find_repo(args.repo), args.project, args.config, args.output, args.use_audio)
        folder = Path(args.preview_dir).expanduser().resolve()
        target = Path(args.project).expanduser().resolve()
        artifact_paths = [folder/'review.json', folder/'shot_plan.csv'] + [folder/f'clip_{row["id"]:02d}_prompt.txt' for row in report['shots'] if row['prompt']]
        if target in artifact_paths:
            raise ValueError('预览输出不能覆盖project.json。')
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        keys = [key for key in report['shots'][0] if key != 'prompt']
        with (folder/'shot_plan.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(report['shots'])
        for row in report['shots']:
            if row['prompt']:
                (folder/f'clip_{row["id"]:02d}_prompt.txt').write_text(row['prompt'], encoding='utf-8')
        print(f'{report["status"]}；{len(report["shots"])}镜头；预览：{folder}')
        for warning in report['warnings']:
            print(f'提示：{warning}')
        return 2 if report['status'] == 'needs_resegmentation' else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        print(f'项目检查失败：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
