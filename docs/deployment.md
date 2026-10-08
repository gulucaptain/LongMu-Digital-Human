# 部署说明

1. 使用 Python 3.10+（3.10环境安装tomli），准备 ffmpeg、ffprobe；如烧录中文字幕，准备 libass 和中文字体。
2. 为 TTS 与 H3 建立独立环境，按服务器 CUDA 安装相应 PyTorch。在两套环境分别安装 `.[tts]` 与 `.[h3]`。若复用已有环境，可 `pip install -e . --no-deps` 后补齐缺失依赖。
3. 复制 `configs/runtime.example.toml` 为本机配置，填写模型路径及两套 Python 路径。模型权重不随仓库提供。
4. 在 `scripts/` 中建立独立剧本项目，复制时保持或更新asset_root，修改内容并检查 `longmu plan`、`longmu doctor`。
5. 建立参考声音、生成 TTS，先验证两个镜头，再运行完整流程。保存部署成功时的环境清单、配置快照及模型版本标记。

H3当前需要CUDA；设备选择可通过启动环境中的 `CUDA_VISIBLE_DEVICES` 控制。TTS进程退出后再启动H3，避免两套模型同时常驻显存。不同项目同一GPU上的资源竞争需自行安排。

CLI在Python3.10上仅需tomli，3.11+使用标准库；`plan` 和 `doctor` 不导入 GPU 依赖。`doctor` 为静态诊断，会显示缺失模型和程序，不验证GPU可用性、模型完整性或最终效果。正式发布需在实际服务器完成真实GPU样片验收。

示例项目和文档保存在源码仓库，不打入wheel。安装wheel后提供外部项目JSON、素材与部署配置即可运行。LongMu安装包同时包含本仓库的 `diffsynth`，建议使用隔离环境，避免另一个DiffSynth分发包覆盖同名模块。

单服务器多GPU视频生成：所有配音准备好以后，在video命令后加--gpus 0,1,2。每卡加载一份H3，保持TTS进程先退出。保留原continue_from，无须手工打乱镜头或更改ID。六段营养项目中1→2、3→4为两条续接链，5、6独立，最多四个独立组件可并行；多于四张卡不会增加该计划的并行组件数。失败后查看运行目录parallel中的manifest和worker日志；重新执行相同命令复用有效缓存。真实GPU并行仍需在服务器进行验证。
