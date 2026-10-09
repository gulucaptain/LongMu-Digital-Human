# 当前代码契约

基线：LongMu v0.1.0，2026-10-08；代码改变时重新核对。

| 用户信息 | JSON字段 | 消费方式 |
| --- | --- | --- |
| 名称与标识 | title / project_id | id命名成片，字母数字/短横线/下划线，首字符字母数字，最多64字符 |
| 角色外观 | characters.<key>.description | 据图填写，进入视觉提示词 |
| 口播/旁白 | characters.<key>.speech_mode | on_camera / voiceover，角色级别，仍共用项目声音 |
| 台词 | shots[].text | 实际TTS及声音提示 |
| 当前角色 | shots[].scene | characters的键，不是地点 |
| 镜头类型 | shots[].shot_type | talking_head / simple_action / speaking_action；simple_action需voiceover，speaking_action需on_camera；省略按speech_mode推导 |
| 主动作 | shots[].action | 进入视觉提示，推荐简明英文 |
| 字幕要点 | shots[].keypoint | 后期叠加，不控制模型 |
| 首帧 | shots[].first_image | 相对asset_root，与continue_from二选一 |
| 续接来源 | shots[].continue_from | 小于本镜id的镜头，使用实际末帧 |
| 尾帧 | shots[].last_image | 素材路径、same_as_start或null |
| 全局约束 | visual_constraints | 每段视觉约束，不得与action冲突 |
| 片尾提示 | notice | 后期文字 |

schema_version=1；project_id、characters、非空shots必填。每镜包含id、text、scene、action、keypoint、first_image、last_image、continue_from，id从1连续递增，text非空。asset_root建议显式为assets；图片真实存在、路径相对于素材目录且不能越界。顶层、角色、镜头未知字段均报错；兼容旧项目episode/notes以及镜头title仅作说明，不参与生成。规划信息放planning.json。续接源必须与本镜scene相同，图片中的身份仍须人工核对。

内容settings白名单见longmu/config.py:PROJECT_KEYS：尺寸、fps、时长预算、首尾静音、字幕和进度开关、语言、首段声音指令、语速及video_prompt_style等。video_prompt_style支持standard和concise；代码默认为standard保持兼容，skill新项目显式选择concise。concise没有数字时长或制作说明，长度仍由num_frames和音频条件控制。模型路径、参考音频/文字、Python环境、种子、步数和版本标记在TOML。未知settings项会报错。逐角色声音、scene_id、强制duration、chapter、原始video_prompt和逐词字幕不是当前接口。

声音选择由skill先检查`assets/longmu/reference_audios/`：有MP3时优先指定参考录音，从第一镜开始使用Base克隆；无MP3才首次CustomVoice建立固定参考。完整选择、文字和部署步骤见[参考声音规则](voice-reference.md)。当前代码优先消费TOML显式参考，否则自动扫描共用目录及项目参考目录；文字可选，无文字用仅音色模式；导入会固定为运行目录内的WAV，Base后续复用同一个voice_clone_prompt。tts_speaker/tts_instruct只控制初次CustomVoice，不能控制Base每段。force保留固定声音；换声音用新运行目录。

speech.py首段复用分支仅限origin.mode=bootstrap_first_clip；外部录音即使文字与第一镜相同也重新克隆。没有外部参考文字时传ref_text=None及x_vector_only_mode=True，不用第一镜文字冒充。video阶段自动补齐缺失配音后校验，再启动GPU视频任务；过期缓存仍明确报错。

24fps、尺寸32倍数；帧数17n+5向上对齐。默认5–10秒实际为124/141/158/175/192/209/226帧，5.167至9.417秒，默认首尾静音0.24秒，配音上限约9.177秒。真实预算调用longmu.media.audio.aligned_frames，不按字数确定最终帧数。speech_seconds为TTS文件时长，包含文件内部静音；补齐尾部=frames/fps-audio_lead_seconds-speech_seconds。默认尾部0.16秒不是总尾部留白上限。当前compose保留全部帧，没有自动去静音或按剪辑结束帧续接。具体规划见[拼接节奏与首尾帧设计](stitching-and-keyframes.md)。

视频用FL2VA关键帧加retake_audio音频保留模式联合生成：last_image=null传[0]单首帧，指定目标图或same_as_start传[0,-1]首尾双帧；continue_from只决定首帧来源，也可与目标尾帧并用。日志/元数据统一的“首尾帧”标签不能证明用了双帧。再配回TTS。口型并非严格保证；不能为绕过报错改用纯后期配音并声称驱动有效。make_prompt固定机位、无剪切变焦；talking_head保持轻微表演，simple_action执行明确单步已有道具动作，不套用口播手部限制。speaking_action组合人物本人讲话口型与单步道具动作，允许自然视线、表情和肘腕/肩部变化，不套用旁白沉默或talking_head放松双手限制；脸在画面外时不改变构图来制造口型。精细操作仍未自动校验。正文前说明首尾图关系；standard使用时间对应行，concise只说明起始/结束参考，不写秒数；台词在integrated段、保留音频说明在overall_soundscape段。音乐混音和外部实拍插入不是当前compose接口。

```bash
python -m longmu plan --project scripts/my-course/project.json
python -m longmu doctor --project scripts/my-course/project.json --config configs/runtime.toml
python -m longmu run --project scripts/my-course/project.json --config configs/runtime.toml --stage tts
python -m longmu run --project scripts/my-course/project.json --config configs/runtime.toml --stage video --shots 1,2
python -m longmu run --project scripts/my-course/project.json --config configs/runtime.toml --stage video
```

Python>=3.10；3.10需安装tomli，3.11+使用内置tomllib。运行目录默认项目旁runs/default；--output覆盖，所有阶段/审核使用同一目录。筛选镜头仍要求全部配音，续接源必须有效。save_progress_after_each_clip默认false，需要每段预览时开启。all --force连TTS一起重做，不用于只修视频。

维护依据：project.py、config.py、stages/video.py:make_prompt、stages/speech.py、stages/voice_reference.py、media/audio.py、cli.py。

多卡执行：run --stage video（或all）支持--gpus 0,1，指定GPU编号/UUID；不是project.json/settings字段。TTS阶段仍先统一生成。真实音频帧数用于分配负载，同续接组件同卡串行，独立组件并行；主进程按ID合成。parallel/manifest.json记录shot_order、各镜ID、continue_from、GPU、路径与状态。--shots仍只筛选显式镜头，不隐式补生成未选中的依赖；外部续接源必须有有效缓存。每卡独占worker日志/完成记录，保留原clip_XX文件命名和缓存校验。
