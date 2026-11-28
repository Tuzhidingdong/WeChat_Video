# Flow 生成与视频号草稿保存验收

## 最终结论：`DRAFT_SAVED` + `verified_draft`

本次直接续用冻结 job `20261128_100000884_0_micro_visual_cleanup_20261128_205646`（run_id `mv-20261128205646-927b777d`），没有重新调用 Planner、Stage A、Stage B，没有重新采集文章，没有重跑 BAT3 前半段。

## 1. 产物与身份

| 项目 | 值 |
|---|---|
| 冻结 run_id | `mv-20261128205646-927b777d` |
| article_id | `100000884_0` |
| 来源 run | `20261124T145207-d1e7fee3` |
| 来源 SHA | `0f3456a638798e44eef071d6710bd9644b727aab619dcb05cfe0ce5f9511b7f2` |
| 原始编译 Prompt SHA（文件字节） | `8f342972526c6c13ee42a81ec76215de298afcc1417a5d684f1b33a94c615577` |
| 原始 Prompt 文本 SHA | `4db725d6bd1d3e943e8e0ced6e1c9bf891f3803dd446f0441ca340bb771351a9` |
| 实际提交 Prompt SHA（文件字节） | `4b3dce5750b8ab7ecafc5384e070d0a521ed2bf492aa2fdf86910683230cee6e` |
| 实际提交 Prompt 文本 SHA | `d9cfdcfdd97abbd5e1739f08e78da51930533b37ae54bf5eee3383a3c63f2a43` |
| Flow 提交时间 | `2026-11-28T22:19:15` |
| Flow 项目 | `d8d339ad-f84f-4098-8383-d942e6a15b3c` |
| 视频 SHA256 | `5b2650adc6c3b98b995b3c15d2486610efe83c58ce5261eac774ba0605e8726f` |
| 草稿标题 | `盐效应与界面离子调控` |
| 草稿 save_click_count | **1** |

## 2. Prompt 修订

只改了一句空间表达，候选 B 的研究对象、沉积行为、环境及全部固定约束不变：

- 原句：`tin deposits on mesoporous polydopamine coating remain dense and smooth during electroplating within a tin electrode surface in aqueous electrolyte`
- 提交句：`tin deposits remain dense and smooth during electroplating as they form on a mesoporous polydopamine coating over a tin electrode in aqueous electrolyte`

原始 Prompt 保留在 `flow_prompt.txt`，实际提交 Prompt 在 `flow_prompt_submitted.txt`，修订说明在 `prompt_revision.json`。`flow_generation_event.json` 绑定的是实际提交 Prompt 的文本 SHA `d9cfdcfd…2a43`。未重新调用模型。

## 3. Flow 生成与视频

- 模型 `Omni Flash 1.2`，15 秒，9:16，720p，输出 1，单次提交；未 Extend/Resume/二次生成。
- 生成 ID 未被平台显式暴露（`generation_id_capture_status=unavailable`），以项目 ID、提交事件、时间、视频文件与台账形成归属证据；未用 Project ID 冒充 Generation ID。
- 视频：`flow_original.mp4` 与 `final.mp4`（同 SHA），5,983,570 字节；ffprobe 实测 15.04 秒、720x1280、H.264/AAC、360 可解码帧，完整 ffmpeg 解码通过；`video_validation_report.json` 状态 PASS。未重新编码。

## 4. 上传与草稿

- 账号身份预检通过（`uploader_identity.json`：`成核生长` / `sph2Wunsevdg194`）。
- 标题来自冻结 Summary 的 `channels_title`（10 字），未临时编造；冻结 `draft_title.txt` 因超过 16 字上限未采用，另存 `draft_title_effective.txt`。
- 上传前多次尝试均停在草稿列表导航、`save_click_count=0`，按 adapter 语义标记为 `FAILED_BEFORE_SAVE` 后才重试；**只有一次**保存点击产生草稿。
- 草稿箱独立回读：`verified_draft` = `{"title":"盐效应与界面离子调控","row_text":"盐效应与界面离子调控 2026年11月28日 22:35","verified_at":"2026-11-28T14:35:12+00:00","draft_list_url":"https://channels.weixin.qq.com/platform/post/draftListManager"}`。
- 台账最后一条：`draft_state=DRAFT_SAVED`、`flow_submitted=true`、`verified_draft` 非空。

## 5. 未做与证据类别

- 未调用 Publish/Send/Schedule/群发；未操作其他账号；未删除或覆盖已有草稿；未修改账号/付款/发布配置；`config/micro_visual.json` 与 `config/channels_upload.json` SHA 恢复一致。
- 真实执行：Flow 提交事件、视频文件与 ffprobe、上传 job、草稿回读、台账、日志。
- 静态证据：continuation 的身份/SHA/重复提交保护源码、配置值。
- 未验证：平台未在响应中暴露 generation ID；草稿箱不提供视频字节 SHA，故无法字节级证明草稿内视频等于本地 MP4（仅通过本次标题、时间、账号与单次保存关联）。
