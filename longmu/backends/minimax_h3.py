"""沿用用户提供脚本的 DiffSynth CUDA 加载逻辑。"""

def stabilize_vision_position_embedding(pipe):
    """Qwen3-VL按pos_embed.weight.device创建索引，须在调用前统一设备。

    只修改该层的onload策略；CPU offload及大模型逐层计算策略仍保留。
    必须在首次pipe推理、load_models_to_device调用前执行。
    """
    encoder = getattr(pipe, 'text_encoder', None)
    model = getattr(encoder, 'model', None)
    visual = getattr(model, 'visual', None)
    position = getattr(visual, 'pos_embed', None)
    if position is None:
        raise RuntimeError('未找到Qwen3-VL visual.pos_embed，无法应用位置嵌入设备兼容修复。')
    if hasattr(position, 'onload_device') and hasattr(position, 'computation_device'):
        # Wrapper的weight.device也会被Transformers用于创建插值权重。
        # 仅在forward里移动索引不够，需提前让weight.device为GPU。
        position.onload_device = position.computation_device
        position.onload_dtype = position.computation_dtype
        position.preparing_device = position.computation_device
        position.preparing_dtype = position.computation_dtype
        # 若权重已被预先加载，先回到offload状态，确保下次onload生效。
        if getattr(position, 'state', 0) != 0:
            position.offload()
        print(f'Qwen3-VL位置嵌入兼容修复：onload={position.onload_device}，offload={position.offload_device}', flush=True)
    else:
        # 无wrapper时只有这一层预先移到流水线设备，不移动整套编码器。
        position.to(device=pipe.device, dtype=pipe.torch_dtype)
        print(f'Qwen3-VL位置嵌入设备：{pipe.device}', flush=True)

def load_pipeline(model_path):
    import torch
    from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Pipeline, ModelConfig

    if not torch.cuda.is_available():
        raise RuntimeError("MiniMax-H3 推理需要可用的 CUDA GPU")
    root = model_path / "FL2VA"
    vram_config = {
        "offload_dtype": torch.bfloat16, "offload_device": "cpu",
        "onload_dtype": torch.bfloat16, "onload_device": "cpu",
        "preparing_dtype": torch.bfloat16, "preparing_device": "cuda",
        "computation_dtype": torch.bfloat16, "computation_device": "cuda",
    }
    configs = []
    for relative_path, pattern in (
        ("text_encoder", "model*.safetensors"),
        ("transformer", "model*.safetensors"),
        ("video_vae/source/model.safetensors", None),
        ("audio_vae/model.safetensors", None),
    ):
        path = root / relative_path
        if pattern:
            paths = sorted(str(file) for file in path.glob(pattern) if file.is_file())
            if not paths:
                raise FileNotFoundError(f"找不到模型权重：{path / pattern}")
        else:
            if not path.is_file():
                raise FileNotFoundError(f"找不到模型权重：{path}")
            paths = str(path)
        configs.append(ModelConfig(path=paths, **vram_config))
    processor_path = root / "processor"
    if not processor_path.is_dir():
        raise FileNotFoundError(f"找不到 processor：{processor_path}")
    pipe = MiniMaxH3Pipeline.from_pretrained(
        torch_dtype=torch.bfloat16,
        device="cuda",
        model_configs=configs,
        processor_config=ModelConfig(path=str(processor_path)),
        vram_limit=max(1, torch.cuda.mem_get_info("cuda")[1] / (1024 ** 3) - 5),
    )


    stabilize_vision_position_embedding(pipe)
    return pipe
