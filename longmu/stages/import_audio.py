"""导入独立v3版已有配音，保留参考声音；校验失败不安装半套缓存。"""
import argparse
from pathlib import Path
import shutil
import tempfile
from dataclasses import replace
from longmu.context import RunContext, current_context, use_context
from longmu.context import settings as S
from longmu.project import load_plan
from longmu.cache import prepared_audio


def import_audio(source):
    source = Path(source).expanduser().resolve()
    destination = S.OUTPUT_PATH
    if destination.exists():
        raise FileExistsError(f'导入要求全新输出目录，避免覆盖现有结果：{destination}')
    for folder in ('voice_reference', 'audio'):
        if not (source / folder).is_dir():
            raise FileNotFoundError(f'缺少{source / folder}；--source应指定renders_v3_clone目录')
    destination.parent.mkdir(parents=True, exist_ok=True)
    plan = load_plan()
    with tempfile.TemporaryDirectory(prefix='.import-audio-', dir=destination.parent) as temporary:
        staging = Path(temporary) / 'validated'
        shutil.copytree(source / 'voice_reference', staging / 'voice_reference')
        (staging / 'audio').mkdir()
        for shot in plan['shots']:
            for suffix in ('_tts.wav', '_tts.json', '_unprocessed.wav'):
                item = source / 'audio' / f'clip_{shot["id"]:02d}{suffix}'
                if item.exists():
                    shutil.copy2(item, staging / 'audio' / item.name)
        try:
            staging_context = RunContext(replace(current_context().config, OUTPUT_PATH=staging))
            with use_context(staging_context):
                for shot in plan['shots']:
                    prepared_audio(shot)
        except (ValueError, RuntimeError, FileNotFoundError) as error:
            raise RuntimeError(f'旧配音校验失败，未导入；请核对模型路径、版本、语言、种子、语速及台词。原因：{error}') from error
        if destination.exists():
            raise FileExistsError('导入时输出目录已被其他进程创建，请勿并行导入')
        staging.rename(destination)
    print(f'已导入{len(plan["shots"])}段配音和固定参考声音：{destination}；未导入旧视频。')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    import_audio(p.parse_args(argv).source)


if __name__ == '__main__':
    main()
