# Literature Micro-Visual V3.0
## 第三个 BAT：文献微观视觉短片

**版本：** V3.0  
**状态：** FROZEN — 冻结需求基线  
**项目目录：** `E:\Agent\WeChat\Video`  
**BAT：** `Run_Literature_Micro_Visual.bat`  
**CLI：** `run-literature-micro-visual`

本规格用于交给 OpenCode / Antigravity 开发。冻结的是产品定义、工作流边界、质量门禁和验收标准。Phase 0 仍须通过只读勘查验证实际环境能力，不能将计划中的能力误认为已经在本机验证。

---

# 1. 产品定位

从已经完成的文献总结中选择一句具有视觉表现力的原句，通过 Google Flow 生成一个连续的 15 秒微观视觉场景。

视频不承担论文讲解任务。

**最终呈现：一个微观画面、一句原文、一段纯音乐。**

不讲机理，不讲逻辑，不使用 TTS，不使用旁白，不制作多幕 PPT，不制作图表，不解释科学结论。

三个生产任务保持独立：

| 任务 | 产品定位 |
|---|---|
| 科普视频 BAT | 解释一个科学知识 |
| 文献精读视频 BAT | 讲解一篇论文 |
| 文献微观视觉 BAT | 将论文中的一个微观现象转化为 15 秒视觉影像 |

## 1.1 最终视频规格

- 时长：15.000 秒。
- 比例：9:16。
- 分辨率：1080 × 1920。
- 帧率：30 fps，最终 450 帧。
- 视频编码：H.264。
- 音频编码：AAC。
- 音轨：只保留一条纯器乐背景音乐。
- 文字：只显示一句从已有文献总结中选择的原句。
- 镜头：一个连续、连贯的微观场景。
- 不出现旁白、对白、歌词、吟唱、人声采样。
- 不出现额外标题、标签、解释、公式、Logo 或图表。

## 1.2 核心审美标准

目标不是廉价的 3D 科学课件，而是具有高级科学纪录片质感的微观影像。

视觉重点：
- 物质的空间关系；
- 液体、颗粒、液滴、薄膜和表面；
- 界面接触、铺展、聚集和变化；
- 微妙运动；
- 光线、景深、质感和空间层次。

允许摄影艺术化，但不允许虚构具体科学结构。

---

# 2. 工程隔离与复用原则

必须在现有 WeChat_Video 项目内独立开发。

优先复用：
- 现有 Python 环境；
- CLI 框架；
- 配置管理；
- 任务锁；
- 日志系统；
- 视频处理工具；
- FFmpeg；
- 文章摘要和证据验证组件。

禁止：
- 重构前两个 BAT；
- 修改前两个任务的生产逻辑；
- 修改 WeChat_control；
- 修改已有文章的去重状态；
- 删除任何历史生产输出；
- 将第三个任务的失败传递为前两个任务的失败。

第三个任务使用独立 CLI、独立台账、独立状态和独立输出目录。

---

# 3. 浏览器自动化：独立 Edge Flow Profile + CDP

## 3.1 禁止占用日常 Edge

不得直接使用日常 Edge 默认 User Data 目录进行自动化连接。

不得复制日常浏览器 Profile 来迁移 Cookie 或登录状态。

不得强行结束用户正常使用的 Edge 进程。

## 3.2 专用 Profile

建立：

    runtime/browser/Edge_Flow_Profile/

通过独立 Edge 实例启动：
- 使用单独的 --user-data-dir；
- 启用本地远程调试端口；
- CDP 仅绑定 127.0.0.1；
- Browser Controller 使用 CDP 连接；
- 该 Profile 仅用于 Google Flow；
- 同一时间仅允许一个自动化任务占用。

首次需要用户手动登录 Google Flow。

后续复用这个专用 Profile，不干扰日常 Edge。

若现有项目已有可靠的 Edge/CDP 管理模块，优先复用；但不能绕过 Profile 锁和所有权管理。

