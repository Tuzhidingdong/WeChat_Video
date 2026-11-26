# Literature Micro-Visual V3.0.1
## 第三个 BAT：文献微观视觉视频草稿

**版本：** V3.0.1  
**状态：** FROZEN — 当前唯一有效实施规格  
**项目目录：** E:\Agent\WeChat\Video  
**BAT：** Run_Literature_Micro_Visual.bat  
**CLI：** run-literature-micro-visual  
**上位文档：** docs/LITERATURE_MICRO_VISUAL_V3.0.md

> V3.0.1 完整取代 V3.0 作为第三个 BAT 的实施基线。V3.0 保留为历史版本，不删除、不覆盖。两版冲突时以 V3.0.1 为准。

---

# 1. 产品目标：最短生产链路

从已经生成并通过原有内容 QA 的文献总结中，选出一句话和一个微观场景，交给 Google Flow 一次生成 15 秒视频。

Google Flow 在同一次生成中负责：
1. 微观动态画面；
2. 画面中的一句中文原句；
3. 纯器乐背景音乐。

视频生成后直接下载，并使用现有的视频号草稿保存链路保存到草稿箱。

**用户亲自检查草稿中的画面、文字、音乐和整体效果。**

最终流程：

    已有文献总结
        ↓
    选择一句总结原句 + 设计一个微观画面
        ↓
    Google Flow 一次生成：画面 + 文字 + 纯器乐音乐
        ↓
    下载生成的 MP4
        ↓
    保存到视频号草稿箱
        ↓
    回读并确认 verified_draft
        ↓
    等待用户人工检查

不制作 TTS，不制作 PPT，不制作图表，不解释机理，不拼接多幕，不单独生成或混合音乐，不在本地叠加文字。

## 1.1 视频目标

- 时长：15 秒。
- 画幅：9:16 竖屏。
- Flow 生成时选择可用的 1080 × 1920 / 竖屏选项，以当前账号界面实际提供为准。
- 一个连续微观场景。
- 只展示一句中文文字。
- 只配纯器乐背景音乐。
- 无旁白、无对白、无人声、无歌词。
- 不展示额外标题、标签、解释、公式、数据图或机理图。

若当前账号无法直接生成 15 秒竖屏视频，停止并报告，不自动降级为 10 秒，不通过多个视频拼接伪装成一个连续镜头。

## 1.2 产品定位

| 任务 | 目标 |
|---|---|
| 科普视频 BAT | 解释一个科学知识 |
| 文献精读视频 BAT | 讲解一篇论文 |
| 文献微观视觉 BAT | 把论文总结中的一个微观现象转成 15 秒短视频 |

第三个任务只负责生成和保存草稿，不替代前两条生产链路。

---

# 2. 最小化原则

V3.0.1 明确采用最小生产链路。

不新增以下生产组件：
- Pillow 文字渲染；
- 本地文字图层；
- FFmpeg 字幕 overlay；
- 独立音乐素材库；
- 独立音乐生成器；
- 音乐下载和混音；
- VLM 视觉审核；
- 画面 OCR；
- 音频分类或人声检测；
- 视频内容 QA；
- 自动质量重生成；
- 发布正文和置顶评论生成器。

Google Flow 负责一次生成画面、文字和音乐。用户负责检查生成质量。

只允许保留完成任务必需的：
- 摘要读取和证据溯源；
- Flow 浏览器控制；
- 任务级下载隔离；
- 草稿上传；
- 草稿保存回读；
- 运行记录和幂等保护。

---

# 3. 文献总结输入与原句来源

## 3.1 只读取已有文献总结

本 BAT 不重新阅读论文，不重新生成 Article Summary。

扫描现有 Article Summary 输出，读取已经生成的摘要和证据记录。

