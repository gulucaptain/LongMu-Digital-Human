"""读取部署配置与项目配置；相对路径分别以各自配置文件所在目录为基准。"""
from dataclasses import dataclass, fields
from pathlib import Path
import json
import os
import sys
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Python 3.10需要tomli解析TOML配置；请在当前环境安装tomli："
            "uv pip install --python /实际环境/bin/python tomli"
        ) from exc

ROOT = Path(__file__).resolve().parent.parent

@dataclass
class RuntimeConfig:
    PROJECT_ROOT: Path = ROOT
    PACKAGE_DIR: Path = ROOT / 'longmu'
    H3_SOURCE_PATH: Path = ROOT / 'diffsynth/pipelines/minimax_h3_audio_video.py'
    PLAN_PATH: Path = ROOT / 'scripts/dry-eye/project.json'
    ASSET_ROOT: Path = ROOT / 'assets/longmu'
    OUTPUT_PATH: Path = ROOT / 'workspace/projects/dry-eye/runs/default'
    TTS_MODEL_PATH: Path = Path('/data/haoyuzhao/models/Qwen3-TTS-Base')
    BOOTSTRAP_MODEL_PATH: Path = Path('/models/Qwen3-TTS-CustomVoice')
    H3_MODEL_PATH: Path = Path('/models/MiniMax-H3')
    REFERENCE_SOURCE_AUDIO: Path | None = None
    REFERENCE_SOURCE_TEXT: str | None = None
    TTS_PYTHON: str = sys.executable
    H3_PYTHON: str = sys.executable
    TTS_SPEAKER: str = 'Serena'
    TTS_LANGUAGE: str = 'Chinese'
    TTS_INSTRUCT: str = '标准普通话，清晰自然的教育讲解，语气亲切，语速适中。'
    TTS_DEVICE: str = 'cuda:0'
    TTS_ATTENTION: str = 'sdpa'
    TTS_SEED: int = 20261008
    TTS_REVISION_TAG: str = 'Qwen3-TTS-12Hz-1.7B-Base-clone-local'
    TTS_TEMPO: float = 1.0
    FPS: int = 24
    MIN_VIDEO_SECONDS: float = 5.0
    MAX_VIDEO_SECONDS: float = 10.0
    AUDIO_LEAD_SECONDS: float = 0.08
    AUDIO_TAIL_SECONDS: float = 0.16
    WIDTH: int = 576
    HEIGHT: int = 1024
    H3_STEPS: int = 50
    H3_SEED: int = 42
    H3_AUDIO_MODE: str = 'retake_preserve'
    H3_REVISION_TAG: str = 'local-FL2VA'
    VIDEO_PROMPT_STYLE: str = 'standard'
    SAVE_PROGRESS_AFTER_EACH_CLIP: bool = False
    BURN_SUBTITLES: bool = True
    SHOW_KEYPOINTS: bool = False

PATH_KEYS = {'TTS_MODEL_PATH', 'BOOTSTRAP_MODEL_PATH', 'H3_MODEL_PATH', 'REFERENCE_SOURCE_AUDIO'}
PROJECT_KEYS = {'TTS_SPEAKER','TTS_LANGUAGE','TTS_INSTRUCT','TTS_TEMPO','WIDTH','HEIGHT','FPS',
                'MIN_VIDEO_SECONDS','MAX_VIDEO_SECONDS','AUDIO_LEAD_SECONDS','AUDIO_TAIL_SECONDS',
                'BURN_SUBTITLES','SHOW_KEYPOINTS','SAVE_PROGRESS_AFTER_EACH_CLIP','VIDEO_PROMPT_STYLE'}
RUNTIME_KEYS = {f.name for f in fields(RuntimeConfig)} - {'PROJECT_ROOT','PACKAGE_DIR','H3_SOURCE_PATH','PLAN_PATH','ASSET_ROOT','OUTPUT_PATH'}

def resolve_path(value, base):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()