## 3.3 浏览器资源锁

运行时检查：
- Profile 是否存在；
- Edge 进程是否正常；
- CDP 端口是否可用；
- Profile 是否被另一个任务占用。

禁止自动结束其他用户进程。

若资源被占用或无法恢复，返回：

    BLOCKED_BROWSER_PROFILE

停止本次任务，保留日志和现场信息。

---

# 4. Google Flow 下载路径隔离

网页下载不能使用系统全局 Downloads 目录作为自动化输入来源。

每次运行建立独立临时下载目录，例如：

    runtime/downloads/micro_visual/<job_id>/

Browser Controller 在启动任务时必须配置 CDP 下载行为，优先通过支持的 Browser CDP 下载接口设置：
- downloadPath；
- 下载允许策略；
- 下载事件监听。

在当前 Edge CDP 版本不支持时，检查是否支持 Page.setDownloadBehavior；只有获得成功确认后才能继续。

不要假设命令调用成功就代表下载路径生效。

必须验证：
- 下载事件属于当前任务；
- 下载目标位于当前任务目录；
- 文件已经完成下载；
- 文件大小稳定；
- MP4 可以正常解析；
- 文件不是上一次运行残留。

禁止通过扫描系统 Downloads 目录、按最近修改时间或随机文件名抓取视频。

下载完成后将原始视频移动或复制到当前独立输出目录，并记录 SHA-256。

下载路径异常返回：

    BLOCKED_FLOW_DOWNLOAD

---

# 5. 输入：只读取已有文献总结

本 BAT 不负责重新选文、重新阅读论文或重新生成摘要。

读取现有 Article Summary 输出及其已验证证据记录。

## 5.1 合格输入条件

- 摘要生产任务已经完成；
- 原有内容 QA 为 PASS；
- source_article_sha256_matched=true；
- SHA 与 manifest 相匹配；
- claims 与 source_excerpt 可追溯；
- 文章尚未使用微观视觉任务生成视频。

实际字段以本地真实输出为准，不允许假设所有历史输出都具有完全相同的 Schema。

## 5.2 允许读取的信息

- article_id
- source_article_sha256
- summary_title
- core_thesis
- claims
- speech_units
- claim_ids
- source_excerpt
- 已存在的期刊、文章标题、年份等 metadata

## 5.3 禁止事项

- 不调用 Planner 重新总结文章；
- 不读取原论文 PDF 或 SI 补充信息；
- 不修改既有摘要；
- 不修改 Article Summary manifest；
- 不改变已有文章去重机制；
- 不把微观视觉的使用记录写入其他任务台账。

没有合格摘要时：

    SKIPPED_NO_ELIGIBLE_SUMMARY

---

# 6. 原句选择：12–28 汉字硬门槛

## 6.1 选择目标

从已有文献总结中选出一句具有视觉表现力的完整原句。

优先检查 speech_units.spoken_text 和其他已有摘要正文。

不得改写原句。

## 6.2 硬性长度条件

去除首尾空白后：
- 汉字数量必须在 12–28 之间；
- 标点、空格不计入汉字数量；
- 数字和拉丁字母单独记录，并纳入实际排版计算；
- 不得截断；
- 不得使用省略号制造短句；
- 不得删除原句中的科学限定条件。

长度满足不等于自动入选。还要满足：
- 句意完整；
- 对象明确；
- 能够转化为一个微观场景；
- 不依赖复杂分子或晶体结构。

## 6.3 证据关联

每句必须关联：
- selected_sentence
- claim_ids
- source_excerpt
- article_id
- source_article_sha256

程序验证：
1. 原句确实来自已有总结的允许字段；
2. 关联 claim 存在；
3. source_excerpt 与已记录的原文证据对应；
4. SHA 相匹配；
5. 没有改变原句中的数值、条件和科学结论。

