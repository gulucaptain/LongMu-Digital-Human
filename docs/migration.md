# 目录迁移说明

当前以 `longmu` 为产品入口，视频后端仅使用 MiniMax-H3，声音后端使用 Qwen3-TTS。

| 整理前 | 整理后 |
| --- | --- |
| examples/longmu/dry_eye/project.json | scripts/dry-eye/project.json |
| examples/longmu/dry_eye/assets/reference_images | assets/longmu/reference_images（相同文件共用，已校验哈希） |
| workspace/projects/eye-drops-education-v1 | scripts/eye-drops-education-v1（后者是维护版本；旧副本归档） |
| assets/minimax_h3/images中的医疗人物和测血压素材 | assets/longmu/legacy_medical_reference |
| 其他模型examples、旧experiments、上游en/zh教程、车辆游戏媒体 | _archive/education_cleanup_20261008，另有完整备份 |

`assets/longmu/reference_images`与滴眼药水项目的路径保持不变。已经同步服务器的旧版项目不会被本地整理自动修改；迁移干眼项目时同步新project.json和共享素材库。旧版命令改用`python -m longmu`。

旧配音仍可通过 `--stage import-audio --source /旧目录 --output /新目录`导入；导入校验模型、声音参考、台词和设置，不能把归档的旧实验视频当作当前缓存。

恢复旧文件：从整理前备份解压到独立目录，取回需要的文件；不要直接覆盖当前仓库。备份位置和逐文件清单见整理报告。
