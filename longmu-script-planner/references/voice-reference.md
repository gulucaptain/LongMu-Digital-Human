# 参考声音选择与部署

## 选择规则

运行代码与skill采用一致的规则：显式reference_source_audio优先；否则检查仓库assets/longmu/reference_audios/，再检查当前项目ASSET_ROOT/reference_audios/。仅检查目录直接包含的MP3，扩展名不区分大小写。单个MP3自动使用，多个必须明确指定，不按文件名任意挑选。用户指定文件缺失或录音无效时报告错误，不换声音。

有参考录音时，第一镜及后续全部镜头用Base克隆各自shots[].text，不把参考录音当第一镜成品，也不生成CustomVoice。没有参考录音且没有固定声音缓存时，首次用CustomVoice生成第一镜作为固定参考，之后使用Base。

## 可选逐字文字与配置

reference_source_text或录音旁同名.txt必须对应参考录音真实内容，不猜测、不用第一镜台词替代。没有文字时直接启用Qwen的x_vector_only_mode=True，仅提取音色，第一镜仍克隆；可选准确转写通常有助于克隆质量。空的同名.txt会报错，填写真实文字或移除空文件。

配置可明确指定录音（相对路径以部署TOML所在目录为基准）：

```toml
reference_source_audio = "../assets/longmu/reference_audios/reference_audio_1.mp3"
# 可选，必须是真实参考录音文字；没有文字时保持注释。
# reference_source_text = "经核对的参考录音逐字文字"
```

若共用目录只有一个MP3，无需额外配置即可自动选择。服务器同步录音，不能照搬本机绝对路径。不添加project.json不支持的参考音频字段。soundfile不支持MP3解码时运行代码自动用ffmpeg解码，不改录音内容。录音必须至少3秒、有效且非静音。

planning.json记录来源、imported_reference或bootstrap_first_clip、是否使用仅音色模式、可选文字及是否核对，以及运行目录。这些是规划元数据。

## 缓存与执行

导入时保存voice_reference/reference.wav及reference.json，不要求audio/clip_01_tts.wav预先存在。后者是第一镜新生成配音，与参考录音用途不同。speech.py只有origin.mode=bootstrap_first_clip且第一镜文字一致时复用首段；所有外部参考从第一镜起都调用generate_voice_clone。

stage video发现配音文件或元数据缺失时先启动TTS，完成真实时长及缓存验证后再启动单卡或多卡视频。已有但过期/损坏的配音明确报错，不自动覆盖。stage all仍执行TTS再视频。参考录音、文字或克隆模式与已固定声音不同会要求新--output；普通--force不换固定声音。所有阶段使用同一目录。

tts_speaker和tts_instruct只影响首次CustomVoice，不控制Base克隆。生成完成后统一检查发音、音色、口型与整片质量，CPU控制流验证不代表GPU生成质量已验证。
