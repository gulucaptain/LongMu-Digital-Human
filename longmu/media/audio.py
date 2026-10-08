import math
from longmu.context import settings as S


def aligned_frames(speech_seconds):
    """保留全部17n+5帧，不裁掉首尾帧模式的目标尾帧。"""
    wanted = max(S.MIN_VIDEO_SECONDS, speech_seconds + S.AUDIO_LEAD_SECONDS + S.AUDIO_TAIL_SECONDS)
    needed = math.ceil(wanted * S.FPS - 1e-8)
    frames = max(5, math.ceil((needed - 5) / 17) * 17 + 5)
    if frames / S.FPS > S.MAX_VIDEO_SECONDS + 1e-8:
        maximum = (math.floor((S.MAX_VIDEO_SECONDS * S.FPS - 5) / 17) * 17 + 5) / S.FPS
        raise ValueError(f'音频{speech_seconds:.2f}秒超出单段预算：当前帧数对齐后视频上限{maximum:.3f}秒。请拆短台词或调整TTS_TEMPO，不会截断语音。')
    return frames