没有合格原句时返回：

    SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE

不能为了完成视频而改写句子。

---

# 7. 科学现象转换为摄影光学语言

分为两个明确阶段。

## 7.1 内部科学理解

Planner 可以分析原句与关联 claim，判断：
- 真实视觉主体；
- 主体之间的空间关系；
- 可以安全表现的动态变化；
- 哪些物理或结构细节有证据支持；
- 哪些内容必须禁止生成。

这一步允许使用科学术语，但不能添加证据不支持的科学事实。

## 7.2 Flow Prompt 转换

最终 flow_prompt.txt 不应直接使用论文术语或复杂科学机理词汇。

避免使用：
- colloidal；
- nanoparticle；
- interfacial tension；
- molecular structure；
- crystal lattice；
- atomic arrangement；
- molecular bonding；
- Brownian motion；
- 特定化学反应路径等学科术语。

必须将科学概念翻译成普通物理对象和摄影描述。

例如：

内部科学场景：

“多个颗粒在液体边界处逐渐聚集。”

摄影化描述：

“许多细小的半透明形态在清澈液体中缓慢漂移，逐渐靠近一条柔和的液体边界。”

最终 Flow Prompt 采用：
- 普通物体描述；
- 材料视觉质感；
- 光线；
- 镜头；
- 景深；
- 运动；
- 摄影语言。

## 7.3 固定构图要求

每条 Flow Prompt 必须加入以下构图指令：

    subject framed in the upper-center with clean, uncluttered negative space in the lower third

要求：
- 主体位于画面中上部；
- 下三分之一保留干净留白；
- 不把主要视觉主体放在底部文字区域；
- 不让次要元素持续占据文字区域。

如果场景本身不适合这一构图，Planner 应判断该原句是否不适合本产品，而不是强行扭曲科学场景。

## 7.4 明确禁止的画面

- 晶格、晶胞和精确晶体结构；
- 球棍模型；
- 精确分子构型；
- 原子排列；
- 电子轨道和化学键；
- 没有原文证据的反应路径；
- 伪造材料特征；
- 论文流程图、公式、数据图表；
- 人物和实验室操作；
- 廉价塑料质感的机械化 3D 小球。

生成定位是艺术化微观纪录影像，不是假冒真实显微数据的模拟。

---

# 8. Google Flow 能力核验与生成策略

## 8.1 Phase 0 真实账号核验

必须使用当前专用 Edge Profile 进入 Google Flow，核实：
- 当前可用模型；
- 是否有 15 秒选项；
- 是否有 9:16 选项；
- 是否支持单次直出；
- 是否支持 Extend；
- Extend 实际可用时长；
- Extend 实际额度消耗；
- 当前可用额度；
- 是否能启用无声视频；
- 导出视频是否自带可见 Flow/Veo 官方角标；
- 官方角标的位置、尺寸、外观是否稳定；
- 最终下载文件是否与界面预览一致。

生成：

    flow_capability_report.json

包含核验日期、模型、时长、比例、额度信息、下载行为及角标情况。

不能从模型名称或宣传材料推断账号拥有某功能。

## 8.2 时长策略

优先级：
1. 单次直出 15 秒；
2. 受控 Extend 延长；
3. 不具备以上条件时停止。

不能自动降级为 10 秒，也不能通过多个短视频拼接冒充一个连续镜头。

### 单次直出

如果账号可以单次生成 15 秒，直接使用。

### Extend 备用路线

如果单次生成不能达到 15 秒，但 Extend 可用，允许使用：
- 首段生成一个连续微观场景；
- 使用同一 Flow 项目 Extend；
- 要求主体、空间、镜头和运动连续；
- 必须评估额外额度；
- 必须在现有授权预算内完成。

不得默认 Extend 免费。

### Extend 原始时长处理

允许 Extend 结果原始时长略超过 15 秒。

初始可接受范围：

    15.000s <= source_duration <= 16.500s

