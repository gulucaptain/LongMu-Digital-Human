from longmu.context import settings as S
from longmu.cache import read_json


SHOT_TYPES = {'talking_head', 'simple_action', 'speaking_action'}


def shot_type(shot, character):
    return shot.get('shot_type', 'talking_head' if character['speech_mode'] == 'on_camera' else 'simple_action')


def reject_unknown(data, allowed, label):
    unknown = data.keys() - allowed
    if unknown:
        raise ValueError(f'{label}包含未支持字段：{sorted(unknown)}；规划元数据请放planning.json')


def load_plan():
    plan = read_json(S.PLAN_PATH)
    from pathlib import Path
    if not isinstance(plan, dict) or plan.get('schema_version') != 1:
        raise ValueError('项目需要schema_version=1')
    reject_unknown(plan, {'schema_version','project_id','title','asset_root','characters','shots','settings','notice','visual_constraints','episode','notes'}, '项目')
    shots = plan.get('shots')
    characters = plan.get('characters')
    if not isinstance(shots, list) or not shots:
        raise ValueError('shots必须是非空数组')
    if not isinstance(characters, dict) or not characters:
        raise ValueError('characters必须定义角色')
    for name, character in characters.items():
        if not isinstance(character, dict) or not isinstance(character.get('description'), str) or not character['description'].strip():
            raise ValueError(f'角色{name}缺少description')
        reject_unknown(character, {'description','speech_mode'}, f'角色{name}')
        if character.get('speech_mode') not in ('on_camera', 'voiceover'):
            raise ValueError(f'角色{name}的speech_mode需要on_camera或voiceover')
    for shot in shots:
        if not isinstance(shot, dict):
            raise ValueError('每个镜头必须为对象')
        required={'id','text','scene','first_image','last_image','continue_from','action','keypoint'}
        reject_unknown(shot, required | {'shot_type', 'title'}, f'镜头{shot.get("id", "?")}')
        if required - shot.keys():
            raise ValueError(f'镜头缺少字段：{sorted(required-shot.keys())}')
        if type(shot['id']) is not int or shot['id'] <= 0:
            raise ValueError('镜头id必须为正整数')
        for name in ('text','scene','action','keypoint'):
            if not isinstance(shot[name], str):
                raise ValueError(f'镜头{shot["id"]}的{name}必须为文字')
        if shot['scene'] not in characters:
            raise ValueError(f'未知角色：{shot["scene"]}')
        kind = shot_type(shot, characters[shot['scene']])
        if not isinstance(kind, str) or kind not in SHOT_TYPES:
            raise ValueError('shot_type需要talking_head、simple_action或speaking_action')
        if kind == 'speaking_action' and characters[shot['scene']]['speech_mode'] != 'on_camera':
            raise ValueError('speaking_action使用on_camera，由画面人物本人讲解并执行单步动作')
        if kind == 'simple_action' and characters[shot['scene']]['speech_mode'] != 'voiceover':
            raise ValueError('simple_action使用voiceover，避免操作与口播动作约束冲突')
        for name in ('first_image','last_image'):
            if shot[name] is not None and (not isinstance(shot[name], str) or not shot[name].strip()):
                raise ValueError(f'{name}需要非空路径或null')
        if shot['first_image']=='same_as_start':
            raise ValueError('same_as_start只用于last_image')
        if shot['continue_from'] is not None and type(shot['continue_from']) is not int:
            raise ValueError('continue_from必须为整数或null')
        if shot['first_image'] and shot['continue_from'] is not None:
            raise ValueError('first_image与continue_from不能同时设置')
        for name in ('first_image','last_image'):
            value=shot[name]
            if value and value!='same_as_start':
                path=Path(value)
                if path.is_absolute() or not (S.ASSET_ROOT/path).resolve().is_relative_to(S.ASSET_ROOT.resolve()):
                    raise ValueError('图片路径必须位于项目asset_root内')
    if not isinstance(plan.get('notice',''),str) or not isinstance(plan.get('visual_constraints',''),str):
        raise ValueError('notice和visual_constraints必须为文字')
    ids = [s['id'] for s in plan['shots']]
    if ids != list(range(1, len(ids) + 1)):
        raise ValueError('镜头id必须从1开始连续递增')
    for shot in plan['shots']:
        if not shot['text'].strip():
            raise ValueError('台词不能为空')
        prev = shot['continue_from']
        if prev is not None and (prev not in ids or prev >= shot['id']):
            raise ValueError('continue_from必须指向前面的镜头')
        if prev is not None and plan['shots'][prev-1]['scene'] != shot['scene']:
            raise ValueError('续接必须沿用同一scene角色；换人物请使用独立首帧')
        for key in ('first_image', 'last_image'):
            value = shot[key]
            if value and value != 'same_as_start' and not (S.ASSET_ROOT / value).is_file():
                raise FileNotFoundError(value)
        if not shot['first_image'] and prev is None:
            raise ValueError('每镜必须指定首帧或续接来源')
    if S.FPS != 24:
        raise ValueError('本H3实现使用24fps')
    if any(x <= 0 or x % 32 for x in (S.WIDTH, S.HEIGHT)):
        raise ValueError('WIDTH/HEIGHT必须为正的32倍数')
    return plan
