# LongMu Digital Human｜医疗教育视频

把规划剧本、人物参考图和固定声音转换为教育视频。当前使用 **Qwen3-TTS + MiniMax-H3 FL2VA**，支持单人讲解、统一旁白、简单动作示意、镜头续接、字幕及成片导出。

## 目录

```text
longmu/             产品代码：配音、视频、缓存、拼接、命令入口
scripts/            规划剧本库，每份剧本一个独立项目
assets/longmu/      共用医疗人物与操作参考素材
configs/            服务器部署配置示例
longmu-script-planner/  完整skill：入口、规范、模板与检查工具
diffsynth/          底层推理引擎，完整保留动态加载依赖
tests/              产品单元测试和CPU媒体集成测试
docs/               架构、部署、迁移和整理说明
workspace/          临时工作区，可选；正式剧本维护在scripts
```

其他模型示例、历史实验及非医疗测试媒体已移入`_archive/education_cleanup_20261008/`，文件完整保留。底层引擎源码保持完整；这不表示LongMu提供其他模型的产品入口。保留LICENSE和docs/upstream中的来源说明。

## 环境与安装

Python 3.10+；3.10使用tomli，3.11+使用内置tomllib。推理需要CUDA GPU及匹配的PyTorch；媒体处理需要ffmpeg和ffprobe，字幕需要libass和中文字体。

```bash
python -m pip install -e '.[tts,h3]'
```

已有正常工作的模型环境可安装 `-e . --no-deps`，Python3.10需单独补装tomli。可把TTS、H3放在两套环境，在runtime.toml中分别指定tts_python、h3_python；两套环境均需安装本项目。不要把其他DiffSynth源码放在本仓库前面的模块搜索路径。

```bash
cp configs/runtime.example.toml configs/runtime.toml
```

填写实际Base、CustomVoice、MiniMax-H3权重路径。H3模型目录含FL2VA；TTS实际模型目录含config.json。部署配置不提交，权重和虚拟环境不放仓库。

## 运行滴眼药水项目

在仓库根目录、已配置环境中运行：

```bash
bash scripts/eye-drops-education-v1/run_pipeline.sh configs/runtime.toml
```

顺序：环境检查 → 第一段固定参考声音 → 全部TTS → 真实时长审核 → 逐镜视频 → 自动累计拼接。项目当前是医生讲解搭配洗手和持瓶示意，尚不包含经确认的精细滴药动作演示。

也可以分阶段：

```bash
python -m longmu run --project scripts/eye-drops-education-v1/project.json --config configs/runtime.toml --stage tts
python -m longmu run --project scripts/eye-drops-education-v1/project.json --config configs/runtime.toml --stage video
```

全部配音完成并通过预算审核后，使用`--stage video --gpus 0,1`启用多卡；省略--gpus保持原单卡流程。每卡一个H3进程，按配音帧数分配工作并复用模型；续接链同卡依ID顺序生成，独立链并行。每张卡都需要能容纳当前H3推理，不能把多张卡显存当作一张卡使用。

```bash
python -m longmu run --project scripts/dry-eye-nutrition-ep04-v1/project.json --config configs/runtime.toml --output scripts/dry-eye-nutrition-ep04-v1/runs/reference-audio-1 --stage video --gpus 0,1
```

多卡的分配、镜头ID、依赖、完成状态和拼接顺序保存到运行目录`parallel/manifest.json`；各卡日志为`parallel/worker_*.log`。文件名保持clip_01、clip_02等ID。合成由主进程统一按ID组织，不按生成完成时间排序。累计预览只合成已完成的连续前缀，不跳过未完成的中间镜头。一个worker失败时停止其他worker并保留已生成片段；再次执行仍校验并复用有效缓存。--gpus仅用于all/video阶段，TTS仍先统一生成。GPU编号/UUID使用服务器实际标识；若已设置CUDA_VISIBLE_DEVICES，--gpus必须是其中的原始标识，不是重映射后的0、1。

全部配音完成后，可用`--stage video --shots 1,3,4`先检查代表镜头。去掉--shots生成完整视频。重复命令会校验并复用有效缓存；修改内容后若缓存过期会报错，按提示只重做受影响阶段。不要用all --force修复单个视频问题，它会同时重做配音。

默认输出在项目的`runs/default/`：audio为逐段配音，raw为H3原始片段，aligned为配回TTS且未加字幕的片段，stitched/latest.mp4为累计成片，final/<project_id>.mp4为最终成片。用--output更改目录时，所有阶段和音频审核必须使用同一目录。

## 写稿与素材

剧本索引见[scripts/README.md](scripts/README.md)，skill入口见[SKILL.md](longmu-script-planner/SKILL.md)。新剧本保存到scripts/<project_id>/，包含project.json、planning.json和所需素材，不修改已有项目。

台词放shots[].text，视觉动作放action，scene是characters中的角色键。角色speech_mode为on_camera或voiceover，但全片只有一套声音。每镜必须设置首帧或continue_from之一；尾帧可选，续接使用aligned中的实际末帧。素材路径相对asset_root；asset_root相对项目JSON。

图片中的人物、服装、道具和姿势必须与提示词匹配。精细医疗操作需要准确素材和试生成检查，首尾帧不能保证中间动作正确。干眼示例位于scripts/dry-eye，引用共用assets/longmu；复制该项目到别处时需同步调整asset_root。

```bash
python longmu-script-planner/scripts/prepare_project.py --repo . --project scripts/eye-drops-education-v1/project.json --preview-dir scripts/eye-drops-education-v1/review
```

TTS完成后加--use-audio并指定相同--output，审核真实时长。当前中文约每秒4–5字仅作估算，最终依音频向上对齐为17n+5帧，超预算停止、不截音频。实际生成提示词由make_prompt构造。

## 字幕与限制

burn_subtitles控制字幕烧录；show_keypoints默认false，仅保留底部口播字幕。顶部摘要按需开启，notice为空时不额外加片尾文字。只改字幕可重新执行compose，无需重做模型推理。save_progress_after_each_clip控制累计成片；滴眼药水项目已开启。

当前没有逐角色音色、自动长稿拆段、精细操作自动验收或Web界面。H3使用首帧/首尾帧与retake_audio保留声音，最终音轨配回原始TTS；不保证精确口型和医疗动作正确。

## 验证与文档

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python longmu-script-planner/scripts/test_prepare_project.py
```

CPU测试验证配置、声音缓存、视频请求、原始音轨拼接及末帧续接，不运行GPU模型。整理后的真实GPU推理仍需在服务器验收。

[部署说明](docs/deployment.md) · [架构](docs/architecture.md) · [目录迁移](docs/migration.md) · [整理记录](docs/cleanup.md)

底层引擎来自[DiffSynth-Studio](https://github.com/modelscope/DiffSynth-Studio)，保留原LICENSE。模型与素材的使用条件分别适用。

参考录音自动选择：显式`reference_source_audio`优先，否则自动检查`assets/longmu/reference_audios/`和项目素材目录的`reference_audios/`；单个MP3从第一段起用于Base克隆。无MP3时才首次CustomVoice。`reference_source_text`或同名.txt为可选真实逐字文字，无文字用仅音色模式，不把第一段台词当参考文字。多个MP3须明确选择。

`--stage video`缺少分段TTS时自动先生成配音，验证真实时长后再启动视频；已有但过期的缓存仍报错。更换参考录音或克隆模式使用新的`--output`目录。