最终统一裁切为：

    15.000s

若原始时长低于 15 秒或超过 16.500 秒，停止并记录，不自动变速或补帧伪造长度。

最终输出统一为 450 帧、30 fps。

## 8.3 Extend 接缝检测

场景切换检测不能直接看到告警就判定失败。

Extend 接缝附近可能发生亮度变化、自然运动、镜头轻微变化和正常画面重新组织。

采用两级判断：

**第一级：候选检测**

使用 FFmpeg scdet 或其他帧差算法查找变化时间点。

**第二级：实质判断**

如果变化发生在 Extend 接缝附近：
- 提取接缝前后关键帧；
- 检查主体是否延续；
- 检查空间环境是否一致；
- 检查是否突然跳到无关场景；
- 必要时送入 VLM 判断。

只有明显跳转为另一个无关场景，才判定连续镜头失败。

自然的明暗变化和运动变化不构成失败。

如果无法确认是否连续，不能自动判为 PASS，需标记 QA 不确定。

## 8.4 无声视频设置

如果 Flow 提供 Return silent videos 设置，优先开启。

但最终仍必须移除原始视频所有音轨。

不能相信 Flow 返回视频一定没有音轨。

## 8.5 额度与重试

- 首轮正式任务只生成一个候选视频；
- 技术失败允许一次针对性重试；
- QA 失败只有能明确定位问题时允许一次修复重试；
- 不允许无限次生成；
- 不允许静默升级订阅；
- 不允许自动支付；
- 不允许切换到未经批准的付费替代服务。

额度不足时返回：

    BLOCKED_FLOW_QUOTA

15 秒能力无法满足时返回：

    BLOCKED_FLOW_15S_UNAVAILABLE

---

# 9. 官方角标与画面文字检查规则

## 9.1 Phase 0 确认官方角标

如果当前 Google Flow 账号导出的视频包含 Flow/Veo 官方可见角标：
1. 保存真实样例截图；
2. 记录角标的具体位置；
3. 记录角标尺寸和外观；
4. 记录其是否在不同视频中保持稳定；
5. 将其登记为当前账号的官方角标白名单。

白名单记录保存在：

    config/micro_visual/official_watermark_allowlist.json

应记录：
- 平台；
- 角标类型；
- 允许的画面区域；
- 已验证样例；
- 验证日期；
- 适用账号或模型条件。

## 9.2 视觉审核边界

如果确认官方角标位于固定角落位置：
- VLM 可以放行该特定官方角标；
- 不得对它进行裁切、遮挡或修图；
- 保留官方原始标识；
- 仅限白名单明确确认的角标样式和位置。

任何以下情况仍然判定失败：
- 画面中央的乱码文字；
- 未知水印；
- 额外 Logo；
- 生成出来的标签或公式；
- 非白名单位置的文字；
- 其他生成模型附加的明显标记。

如果官方角标没有经过 Phase 0 确认，不能自动放行。

官方角标白名单不能变成通用水印豁免。

---

# 10. 文字排版与渐变遮罩：Python Pillow 透明图层

禁止使用 FFmpeg drawtext 直接排版中文原句。

原因：
- Windows 命令行转义问题；
- 中文字体路径问题；
- 全角标点、百分号和引号容易触发滤镜解析错误；
- 原生 drawtext 缺少适合本项目的精细自动排版控制。

## 10.1 Pillow 渲染

使用 Python Pillow 生成：

    text_overlay.png

规格：
- 图层大小：1080 × 1920；
- RGBA；
- 背景透明；
- 内含底部渐变遮罩；
- 内含选中的原句；
- 不包含其他文字。

优先使用系统中已安装且支持中文的字体。

不能假设所有 Windows 系统存在同一字体路径。

如果没有可用中文字体，返回：

    BLOCKED_CJK_FONT

不能退化为乱码方框或截图拼接。

## 10.2 排版计算

