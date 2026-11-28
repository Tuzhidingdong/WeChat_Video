# 统一 Micro Visual BAT 交付报告

## 最终唯一入口

`Run_Literature_Micro_Visual.bat`（SHA `de7c31aa…3d9b476`）现在只调用一个 CLI 命令：

```
python -X utf8 -m wechat_video.cli run-micro-visual-unified --state-file ...
```

BAT 不解析 JSON、不选择模式、不要求 job ID；状态文案仍由已修复的 `micro_visual_status_readback.py` 单行读取，并在消息中标注 `[统一入口:resume|complete|new]` 与 job ID。

## 统一入口逻辑（`src/wechat_video/micro_visual_unified.py`）

`run_unified()` 先调用 `classify_jobs()` 读取 `runtime/micro_visual_jobs.jsonl` 与 `outputs/<job>/micro_visual_plan.json`：

- **DRAFT_SAVED + verified_draft** → 视为已完成；不为该 job 重复上传。若没有其他未完成 job，则按情况 B 创建新 job。
- **flow_submitted=true** → 必须有 `flow_generation_event.json`，否则判为损坏并停止；有事件则续作，**绝不再次提交 Generate**。若已有 `final.mp4`，直接续到视频校验/上传；若没有，则只读定位结果并下载，不提交。
- **STOPPED_BEFORE_FLOW_SUBMIT / FAILED / BLOCKED_* / UPLOAD_UNKNOWN 等未完成状态** → 必须有 `flow_prompt.txt`、`visual_theme_binding.json`、`source_evidence.json`、`micro_visual_plan.json`；齐全则续作原 job。
- **没有未完成 job** → 创建新 job，执行完整生产模式。
- **损坏/歧义** → 缺必要文件、无 ledger 状态、DRAFT_SAVED 缺 verified_draft、flow_submitted 无事件、多个未完成 job，均抛 `UnifiedDecisionError` 并停止；不新建 job、不猜测。

### 完整模式如何越过 `stop_before_flow_submit=true`

不动配置文件：在 `run_unified()` 的 `new` 分支通过 `deps["load_config"]` 注入一个包装器，仅在本次调用返回的内存配置中把 `stop_before_flow_submit` 设为 `False`，再调用既有 `run_literature_micro_visual(deps=...)`。因此 BAT 会从文章发现一直跑到草稿保存，而 BAT2/其他 CLI 调用方式不受影响。

## 复用 PR #7 能力

- 续作：`continue_micro_visual_run()`（本次新增 resume-download 分支，保证已提交 Flow 不再 Generate）。
- 已保存草稿收尾：`finalize_existing_draft()`，只读，不重复上传。
- Flow 浏览器导航：落地页无输入框时进入已有 project editor。
- 保留 Stage A 结构检查、来源只读 daily_runs、Prompt SHA、身份与重复提交保护、草稿箱独立回读。

## 关键文件 SHA256

```
de7c31aa077a71328d0bba7018682a623c8123fe69cf02f0d2a45928d3d9b476  Run_Literature_Micro_Visual.bat
79cf40b301a3aa6fa43cfcc8cd43f8438c3b200fa2261bbbcfb6527634040973  src/wechat_video/cli.py
a2919fdb6313ef1d9294473bb502317973dba6fb3431393427a91f200e56a2cf  src/wechat_video/micro_visual_unified.py
57dced251ece495525736fba20b2e359766f5379337933a2d2d5952759e28193  src/wechat_video/micro_visual_continuation.py
298c60c6a4b6b998798e3592206d074b085cecbc75c81fb6d7b9533fe78b2c96  src/wechat_video/micro_visual_browser.py
09b31814be4b25ef9b02c376177110c921118fc230358ae93159f2a139452e9c  config/micro_visual.json (未改)
```

## 测试（模拟数据 + Mock，无真实 Flow/视频号）

命令：
```
.venv\Scripts\python.exe -m pytest -q tests/test_micro_visual_unified.py tests/test_micro_visual_continuation.py tests/test_micro_visual_finalize.py
```
结果：**15 passed / 0 failed**。

覆盖：无未完成 job→新建且强制完整模式；STOPPED→续作原 job；已提交 Flow→不再 Generate；已有视频→从后续阶段续作；DRAFT_SAVED→不重复上传；缺文件/无事件/多 job→停止；resume-download 路径不二次提交；BAT 仅含统一入口。

未执行：真实 BAT3、真实 Flow 生成、积分消耗、视频号操作；按要求仅做 Mock 验收。
