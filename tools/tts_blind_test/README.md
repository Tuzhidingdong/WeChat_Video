# 科研中文 TTS 盲听基准（独立测试）

本目录只用于语音引擎盲听，不接入正式视频生产流程，不修改生产默认 TTS。

## 比较候选

- 现有基线：项目当前 sherpa-onnx / VITS MeloTTS zh_en（离线 CPU）。
- 候选一：Edge-TTS，女声 zh-CN-XiaoxiaoNeural。它通过 Microsoft 在线语音服务合成，只用于听感比较；不能仅凭本次试听就认定它适合作为长期生产依赖。
- 候选二：火山引擎 Seed-TTS 3.0，女声「知性女声 3.0」。本轮默认不调用可能计费的 API。只有在用户明确同意本次测试费用，并同时设置 VOLCENGINE_TTS_API_KEY 与 TTS_ALLOW_PAID_TTS_TEST=1 时才运行；单独存在密钥也会跳过。密钥不会写入文件、命令历史或 Git。该候选采用统一的克制科研讲解指令。

CosyVoice 3 不在本轮自动运行：其官方仓库建议独立 Python 3.10 环境和单独模型下载，避免为了盲听污染项目 .venv。若用户希望本地模型路线，再单独制作隔离环境样本。

## 盲听规则

1. 所有候选使用 benchmark_text.json 中完全相同的七段文字，逐段独立合成，以便比较每段的句首是否吞字。
2. 不添加背景音乐、音效、EQ、压缩或降噪；只做统一格式转换和整段响度归一化（约 -20 LUFS，TP 不高于 -2 dBTP）。
3. 每段之间插入相同的 550 ms 数字静音。
4. 随机分配 A/B/C 标签。公开试听目录不含引擎名称；真实映射保存在本地 _internal/answer_key.json，请在用户评分前不要打开。
5. 这是主观盲听比较，不等于完整生产验收。重点听发音、句首完整性、自然度、疑问句、专业词汇和中英混读。

## 本地执行

先同步本测试分支，再确认 tracked 工作区没有修改。测试不会修改源代码以外的项目配置，也不会覆盖已有输出。

项目 .venv 已安装 edge-tts 时可直接运行。若未安装，先检查并确认允许后，只在项目 .venv 安装该可选包；不得把它加入正式项目依赖。Seed-TTS 3.0 需要事先在本机设置 VOLCENGINE_TTS_API_KEY，不可把密钥写入文件、命令历史、日志或 Git。

PowerShell：

    .\.venv\Scripts\python.exe tools\tts_blind_test\run_benchmark.py --output outputs\tts_blind_test_20261123_01

如果输出目录已经存在，程序会拒绝覆盖。脚本只生成音频，不生成视频，也不触碰微信视频号。

## 试听文件

成功运行后，打开：

- outputs\tts_blind_test_20261123_01\listen\A.wav
- outputs\tts_blind_test_20261123_01\listen\B.wav
- outputs\tts_blind_test_20261123_01\listen\C.wav（若 Seed-TTS 3.0 已配置且成功）

同目录有 LISTENING_SCORECARD.md。请先听完并记录 A/B/C 的分数，再打开 _internal\answer_key.json 对照引擎。

## 结果解释

- A/B/C 的声音时长可能不同，这是语速和停顿的真实差异，不做强制变速。
- 统一响度只为减少音量大小对主观判断的干扰，不做音质增强。
- 候选引擎未运行或失败时，会记录为 skipped/failed，不会伪装成完成。
- 任何一个候选的发音错误都应按原文逐字复核；ASR 不作为唯一裁决。
