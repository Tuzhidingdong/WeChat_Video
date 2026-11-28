# PR #8 定向修复验收报告

## 修复内容

### 1. 已提交 Flow 的续作冲突
`src/wechat_video/micro_visual_continuation.py`：
- 旧保护逻辑（ledger `flow_submitted=true` 即拒绝）改为**带事件校验的续作**：
  - `flow_submitted=true` 且 `flow_generation_event.json` 缺失 → 停止；
  - event 的 Prompt SHA 与当前 frozen/submitted Prompt 不匹配 → 停止；
  - 校验通过 → 允许进入结果定位、下载、视频校验与上传；**任何路径都不会再次提交 Generate**；
  - `DRAFT_SAVED` 仍拒绝重复上传。
- `resume` 分支已有 final.mp4 时直接校验/上传；没有 final.mp4 时走只读 locate+download，不 Generate。

### 2. 新 job 的 run_id 与 job_id 传递
`src/wechat_video/micro_visual_unified.py`：
- 新分支生成 `mv-<timestamp>-<uuid8>` 并通过 `run_unified() → run_literature_micro_visual(..., run_id=...)` 传递，`visual_theme_binding.json` 因此保存非空 run_id。
- 新任务结果从 Pipeline 返回值提取真实 `job_id` 写入 `unified_job_id`；`unified_run_id` 同步记录。

### 3. 异常退出写入终止状态
`src/wechat_video/cli.py` 统一入口分支：
- 捕获分类/续作异常，写出 `state=FAILED`、`exit_code=2`、原因与 `unified_mode=error`，不再残留 `RUNNING`；
- BAT 状态文案显示真实终止原因；成功仍必须是 `DRAFT_SAVED` + `verified_draft`。

### 4. 状态与 ledger 管理
`micro_visual_unified.py`：
- `RESUMABLE_STATES`：STOPPED_BEFORE_FLOW_SUBMIT / FAILED / FLOW_SUBMISSION_UNKNOWN / BLOCKED_FLOW_DOWNLOAD / FAILED_DRAFT_SAVE / FAILED_VIDEO_VALIDATION；
- `MANUAL_BLOCK_STATES`：BLOCKED_UPLOADER_IDENTITY / BLOCKED_FLOW_15S_UNAVAILABLE / BLOCKED_FLOW_QUOTA / BLOCKED_BROWSER_PROFILE / BLOCKED_DRAFT_UPLOAD_ADAPTER / UPLOAD_UNKNOWN（识别为 blocked，不重试也不当作无 job）；
- `PRE_JOB_STATES`：CONFIG_FAILURE / BLOCKED_ARTICLE_SOURCE / SKIPPED_* 等无 job 目录的 ledger 记录被忽略，不再阻塞后续新任务；
- 多个未完成/阻塞 job 或歧义 → 停止报告。

## 关键文件 SHA256

```
de7c31aa077a71328d0bba7018682a623c8123fe69cf02f0d2a45928d3d9b476  Run_Literature_Micro_Visual.bat
f34a4aafb9d1b5b5defb75a7252e1541cfad6447cea788786cf623ea8c467373  src/wechat_video/cli.py
c017650bc82b0df37cb79d57368ba829cbd8ef84c819fd582d2223746f106a69  src/wechat_video/micro_visual_unified.py
74aa05ebe9560cc01eaa8d323a4b82c7a458b5894b0214c3c630cecea38e6fc2  src/wechat_video/micro_visual_continuation.py
09b31814be4b25ef9b02c376177110c921118fc230358ae93159f2a139452e9c  config/micro_visual.json (未改)
```

## 测试

命令：
```
.venv\Scripts\python.exe -m pytest -q tests/test_micro_visual_unified.py tests/test_micro_visual_unified_integration.py tests/test_micro_visual_continuation.py tests/test_micro_visual_finalize.py
```
结果：**23 passed / 0 failed**。

集成 Mock 测试实际连接分类器与真实续作代码，覆盖：
1. flow_submitted + 有效 event + 无 final.mp4 → locate+download，不 Generate；
2. flow_submitted + 有效 event + 有 final.mp4 → 直接校验+上传，不 Generate；
3. event 缺失 → 停止，不 Generate；
4. event Prompt SHA 不匹配 → 停止，不 Generate；
5. 新 job run_id 非空、模拟中断后可被统一入口识别并续作；
6. BLOCKED_UPLOADER_IDENTITY 被识别为 blocked；
7. CLI 分类/续作异常后 state file 不残留 RUNNING；
8. DRAFT_SAVED job 不重复上传，无未完成 job 时可新建。

未运行真实 Flow、未消耗积分、未操作视频号。