候选摘要必须满足：
1. 生产任务已经完成；
2. 原有 content_qa_report.json 的内容 QA 状态为 PASS；
3. source_article_sha256_matched=true；
4. manifest 与 summary 的 article_id 一致；
5. manifest 与 summary 的 source_article_sha256 一致；
6. 已有 claims、claim_ids 和 source_excerpt 能够追溯。

不把 upload_eligible=true 作为本任务的独立必要条件。本任务需要的是已经通过原有内容 QA、具有完整来源绑定的文献总结；视频号上传器自己的必要技术或安全条件仍须遵守。

不得因本任务需要而读取原论文 PDF、SI 或其他原始文献补充信息。

不得重新生成摘要或更改原有摘要。

## 3.2 视频中展示的句子来自“文献总结”

用户要展示的是已经生成的文献总结中的一句话，不要求这句话必须是论文原文的逐字引文。

候选句优先来自：
- speech_units[].spoken_text；
- 已有总结正文中的完整句子；
- 其他已经存在、语义完整的总结文本字段。

speech_units[].spoken_text 可以是经过编辑的总结表达。只要它确实来自已通过 QA 的文献总结，就可以作为视频文字。

不得将总结句伪装成论文作者的直接引语。

## 3.3 原句与 claim 的证据关系

所选句子必须能关联到已有 claim：

- selected_sentence：从文献总结中选出的完整句子；
- claim_ids：该句所表达内容对应的已有 claim；
- source_excerpt：这些 claim 已有的原文证据；
- article_id；
- source_article_sha256。

这里的 source_excerpt 用于证明该总结句有文章证据支持，不要求 selected_sentence 本身必须逐字出现在 source_excerpt 或论文原文中。

不得改变句子表达的科学含义、数字、实验条件或限定范围。

若无法建立合理的 sentence → claim → source_excerpt 关联，则跳过该候选，不得编造证据。

## 3.4 句子长度与视觉适用性

优先选择 12–28 个汉字的完整句子：
- 去除首尾空白后计数；
- 汉字数不含标点和空格；
- 数字及拉丁字母单独记录；
- 不截断、不拼接、不改写；
- 不通过省略号缩短句子。

12–28 汉字是候选筛选目标，不得为了满足长度而编辑原句。

优先选择可以直接形成微观画面想象的句子，例如颗粒、液滴、薄膜、表面、孔隙、界面或多相接触的现象。

不选择：
- 纯抽象理论结论；
- 纯因果推理；
- 必须展示精确分子或晶体结构才能理解的内容；
- 不能在一个连续场景中表现的句子。

如果没有合适句子，返回：

    SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE

不重新写句子凑数。

---

# 4. 微观画面设计

Planner 只负责理解已有总结、选择句子并生成 Flow Prompt，不负责生成视频 QA。

## 4.1 画面目标

围绕所选句子设计一个连续的微观场景。

可优先考虑：
- 液滴；
- 颗粒；
- 软质材料；
- 界面；
- 液体中的缓慢运动；
- 薄膜铺展；
- 表面形貌；
- 多相体系的接触和变化；
- 柔性、多孔或非晶材料的视觉质感。

这些只是候选视觉语言，必须服从具体文章内容。

## 4.2 明确避免的内容

避免：
- 晶格和晶胞；
- 精确晶体结构；
- 球棍分子模型；
- 原子排列；
- 精确分子构型；
- 化学键、电子轨道；
- 未经文章证据支持的反应路径；
- 伪造实验数据；
- 机理流程图；
- 数据图表；
- 人物、实验室操作和讲解者；
- 廉价塑料感的机械化 3D 小球。

目标是艺术化微观影像，不是假冒真实显微实验或分子模拟结果。

## 4.3 摄影语言

Planner 可以在内部使用科学术语理解现象，但给 Flow 的 Prompt 应主要使用普通物理对象与摄影语言，例如：
- translucent suspended forms；
- gentle fluid movement；
- dark-field macro photography；
- shallow depth of field；
- delicate light scattering；
- soft organic motion；
- subtle highlights；
- cinematic science-documentary style。

