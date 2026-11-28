# 代码变更摘要（下游续作）

| 文件 | 用途 |
|---|---|
| `src/wechat_video/micro_visual_continuation.py` | 新增：仅针对明确 job_id 的下游续作；身份/SHA/重复提交前置检查；复用现有 Flow Browser、Submission、Result、Download、Upload Adapter；resume 分支避免二次 Generate；`finalize_existing_draft()` 只读收尾。 |
| `src/wechat_video/cli.py` | 新增 `continue-micro-visual` 与 `finalize-micro-visual-draft` 子命令。 |
| `src/wechat_video/micro_visual_browser.py` | 最小修复：Flow 落地页无 Prompt 输入框时，进入已存在的 project editor。 |
| `tests/test_micro_visual_continuation.py` | 新增：job/SHA/台账保护、resume 不重复提交、happy path 到 DRAFT_SAVED。 |
| `tests/test_micro_visual_finalize.py` | 新增：已有草稿只读收尾。 |

定向测试：`pytest -q tests/test_micro_visual_continuation.py tests/test_micro_visual_finalize.py` → **5 passed / 0 failed**。

未修改：PR#5/PR#6 已完成逻辑、Planner、Stage A/B、文章发现、Flow 参数、上传器源码、BAT2、WeChat_control、账号/付款/发布配置。运行期对 `channels_upload.json.ui_settle_ms` 的临时放宽已原样恢复（SHA `f0c839d0…`），对 uploader 导航的包装仅在 continuation 进程内生效，未写入共享源码。
