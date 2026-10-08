from longmu.context import settings as S
from longmu.project import load_plan

def escape_ass(text):
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", r"\N")

def stamp(seconds, ass=False):
    units = round(seconds * (100 if ass else 1000))
    scale = 100 if ass else 1000
    hours, rem = divmod(units, 3600 * scale)
    minutes, rem = divmod(rem, 60 * scale)
    sec, fraction = divmod(rem, scale)
    return f'{hours}:{minutes:02d}:{sec:02d}.{fraction:02d}' if ass else f'{hours:02d}:{minutes:02d}:{sec:02d},{fraction:03d}'


def wrap(text, n=18):
    return '\n'.join(text[i:i+n] for i in range(0, len(text), n))


def captions(ready, folder):
    plan = load_plan()
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 576
PlayResY: 1024
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Speech,Noto Sans CJK SC,29,&H00FFFFFF,&H00FFFFFF,&H00111111,&H99000000,0,0,0,0,100,100,0,0,1,2,0,2,25,25,105,1
Style: Point,Noto Sans CJK SC,27,&H00FFFFFF,&H00FFFFFF,&H00111111,&H99000000,-1,0,0,0,100,100,0,0,1,2,0,8,25,25,50,1
Style: Notice,Noto Sans CJK SC,21,&H00FFFFFF,&H00FFFFFF,&H00111111,&H99000000,0,0,0,0,100,100,0,0,1,2,0,2,25,25,25,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    header = header.replace('PlayResX: 576', f'PlayResX: {S.WIDTH}').replace('PlayResY: 1024', f'PlayResY: {S.HEIGHT}')
    srt, events, cursor = [], [], 0.0
    for i, item in enumerate(ready, 1):
        shot, meta = item['shot'], item['meta']
        end = cursor + meta['frames'] / S.FPS
        voice_start = cursor + S.AUDIO_LEAD_SECONDS
        voice_end = voice_start + meta['speech_seconds']
        words = wrap(shot['text'])
        srt.append(f'{i}\n{stamp(voice_start)} --> {stamp(voice_end)}\n{words}\n')
        body = escape_ass(words)
        events.append(f'Dialogue: 0,{stamp(voice_start, True)},{stamp(voice_end, True)},Speech,,0,0,0,,{body}')
        if S.SHOW_KEYPOINTS and shot['keypoint'].strip():
            point = escape_ass(wrap(shot['keypoint']))
            events.append(f'Dialogue: 0,{stamp(cursor, True)},{stamp(end, True)},Point,,0,0,0,,{point}')
        cursor = end
    if ready and ready[-1]['shot']['id'] == plan['shots'][-1]['id'] and plan.get('notice'):
        notice = escape_ass(plan['notice'])
        events.append(f'Dialogue: 0,{stamp(max(0,cursor-12),True)},{stamp(cursor,True)},Notice,,0,0,0,,{notice}')
    (folder / 'captions.srt').write_text('\n'.join(srt), encoding='utf-8')
    (folder / 'captions.ass').write_text(header + '\n'.join(events) + '\n', encoding='utf-8')