不要把论文的机理术语、化学反应路径或复杂分子结构直接转成模型指令。

## 4.4 固定构图建议

Flow Prompt 应尽量要求：

    subject framed in the upper-center with clean, uncluttered negative space in the lower third

主体偏中上部，画面下方尽量留出文字空间。

这是构图引导，不是额外的后期检查或裁切步骤。

---

# 5. Google Flow：一次生成画面、文字和音乐

## 5.1 Flow 是唯一视频生成工具

使用用户现有 Google Flow 账号。

Phase 0 只读核实：
- 当前账号是否可用；
- 当前可用模型；
- 是否有单次 15 秒生成选项；
- 是否有 9:16 选项；
- 是否支持视频内生成中文文字；
- 是否支持生成背景音乐；
- 是否可以明确要求无声音人声、无对白和无旁白；
- 当前额度及单次生成费用。

不得从模型名称或宣传说明推断账号权限。

如果账号不能在现有额度内生成 15 秒竖屏视频，停止并报告：

    BLOCKED_FLOW_15S_UNAVAILABLE

不自动升级套餐、不支付、不切换未经批准的付费服务。

## 5.2 不使用 Extend

为了保持链路简单，V3.0.1 只采用单次生成。

不使用 Extend，不拼接多段视频，不进行二次生成来补足时长。

如果当前账号不支持单次 15 秒生成，本版本停止并报告能力缺口，由用户决定是否修改规格。

## 5.3 Flow Prompt 必须包含三部分

### A. 视觉画面

明确描述：
- 一个微观主体；
- 一个连续场景；
- 主体之间的关系；
- 自然、缓慢、有美感的运动；
- 光线、景深、材质和摄影风格；
- 不出现机理图、晶体、分子模型或额外视觉文字。

### B. 唯一一句中文文字

将选中的原句原样放入 Prompt：

    On-screen Chinese text (show exactly, do not translate or paraphrase):
    "{selected_sentence}"

要求 Flow：
- 准确显示这句中文；
- 不翻译；
- 不改写；
- 不增加标题或字幕；
- 字体清晰、稳定、易读；
- 将文字放在画面下方留白区域；
- 文字不要遮盖主要视觉主体；
- 不生成其他文字、标签、数字、公式或 Logo。

不使用本地 Pillow、FFmpeg drawtext、字幕轨或其他工具补字。如果 Flow 生成错字，由用户在草稿箱中自行判断，不自动修复。

### C. 纯音乐背景

在同一次 Flow 生成中要求：

    Generate a gentle, elegant, cinematic instrumental background score.
    Instrumental music only.
    No vocals, no singing, no lyrics, no human voice,
    no speech, no dialogue, no narration, no chanting.
    No sound effects and no environmental ambience.
    Keep the music subtle and continuous throughout the video.

Flow 生成的音轨直接随视频使用。

不另建音乐素材库、不下载音乐、不混音、不替换 Flow 音轨、不做音频检测。

## 5.4 生成次数和额度

- 每个 Job 只提交一次 Flow 生成请求。
- 不自动连续重试。
- 提交后如果浏览器断开或结果状态不明，不得再次提交，以免重复消耗额度。
- 必须先确认上一次请求是否已经生成结果。
- 不自动支付、不升级套餐、不切换付费模型。

如果生成失败，记录失败原因并停止，等待用户决定后续操作。

---

# 6. Edge 浏览器与 Flow 自动化

## 6.1 独立 Edge Profile

使用专用目录：

    runtime/browser/Edge_Flow_Profile/

禁止占用日常 Edge 默认 User Data。

启动独立 Edge：
- 独立 --user-data-dir；
- CDP 只绑定 127.0.0.1；
- 专用 Profile 仅用于 Google Flow；
- 同时只允许一个 Flow 任务拥有该 Profile。

首次使用由用户手动登录 Google Flow。

不得复制日常 Profile、提取 Cookie、导出凭证或强制关闭用户日常浏览器。