def apply_values(config, data, base, allowed):
    for key, value in data.items():
        name = key.upper()
        if name not in allowed:
            raise ValueError(f'未知配置项：{key}')
        if name in PATH_KEYS:
            value = resolve_path(value, base)
        elif name in {'TTS_PYTHON','H3_PYTHON'}:
            # 不解析解释器符号链接，否则会绕过虚拟环境的site-packages。
            interpreter = Path(value).expanduser()
            value = str(interpreter if interpreter.is_absolute() else base / interpreter)
        elif name == 'REFERENCE_SOURCE_TEXT':
            if not isinstance(value,str) or not value.strip():
                raise ValueError('reference_source_text必须是非空文字')
        else:
            original = getattr(config,name)
            if isinstance(original,bool):
                valid = isinstance(value,bool)
            elif isinstance(original,int):
                valid = type(value) is int
            elif isinstance(original,float):
                valid = type(value) in (int,float)
            else:
                valid = isinstance(value,str)
            if not valid:
                raise ValueError(f'配置项{key}类型不正确')
        setattr(config,name,value)

def validate(config):
    import math
    for key in ('TTS_TEMPO','MIN_VIDEO_SECONDS','MAX_VIDEO_SECONDS','AUDIO_LEAD_SECONDS','AUDIO_TAIL_SECONDS'):
        if not math.isfinite(getattr(config,key)):
            raise ValueError(f'{key}必须为有限数值')
    if not 0.5 <= config.TTS_TEMPO <= 2:
        raise ValueError('tts_tempo应在0.5–2.0之间')
    if not 0 < config.MIN_VIDEO_SECONDS <= config.MAX_VIDEO_SECONDS:
        raise ValueError('视频最短/最长时长设置不正确')
    if min(config.AUDIO_LEAD_SECONDS,config.AUDIO_TAIL_SECONDS) < 0:
        raise ValueError('音频首尾留白不能为负')
    if config.FPS != 24 or any(x <= 0 or x % 32 for x in (config.WIDTH,config.HEIGHT)):
        raise ValueError('H3需要24fps，宽高必须为正的32倍数')
    if config.H3_STEPS <= 0:
        raise ValueError('h3_steps必须为正整数')
    if config.VIDEO_PROMPT_STYLE not in ('standard', 'concise'):
        raise ValueError('video_prompt_style需要standard或concise')
    return config

def load_config(project=None, runtime=None, output=None):
    config = RuntimeConfig()
    if runtime:
        path=Path(runtime).expanduser().resolve()
        apply_values(config,tomllib.loads(path.read_text(encoding='utf-8')),path.parent,RUNTIME_KEYS)
    if os.environ.get('MINIMAX_MODEL_PATH'):
        config.H3_MODEL_PATH=Path(os.environ['MINIMAX_MODEL_PATH']).expanduser().resolve()
    if project:
        config.PLAN_PATH=Path(project).expanduser().resolve()
        plan=json.loads(config.PLAN_PATH.read_text(encoding='utf-8'))
        if not isinstance(plan,dict):
            raise ValueError('项目必须为JSON对象')
        project_id=plan.get('project_id')
        import re
        if not isinstance(project_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',project_id):
            raise ValueError('project_id只能包含字母、数字、短横线或下划线，最多64字符')
        config.ASSET_ROOT=resolve_path(plan.get('asset_root','assets'),config.PLAN_PATH.parent)
        config.OUTPUT_PATH=config.PLAN_PATH.parent/'runs/default'
        apply_values(config,plan.get('settings',{}),config.PLAN_PATH.parent,PROJECT_KEYS)
    if output:
        config.OUTPUT_PATH=Path(output).expanduser().resolve()
    return validate(config)

def snapshot(config):
    return {f.name:str(value) if isinstance(value,Path) else value for f in fields(config)
            for value in [getattr(config,f.name)]}

def from_snapshot(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    for key in PATH_KEYS | {'PROJECT_ROOT','PACKAGE_DIR','H3_SOURCE_PATH','PLAN_PATH','ASSET_ROOT','OUTPUT_PATH'}:
        if data.get(key) is not None:
            data[key]=Path(data[key])
    return validate(RuntimeConfig(**data))