使用 Pillow textbbox 或等效文字宽度计算，按真实像素宽度自动换行。

要求：
- 允许最多两行；
- 不删除字符；
- 不改写标点；
- 不拆散不可断开的拉丁单词和数字；
- 保留中英文混排；
- 计算最终文字块的实际宽高；
- 检查安全边距。

文字初始字号参考 48–60 px，根据实际宽度进行小范围调整。

必须保证观众在手机屏幕上清晰可读。

如果超过两行，或必须将字号降到不可读才能容纳，返回：

    SKIPPED_TEXT_LAYOUT_UNFIT

不能裁切原句。

## 10.3 Gradient Scrim

在文字区域叠加柔和渐变遮罩：
- 初始透明度 15%–25%；
- 覆盖底部文字所在区域；
- 采用渐变，不使用明显的黑色矩形；
- 不遮挡主要视觉主体；
- 文字采用高对比度字体并配轻微阴影。

使用程序计算文字与预估背景的对比度。

若画面亮度变化导致可读性下降，优先调整遮罩强度和文字阴影，不无限缩小字号。

## 10.4 文字出现时间

| 时间 | 画面 |
|---|---|
| 0.0–1.5 秒 | 纯视觉开场 |
| 1.5–2.0 秒 | 原句淡入 |
| 2.0–13.5 秒 | 原句稳定显示 |
| 13.5–14.5 秒 | 原句淡出 |
| 14.5–15.0 秒 | 纯视觉结束 |

Pillow 生成静态 PNG 图层。FFmpeg 使用 alpha fade 和 overlay 完成动态叠加。

---

# 11. 背景音乐管理

只使用经过核实授权的纯器乐音乐素材。

每首音乐必须登记：
- 文件路径；
- SHA-256；
- 来源；
- 许可证或授权信息；
- instrumental_only=true；
- 人工确认记录；
- 允许用途。

不使用：
- 歌词；
- 人声；
- 对话；
- 旁白；
- 吟唱；
- 人声采样；
- 不明确是否含有人声的素材。

没有合格音乐时返回：

    BLOCKED_NO_LICENSED_MUSIC

不允许随意下载未知授权的网络音乐。

## 11.1 音乐混合

- 0.0–0.8 秒淡入；
- 0.8–14.0 秒平稳播放；
- 14.0–15.0 秒淡出；
- 全片只有这一条音轨；
- 音乐覆盖整个视频。

即使 Flow 已返回无声视频，仍必须检查最终 MP4 的音轨数量。

---

# 12. 最终视频合成

统一使用 Python 管理素材、FFmpeg 完成视频与音频处理。

处理顺序：
1. 下载 Flow 原始 MP4 到当前任务专用目录；
2. 检查文件完整性；
3. 读取真实视频信息；
4. 移除所有原始音轨；
5. 转为标准 9:16 格式；
6. 检查和处理分辨率；
7. 如果 Extend 原始视频略长，裁切前 15.000 秒；
8. 按 30 fps 输出 450 帧；
9. 使用 Pillow 生成透明文字与渐变图层；
10. FFmpeg overlay 叠加图层；
11. 执行文字 alpha fade；
12. 混入唯一一段已批准的纯器乐音乐；
13. 编码 H.264 + AAC；
14. 输出 final.mp4；
15. 计算最终 SHA-256。

最终 MP4 必须可独立播放，不依赖外部图片或音频素材。

---

# 13. QA：确定性技术检查 + VLM 视觉审核

不得将程序无法检查的画面属性写成自动 PASS。

## 13.1 技术 QA

使用 FFmpeg 检查全片：
- 文件完整性；
- 15.000 秒；
- 1080 × 1920；
- 30 fps；
- 450 帧；
- H.264；
- AAC；
- 只有一个音轨；
- 无黑帧；
- 无长时间异常静止；
- 无严重模糊或破损；
- 音乐完整覆盖；
- 无 Flow 原音轨残留。