## 6.2 Profile 锁与所有权

运行前检查：
- Profile 是否被占用；
- Edge 进程是否属于本任务；
- CDP 端口是否可用；
- 当前 Profile 是否为专用 Flow Profile。

复用现有 _validate_existing_session 的进程身份校验模式和项目锁机制，但不得影响已有上传器 Profile。

Flow Profile 和视频号草稿上传器使用的浏览器会话应隔离；两项操作顺序执行，不并行抢占浏览器资源。

无法安全启动或确认所有权时：

    BLOCKED_BROWSER_PROFILE

不得通过结束全部 Edge 进程解决。

## 6.3 Google Flow 网站自动化的范围例外

原冻结 TASK_PLAN.md V5 中关于日常生产不得自动化操作 Google Flow 网站的限制，现由用户明确批准一个极窄的例外：

**只允许新增的 Run_Literature_Micro_Visual.bat 操作 Google Flow 网站，且仅为生成本文定义的文献微观视觉视频。**

该例外：
- 不适用于科普视频 BAT；
- 不适用于文献精读视频 BAT；
- 不允许操作其他 Google 产品；
- 不允许扩展为通用浏览器自动化；
- 不改变 V5 的其他冻结要求；
- 不授权购买额度、修改订阅或访问其他账号内容。

不得改写原 TASK_PLAN.md V5。若需要记录范围例外，应在第三个任务的独立文档或状态记录中注明本节授权。

---

# 7. Flow 下载与文件交接

每次任务使用独立下载目录：

    runtime/downloads/micro_visual/<job_id>/

使用 CDP 下载行为设置或现有 Browser Controller 的等效下载接口，将下载目录绑定到当前 Job。

优先使用当前 Edge/CDP 版本实际支持的下载行为接口；只有确认生效后才能继续。

必须确认：
- 下载事件属于当前 Job；
- 文件落在该 Job 的独立目录；
- 下载已完成；
- 文件大小不再变化；
- 文件路径唯一且不是旧任务残留。

不扫描系统全局 Downloads，不按最近修改时间猜测文件，不抓取随机文件名。

下载完成后：
- 将 MP4 放入本次输出目录；
- 记录文件路径和 SHA-256；
- 原样使用 Flow 生成文件进行上传；
- 不裁剪、不转码、不叠字、不混音、不改画面。

这里的文件完成确认只是防止上传未下载完成或错误文件，不是视频内容或质量 QA。

下载异常时：

    BLOCKED_FLOW_DOWNLOAD

---

# 8. 直接保存到视频号草稿箱

## 8.1 复用现有上传能力

使用项目已有的视频号草稿上传与回读组件，优先复用：
- channels_uploader.py 中现有的浏览器上传流程；
- 已有的草稿保存动作；
- 已有的 verified draft 回读与验证机制；
- 已有的浏览器会话所有权保护。

不得另写一套绕过现有草稿保存安全机制的上传器。

第三任务应先把 Flow MP4 和必要元数据适配成上传器接受的独立输入包。

## 8.2 不伪造视频 QA 结果

第三任务不执行视频内容 QA，因此：
- 不得生成虚假的 content_qa_report.json: PASS；
- 不得伪造 upload_eligible=true；
- 不得伪造文献精读任务的 manifest；
- 不得将 Flow 视频冒充由 Manim/TTS 生产的视频。

如果现有上传器把视频内容 QA 与草稿保存机械绑定，必须先实现仅适用于本任务的窄适配入口：保留上传器必要的文件完整性、账号身份、草稿保存及回读保护，但不伪造视频质量审核结果，不修改前两个任务的上传规则。

若无法在不绕过必要安全保护的前提下完成适配，返回明确阻塞，不能伪造 QA 或直接调用发布接口。

## 8.3 仅允许保存草稿

