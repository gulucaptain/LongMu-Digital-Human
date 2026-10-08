# 教育视频仓库整理记录

旧文件完整保留在_archive/education_cleanup_20261008，另外保存了逐文件校验的完整备份。未删除旧代码或媒体。活动目录保留LongMu、TTS/H3后端、规划skill、剧本、医疗素材、配置、CPU测试、许可和完整DiffSynth引擎。

干眼示例移到scripts/dry-eye，六张重复原图经SHA-256核对后改为引用assets/longmu。滴眼药水正式项目在scripts/eye-drops-education-v1，保留自身三张素材副本；没有生成产物的旧workspace副本归档。历史医疗人物和测血压图保留在assets/longmu/legacy_medical_reference。

pyproject只公开tts、h3及合并all依赖组。底层引擎可能通过动态注册和模块映射加载源码，因此本次不裁剪diffsynth。其他底层模型不代表产品支持。服务器模型环境及推理产物未被改变，仍需服务器GPU验收。

恢复旧文件：从本地_archive或备份中按原相对路径取回，先检查目标是否有新的修改，避免直接覆盖整个仓库。

备份：/Users/zhaohaoyu/Documents/Codex/2026-10-08/markdown-minimax-h3-5-10-1/outputs/LongMu_cleanup/LongMu_before_cleanup.zip

校验清单：/Users/zhaohaoyu/Documents/Codex/2026-10-08/markdown-minimax-h3-5-10-1/outputs/LongMu_cleanup/backup_manifest.json