场景变化检测采用候选检测 + 实质判断，不允许将轻微亮度或正常运动变化直接当成多镜头失败。

## 13.2 VLM 视觉 QA

从 Flow 原始视频抽取：
- 0 秒；
- 3 秒；
- 7 秒；
- 11 秒；
- 14 秒。

生成带时间戳的五帧宫格图。

针对 Extend 结果，额外检查接缝前后画面。

调用具备真实图像输入能力的视觉模型。

输出结构化 JSON：

    {
      "has_unapproved_text": false,
      "has_unapproved_watermark": false,
      "official_corner_badge_allowed": true,
      "has_ball_and_stick_molecule": false,
      "has_crystal_lattice_or_atomic_structure": false,
      "has_multiple_unrelated_scenes": false,
      "has_people_or_talking_subjects": false,
      "is_blurry_or_corrupted": false,
      "is_one_coherent_micro_visual_scene": true,
      "visual_quality_pass": true,
      "findings": []
    }

VLM 规则：
- has_unapproved_watermark 必须结合当前白名单判断；
- 官方角标只放行已经确认的精确区域和样式；
- 不允许放行其他文字或 Logo；
- 不允许只根据 Prompt 推测视频内容；
- 必须检查真实关键帧；
- 字段缺失、解析错误、模型无法识别或判断不确定时不得 PASS。

如果没有可调用的合格 VLM，返回：

    BLOCKED_VISUAL_QA_UNAVAILABLE

不允许跳过 VLM 后报告内容 QA PASS。

## 13.3 文字 QA

验证：
- 原句逐字一致；
- 没有字符丢失；
- 没有乱码；
- 没有超出安全区；
- 不超过两行；
- 文字时间窗口符合要求；
- 文字在全片明暗变化下可读；
- 没有 Flow 另外生成的文字。

## 13.4 音频 QA

验证：
- 只有一条音轨；
- 唯一音轨与批准的音乐素材一致；
- Flow 原始音频不存在；
- 无人声、对白、歌词和人声采样；
- 音乐全程覆盖；
- 淡入淡出正确；
- 没有爆音或明显失真。

音乐素材已经过许可和人工确认，自动音频检测只作为附加检查，不能替代素材审核。

## 13.5 最终 QA 通过条件

必须全部通过：
1. 证据链 QA；
2. 技术 QA；
3. VLM 视觉 QA；
4. 文字 QA；
5. 音频 QA。

任一项失败，最终状态不能是 VIDEO_QA_PASSED。

自动检查通过仍需用户人工验收。

---

# 14. 发布配套文本

额外生成：

    post_caption_and_comment.txt

文件不进入视频画面。

## 视频正文

包含：
- 一句通俗的现象揭秘；
- 论文中文标题；
- 期刊名称；
- 发表年份。

## 置顶评论

包含：
- 微观画面对应的现象补充；
- 论文来源；
- 引导观众了解原论文的自然表达。

只能从已经存在的摘要和 metadata 读取信息。

缺失字段必须标注，不得编造，不得重新查询原文补齐。

---

# 15. 独立任务台账与状态

使用：

    runtime/micro_visual_jobs.jsonl

不改变任何其他任务的去重状态。

每篇合格文献总结初期最多生产一条微观视觉视频。

每个 Job 记录：
- job_id
- article_id
- source_article_sha256
- selected_sentence
- selected_sentence_sha256
- claim_ids
- flow_model
- flow_duration_mode
- flow_credit_usage
- flow_original_path
- final_video_path
- final_video_sha256
- technical_qa_state
- visual_qa_state
- audio_qa_state
- content_qa_state
- user_acceptance
- created_at

## 15.1 状态定义