允许：
- 打开视频号草稿创建页面；
- 填写必要的标题或说明；
- 上传 Flow 生成的原始 MP4；
- 点击保存草稿；
- 回读草稿箱，确认本次记录。

标题和其他必要元数据只能使用已有文献总结中的真实字段，例如 article_title 或 summary_title。不得编造作者、期刊、年份或科学结论。

禁止：
- 发布；
- 发表；
- 定时发布；
- 自动选择发布时间；
- 删除其他草稿；
- 覆盖其他草稿；
- 批量处理其他用户内容。

保存后必须确认：
- 存在本次对应的草稿记录；
- 上传的视频与本次 Job 关联；
- 读回结果可识别；
- 产生 verified_draft。

**只有状态为 DRAFT_SAVED 且存在 verified_draft 才能报告成功。**

BAT 返回码 0 不能替代草稿回读证据。

---

# 9. 不执行生成后的视频质量 QA

这是 V3.0.1 相对 V3.0 最重要的产品简化。

Flow 生成后，系统不再检查：
- 画面是否美观；
- 微观结构是否符合预期；
- 是否出现晶体或分子结构；
- 是否有乱码、错别字或额外文字；
- 中文句子是否逐字准确；
- 是否包含人声或环境音；
- 音乐是否悦耳；
- 视频是否精确达到目标分辨率或帧率；
- 场景是否连续；
- 黑帧、冻结帧、模糊程度；
- VLM 关键帧；
- 音频质量；
- 水印或角标。

不调用 VLM，不做 OCR，不抽帧，不播放视频进行自动审查，不执行 FFmpeg 视频质量检测。

用户本人在草稿箱中检查画面、文字、声音和整体效果。

自动流程只确认下载文件完成、执行草稿保存，并回读验证草稿是否存在。

视频号平台或现有上传器本身强制要求的最低文件接收条件，不属于本任务新增的视频质量 QA；如果平台拒收，记录拒收结果并停止，不得伪造通过。

---

# 10. 独立任务记录、去重与输出

## 10.1 独立任务台账

使用：

    runtime/micro_visual_jobs.jsonl

不得修改：
- Article Summary 的 article_summary_manifest.json；
- 文献精读任务的去重状态；
- 科普任务的 Fact Card 状态；
- 前两个任务的 job journal。

每个 Job 记录：
- job_id；
- article_id；
- source_article_sha256；
- selected_sentence；
- selected_sentence_sha256；
- claim_ids；
- source_excerpt references；
- flow_model；
- flow_duration；
- flow_job_id（如可获得）；
- flow_credit_usage（如界面可获得）；
- flow_prompt；
- downloaded_mp4_path；
- downloaded_mp4_sha256；
- draft_state；
- verified_draft；
- created_at。

台账只用于来源追溯、任务去重和草稿结果确认，不用于视频质量判定。

## 10.2 去重

初期每篇合格文献总结最多提交一次 Flow 生成请求。

建议幂等键：

    (article_id, source_article_sha256, selected_sentence_sha256)

如果同一 Job 已经提交 Flow 请求但结果状态不明，不得自动再次提交。

如果已有成功草稿，不重复生成、不重复上传。

## 10.3 输出目录

每次任务独立保存：

    outputs/<date>_<article_id>_micro_visual/

建议文件：
- micro_visual_plan.json；
- selected_sentence.txt；
- source_evidence.json；
- flow_prompt.txt；
- flow_capability_report.json（Phase 0 产物，可独立保存）；
- flow_original.mp4；
- final.mp4（如原始文件复制为最终交付名，不重新编码）；
- final_video_sha256.txt；
- upload_result.json；
- run_result.json。

不要生成 video_qa_report、visual_qa_report、audio_qa_report 或虚假的 content_qa_report。

真实文章材料、MP4、Flow 会话、浏览器 Profile、账号数据和凭证不得提交 GitHub。

---

# 11. 状态与退出码

状态至少包括：

