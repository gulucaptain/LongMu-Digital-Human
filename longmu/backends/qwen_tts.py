from pathlib import Path
from longmu.context import settings as S
from longmu.cache import read_json

def resolve_model(root):
    root = Path(root).expanduser()
    if (root / 'config.json').is_file():
        return root
    candidates = [p.parent for p in root.glob('*/config.json')]
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(f'{root}需包含config.json；多个子模型时请指定准确路径。')

def load_model(cls, root, expected):
    import torch
    path = resolve_model(root)
    config = read_json(path / 'config.json')
    kind = config.get('tts_model_type')
    if kind and kind.lower() != expected:
        raise ValueError(f'{path}是{kind}，这里需要{expected}模型')
    return cls.from_pretrained(str(path), device_map=S.TTS_DEVICE, dtype=torch.bfloat16,
                              attn_implementation=S.TTS_ATTENTION, local_files_only=True)