| 状态 | 含义 |
|---|---|
| VIDEO_QA_PASSED | 本地视频完成，全部 QA 通过 |
| USER_ACCEPTANCE_PENDING | 等待用户人工验收 |
| SKIPPED_NO_ELIGIBLE_SUMMARY | 没有合格摘要 |
| SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE | 没有适合展示的原句 |
| SKIPPED_TEXT_LAYOUT_UNFIT | 原句无法满足排版要求 |
| BLOCKED_BROWSER_PROFILE | Edge Profile 不可用 |
| BLOCKED_FLOW_DOWNLOAD | 下载隔离或下载校验失败 |
| BLOCKED_FLOW_15S_UNAVAILABLE | 无法在授权条件下生成 15 秒 |
| BLOCKED_FLOW_QUOTA | Flow 额度不足 |
| BLOCKED_CJK_FONT | 没有可用中文字体 |
| BLOCKED_NO_LICENSED_MUSIC | 没有核实授权的纯音乐 |
| BLOCKED_VISUAL_QA_UNAVAILABLE | VLM 视觉 QA 不可用 |
| FAILED | 真实执行硬失败 |

CLI 退出码 0 仅表示没有硬失败，不代表视频成功。

只有 VIDEO_QA_PASSED 并且存在可验证 final.mp4，才算本地视频生产成功。

如未来单独授权微信公众号草稿保存，才增加 DRAFT_SAVED，而且必须存在 verified_draft 才能视为草稿保存成功。

---

# 16. 输出目录

每次生产建立独立目录：

    outputs/<date>_<article_id>_micro_visual/

建议结构：

    outputs/<date>_<article_id>_micro_visual/
    ├── micro_visual_plan.json
    ├── selected_sentence.txt
    ├── source_evidence.json
    ├── flow_prompt.txt
    ├── flow_capability_report.json
    ├── flow_original.mp4
    ├── text_overlay.png
    ├── flow_keyframes/
    │   ├── frame_00.png
    │   ├── frame_03.png
    │   ├── frame_07.png
    │   ├── frame_11.png
    │   ├── frame_14.png
    │   ├── extension_seam_before.png
    │   ├── extension_seam_after.png
    │   └── contact_sheet.png
    ├── visual_qa_report.json
    ├── video_qa_report.json
    ├── content_qa_report.json
    ├── music_source.json
    ├── post_caption_and_comment.txt
    ├── final.mp4
    ├── final_video_sha256.txt
    └── run_result.json

不需要的 Extend 接缝文件可以不生成。

真实生产材料、MP4、Flow 会话、浏览器 Profile、账号数据不得提交 GitHub。

---

# 17. 开发顺序和验收

## Phase 0：只读勘查

不改代码、不生成视频、不消耗 Flow 额度。

检查：
1. 文献总结真实输出结构；
2. QA 和 SHA 记录；
3. 专用 Edge Profile 启动条件；
4. CDP 连接条件；
5. 下载路径隔离能力；
6. Google Flow 当前模型、15 秒直出和 Extend；
7. Flow 账号当前额度及 Extend 实际消耗；
8. Return silent videos 能力；
9. Flow/Veo 官方可见角标是否存在及其固定位置；
10. 本地音乐素材和授权；
11. 中文字体；
12. Pillow 是否可用；
13. FFmpeg 当前处理能力；
14. 免费 OpenCode 模型图像输入能力；
15. VLM 是否可以实际调用和接收图像。

输出：

    docs/LITERATURE_MICRO_VISUAL_PHASE0_REPORT.md

以及：

    flow_capability_report.json

Phase 0 必须给出明确的可行、阻塞和待人工处理项。

不得将尚未验证的能力标记为可用。

## Phase 1：独立链路实现

实现：
- 独立 BAT；
- 独立 CLI；
- 摘要读取；
- 原句选择；
- 字数过滤；
- 证据校验；
- 摄影语言转换；
- Flow Prompt；
- 独立 Edge Profile；
- CDP 下载隔离；
- Flow 控制；
- Pillow 文字与遮罩；
- FFmpeg 后期合成；
- 纯音乐处理；
- VLM 视觉 QA；
- 音频及技术 QA；
- 独立任务台账；
- 发布配套文本。