| 状态 | 含义 |
|---|---|
| DRAFT_SAVED | 草稿保存成功且存在 verified_draft |
| SKIPPED_NO_ELIGIBLE_SUMMARY | 没有通过原摘要 QA 和 SHA 绑定的总结 |
| SKIPPED_NO_VISUALLY_SUITABLE_SENTENCE | 没有合适句子 |
| BLOCKED_FLOW_15S_UNAVAILABLE | Flow 当前账号不能单次生成目标 15 秒竖屏视频 |
| BLOCKED_FLOW_QUOTA | Flow 额度不足 |
| BLOCKED_BROWSER_PROFILE | 专用 Edge Profile 无法安全使用 |
| BLOCKED_FLOW_DOWNLOAD | 当前任务下载未能确认完成 |
| BLOCKED_DRAFT_UPLOAD_ADAPTER | 不能安全适配现有草稿上传器 |
| FAILED_DRAFT_SAVE | 草稿保存失败或无法回读验证 |
| FAILED | 其他硬失败 |

退出码规则：
- 只有 DRAFT_SAVED 且 verified_draft 存在并匹配本次 Job 时，返回 0；
- SKIPPED、BLOCKED、FAILED 均返回非 0；
- 不允许以“没有硬失败”代替“草稿已保存”。

---

# 12. 开发与验收阶段

## Phase 0：只读勘查

不修改源码、不生成视频、不消耗 Flow 额度、不上传草稿。

只读检查：
1. Article Summary 的真实输出 Schema；
2. 原内容 QA 和 SHA 绑定字段；
3. 从 speech_units.spoken_text 选择句子的可行性；
4. sentence → claim → source_excerpt 的关联方式；
5. 独立 Edge Flow Profile 和 CDP 连接能力；
6. 当前 Edge/CDP 下载目录设置和下载事件能力；
7. 当前 Google Flow 账号是否支持单次 15 秒竖屏生成；
8. Flow 是否在同一次生成中支持中文文字与音乐；
9. 当前 Flow 账号额度和单次生成成本；
10. 视频号现有草稿上传器接受的输入结构；
11. 如何在不伪造 QA、不影响前两个任务的前提下接入 Flow MP4；
12. 草稿保存后的 verified_draft 回读能力；
13. 原 TASK_PLAN V5 的 Flow 禁令如何按第 6.3 节限定为第三 BAT 的明确例外。

Phase 0 输出：

    docs/LITERATURE_MICRO_VISUAL_PHASE0_REPORT.md

只报告真实可用、不可用和待人工处理项，不进行真实生成。

## Phase 1：实现最小生产链路

只新增第三条独立工作流：
- 摘要候选扫描；
- 原句选择和证据关联；
- 微观场景 Prompt；
- Flow 独立 Edge Profile；
- 单次 15 秒生成；
- CDP 任务级下载；
- 现有草稿上传器适配；
- verified_draft 回读；
- 独立 jsonl 台账；
- 独立 CLI 和 BAT。

不新增视频 QA、VLM、Pillow、独立音乐处理或 FFmpeg 内容制作模块。

必须优先复用现有成熟模块，不重构前两个 BAT。

## Phase 2：一次真实端到端实验

使用一份合格的已有文献总结：

1. 选择一句总结原句；
2. 建立 claim 和 source_excerpt 关联；
3. 生成 Flow Prompt；
4. 通过专用 Edge Profile 提交一次 15 秒 Flow 生成；
5. 下载本次 MP4；
6. 使用现有草稿上传链路保存到视频号草稿箱；
7. 回读并确认 verified_draft；
8. 将草稿位置和本地 MP4 路径交给用户。

不执行视频质量 QA。

不自动重生成。

不发布、不定时发布。

用户在视频号草稿箱中亲自检查画面、文字和音乐。

## Phase 3：每日自动化

Phase 2 完成一次真实 DRAFT_SAVED 保存回读后，先将草稿交给用户人工检查；只有用户确认首条草稿的整体形式可以接受后，才将第三个 BAT 纳入每日自动任务。

