"""检查当前仓库的H3源码、路径与配音缓存；不导入CUDA模型。"""
import ast
import sys
import shutil
from longmu.context import settings as S
from longmu.project import load_plan
from longmu.cache import prepared_audio


def check_source():
    tree = ast.parse(S.H3_SOURCE_PATH.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MiniMaxH3Pipeline')
    call = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__call__')
    params = {n.arg for n in call.args.args + call.args.kwonlyargs}
    required = {'keyframes', 'keyframe_indices', 'retake_audio', 'retake_audio_sample_rate', 'seconds_regions_to_retake'}
    if not required <= params:
        raise RuntimeError(f'当前仓库H3源码缺少参数：{required - params}')
    names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    if 'MiniMaxH3Unit_AudioRetakeEmbedder' not in names:
        raise RuntimeError('当前源码缺少音频保留处理单元')
    return params


def main(argv=None, project=True):
    check_source()
    plan = load_plan() if project else None
    print(f'代码目录：{S.PROJECT_ROOT}')
    print(f'H3源码：{S.H3_SOURCE_PATH}；所需接口静态检查通过')
    print(f'Python：{sys.executable}；TTS环境：{S.TTS_PYTHON}；H3环境：{S.H3_PYTHON}')
    if project:
        print(f'输出目录：{S.OUTPUT_PATH}')
    for name, path in [('Base', S.TTS_MODEL_PATH), ('首段CustomVoice', S.BOOTSTRAP_MODEL_PATH), ('H3', S.H3_MODEL_PATH)]:
        print(f'{name}：{path}；存在={path.exists()}')
    for name in ['ffmpeg', 'ffprobe']:
        print(f'{name}：{shutil.which(name) or "未找到"}')
    if plan is None:
        print('未指定项目；仅检查部署环境。')
        return
    count = 0
    for shot in plan['shots']:
        try:
            _, meta, frames = prepared_audio(shot)
            print(f'配音{shot["id"]:02d}有效：{meta["speech_seconds"]:.3f}秒；视频{frames/S.FPS:.3f}秒')
            count += 1
        except (FileNotFoundError, RuntimeError, ValueError) as error:
            print(f'配音{shot["id"]:02d}尚未就绪：{error}')
    print(f'有效配音：{count}/{len(plan["shots"])}；以上不代表GPU推理或口型已通过。')


if __name__ == '__main__':
    main()
