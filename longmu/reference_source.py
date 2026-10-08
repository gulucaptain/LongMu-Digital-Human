"""选择参考录音与可选逐字文字；不加载模型。"""
from pathlib import Path
from longmu.cache import read_json, sha


def select_reference(config):
    source = config.REFERENCE_SOURCE_AUDIO
    if source is None:
        folders = [config.PROJECT_ROOT/'assets/longmu/reference_audios', config.ASSET_ROOT/'reference_audios']
        for folder in dict.fromkeys(folders):
            candidates = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower()=='.mp3') if folder.is_dir() else []
            if len(candidates)>1:
                raise ValueError(f'{folder}有多条MP3，请用reference_source_audio明确选择。')
            if candidates:
                source = candidates[0]
                break
    if source is None:
        if config.REFERENCE_SOURCE_TEXT:
            raise ValueError('reference_source_text需要对应的参考音频。')
        return None, None
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f'参考音频不存在：{source}')
    text = config.REFERENCE_SOURCE_TEXT
    sidecar = source.with_suffix('.txt')
    if text is None and sidecar.is_file():
        text = sidecar.read_text(encoding='utf-8-sig').strip()
        if not text:
            raise ValueError(f'参考音频文字文件为空：{sidecar}；填写逐字文字或移除空文件使用仅音色模式。')
    return source, text


def validate_pinned_source(config):
    """选择新录音时不悄悄覆盖同一输出目录已经固定的声音。"""
    source = config.REFERENCE_SOURCE_AUDIO
    metadata = config.OUTPUT_PATH/'voice_reference/reference.json'
    if source is None or not metadata.is_file():
        return
    meta = read_json(metadata)
    origin = meta.get('origin', {})
    mode = origin.get('mode')
    text = config.REFERENCE_SOURCE_TEXT
    if (mode not in ('import_first_clip','import_reference') or
            Path(origin.get('source','')).resolve()!=source.resolve() or
            meta.get('text')!=text or
            bool(meta.get('x_vector_only_mode',False))!=(text is None) or
            (origin.get('source_sha256') is not None and origin['source_sha256']!=sha(source))):
        raise RuntimeError('选定参考录音、文字或克隆模式与当前运行目录固定声音不一致；请使用新的--output目录。普通--force不会换声音。')