每日任务：
- 独立扫描合格文献总结；
- 每日最多生成一条；
- 独立使用和记录 Flow 额度；
- 独立保存草稿；
- 不影响前两个 BAT；
- 没有合格输入时跳过；
- 任何 Flow 或上传失败都明确报告；
- 不自动发布或安排发布时间。

---

# 13. 安全与禁止事项

1. 不修改 WeChat_control。
2. 不重构前两个 BAT。
3. 不修改前两个任务的去重状态或生产逻辑。
4. 不删除或覆盖历史生产输出。
5. 不占用日常 Edge 默认 Profile。
6. 不读取、复制或导出登录凭证。
7. 不自动购买 Flow 额度或升级订阅。
8. 不在结果状态不明时重复提交生成请求。
9. 不生成独立音乐、不下载授权不明的音乐。
10. 不使用本地程序叠加文字。
11. 不执行视频内容质量 QA。
12. 不伪造 QA PASS 或 upload_eligible。
13. 不绕过现有草稿保存安全机制。
14. 不发布、不定时发布、不删除其他草稿。
15. 不将真实文章、视频、浏览器 Profile、Flow 会话或敏感账号数据推送 GitHub。
16. PR 保持 Open / Draft / Unmerged。

---

# 14. V3.0.1 对 V3.0 的正式修订

| 主题 | V3.0 | V3.0.1 |
|---|---|---|
| 视频画面 | Flow 生成 | Flow 生成 |
| 屏幕文字 | Pillow 本地叠加 | Flow 同次生成 |
| 背景音乐 | 独立音乐素材与本地混音 | Flow 同次生成纯器乐 |
| 视频 QA | FFmpeg + VLM | 完全取消，由用户检查 |
| 文字 QA | 自动逐字检查 | 完全取消，由用户检查 |
| 音频 QA | 自动检查音轨、人声、音乐 | 完全取消，由用户检查 |
| 官方角标白名单 | VLM 识别与白名单 | 取消自动检查 |
| Extend | 允许受控备用 | 不使用，单次 15 秒直出 |
| 本地后期 | Pillow + FFmpeg | 不进行内容后期；只原样上传 |
| 上传 | 先本地验收 | 直接保存视频号草稿箱 |
| 成功标准 | VIDEO_QA_PASSED | DRAFT_SAVED + verified_draft |
| 用户检查 | 视频生成后检查 | 在视频号草稿箱检查 |

## 14.1 关于原句定义

V3.0 原先的“原句”存在歧义。V3.0.1 正式明确：

**视频文字是从已生成文献总结中选出的原句，不要求与原论文原文逐字相同。**

其科学证据通过 claim 和 source_excerpt 关联，不允许伪装成论文直接引语。

## 14.2 关于 TASK_PLAN V5

用户明确批准的 Flow 网站自动化，仅适用于第三个 Literature Micro-Visual BAT。

除该明确范围例外外，TASK_PLAN V5 其他限制全部继续有效。

## 14.3 冻结声明

V3.0.1 是第三个 BAT 当前唯一有效的实施规格。

不得擅自重新加入：
- TTS；
- PPT；
- 多幕拼接；
- 图表和机理讲解；
- Pillow；
- 本地字幕；
- 独立音乐库；
- 音乐混音；
- VLM；
- 视频内容 QA；
- 自动质量重生成。

实际账号能力不足时必须明确报告阻塞，不能静默降低 15 秒目标、伪造草稿保存或绕过现有安全机制。

只有真实环境证据证明当前规格无法实现，或真实生产暴露明确缺陷时，才可提出新版本修订；未经用户确认不得改变冻结要求。

**最终产品：从已有文献总结选择一句话，用 Google Flow 一次生成 15 秒微观画面、屏幕文字和纯器乐背景音乐，然后直接保存到视频号草稿箱。用户负责最终检查。**