不修改前两个 BAT。

## Phase 2：一次真实生产实验

仅使用一个合格的已有文献总结。

只生成一个候选视频。

验证：
- 原句选择；
- 画面质量；
- 连续镜头；
- 角标白名单；
- 字幕清晰；
- 音乐无声轨污染；
- 技术 QA；
- VLM QA；
- 最终 MP4；
- 文件 SHA 和记录。

输出本地 final.mp4 交由用户验收。

首条视频不自动保存公众号草稿、不上传、不发布。

一次技术重试或一次有明确原因的质量修复重试为上限。

## Phase 3：用户验收后再扩展

只有用户认可首条视频风格后，才考虑：
- 每日自动选择文献总结；
- 每日最多生成一条；
- 接入统一三任务调度；
- 单独输出第三个任务的运行状态。

每日没有合格摘要、没有适合句子或 Flow 额度不足时，可以正常跳过，不影响前两个任务。

---

# 18. 安全与禁止事项

- 不修改 WeChat_control。
- 不重构前两个生产流程。
- 不修改原文献去重状态。
- 不删除历史输出。
- 不占用日常 Edge 默认 Profile。
- 不读取、复制或导出登录凭证。
- 不自动支付或升级 Flow 套餐。
- 不消耗未经批准的额外额度。
- 不下载授权不明的音乐。
- 不制作无证据支持的分子或晶体结构。
- 不绕过官方角标或水印。
- 不用未执行的 VLM 检查冒充 PASS。
- 不上传公众号。
- 不保存公众号草稿。
- 不发布或调度公众号内容。
- 不把真实文章、生产视频、账号数据、浏览器 Profile 或会话凭证推送 GitHub。
- PR 保持 Open / Draft / Unmerged。

---

# 19. 冻结验收标准

## 内容
- 一句真实原文；
- 12–28 个汉字；
- 完整 claim 和证据关联；
- 没有改写和虚构。

## 画面
- 一个连续微观场景；
- 15 秒；
- 9:16；
- 1080 × 1920；
- 30 fps；
- 摄影纪录片质感；
- 主体偏上，下三分之一留白；
- 不出现不准确的晶体、分子或机理结构；
- 仅允许 Phase 0 确认过的官方角标。

## 文字
- Pillow 透明图层；
- 完整显示原句；
- 最多两行；
- 渐变遮罩；
- 1.5 秒淡入；
- 13.5 秒开始淡出。

## 音频
- 仅一段授权纯器乐；
- 没有人声；
- Flow 原始音轨完全移除。

## 工程
- Edge 独立 Profile；
- CDP 下载路径隔离；
- 单独的任务台账；
- 可追踪 SHA；
- 技术、视觉、文字、音频 QA 全部通过。

## 发布
- 生成本地 MP4；
- 生成正文与置顶评论文本；
- 用户人工验收；
- 未经另外授权不得保存草稿或发布。

---

# 20. 版本冻结声明

V3.0 为当前开发的唯一正式需求基线。

实施时：
1. 不重新讨论已经冻结的产品定位。
2. 不重新加入 TTS、PPT、图表、多幕拼接或论文机理讲解。
3. 不擅自删除任何质量门禁。
4. 不因某个工具能力不足而静默降低输出规格。
5. Phase 0 的实际结果只用于确认实现路径与识别阻塞，不用于擅自改变产品目标。
6. 只有真实环境证据证明某条规则不可行，或真实生产暴露了明确缺陷时，才提交有依据的版本修订。
7. 任何修订必须记录原因、影响范围和测试依据，并获得用户确认后才能改变冻结规格。

**最终产品定义：15 秒，一个微观世界，一个连续镜头，一句原文，一段纯音乐。**
