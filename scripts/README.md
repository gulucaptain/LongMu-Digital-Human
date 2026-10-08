# 规划剧本库

每份剧本按独立项目子目录保存，目录名与project_id一致。目录内保留可读剧本、project.json、planning.json、素材、TTS文本、提示词审核预览和运行说明；模型部署参数使用服务器已有runtime.toml，生成内容放各项目runs目录。

| 项目 | 内容 | 状态 |
| --- | --- | --- |
| [dry-eye](dry-eye/剧本.txt) | 干眼与视疲劳教育讲解 | 原示例迁入；共用主素材库 |
| [eye-drops-education-v1](eye-drops-education-v1/剧本.txt) | 滴眼药水：医生讲解与准备步骤示意 | 已校验输入；未运行模型；精细滴药素材待修正 |
| [dry-eye-nutrition-ep04-v1](dry-eye-nutrition-ep04-v1/原稿与执行台词.txt) | 第4集干眼饮食与鱼油：6段讲解版及6段交互旁白草案 | 讲解版已校验；交互版待3张首帧；参考音频逐字文字待补；未运行模型 |

在仓库根目录运行：

```bash
bash scripts/eye-drops-education-v1/run_pipeline.sh /实际路径/runtime.toml
```

后续新增剧本使用独立子目录，并在此索引登记，避免覆盖已有项目。
