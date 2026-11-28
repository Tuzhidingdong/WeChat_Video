# BAT 收尾状态读取修复

## 1. 原错误与定位

原日志（`outputs/pre_flow_no_evidence_gate_20261128/LOGS/bat_stdout.log`）出现：
```
'.venv\Scripts\python.exe" -X utf8 -B -c "from' is not recognized...
[STOP] 未能读取业务状态
']' is not recognized as an internal or external command
```

定位到两个独立的 CMD 解析问题：
1. 第 36 行 `for /f "usebackq delims=" %%M in (`...python.exe" ... -c "...")` 的反引号命令替换中嵌套双引号，CMD 在 `"` 处截断，导致 `python.exe" ...` 被当成命令。
2. `echo [INFO] 状态文件：%STATE_FILE%` 的全角冒号在 `chcp 65001` 下被 CMD 误解析，产生 `']' is not recognized`（已用最小 probe 复现：改为 ASCII 冒号后错误消失）。

## 2. 修复

- 新增 `src/wechat_video/micro_visual_status_readback.py`：单行输出 `[state] run_id=... exit_code=... <message>`；校验状态文件存在、JSON 可解析、run_id/state/message/success 字段完整；支持 `MICRO_VISUAL_EXPECTED_RUN_ID` 环境变量做运行身份一致性检查；缺失/损坏/不匹配返回退出码 2 并输出明确 `[STOP]` 文案。
- BAT 改为把辅助脚本输出重定向到 `%TEMP%` 临时文件，再用 `set /p "MSG=" < file` 读取，彻底避开 `FOR /F` 反引号嵌套引号。
- `echo [INFO] 状态文件：` 改为 ASCII `echo [INFO] state_file: %STATE_FILE%`。

## 3. 本次实际读取结果

`LOGS/bat_stdout.log` 尾部：
```
[STOPPED_BEFORE_FLOW_SUBMIT] run_id=mv-20261128205646-927b777d exit_code=0 内容准备完成，已按配置停止在 Flow 提交前；尚未生成视频、上传视频或保存草稿。
[INFO] 退出码 0 仅供参考，成功与否以业务状态为准。
[INFO] state_file: C:\...\runtime\micro_visual_last_status.json
[INFO] 报告目录：docs\reports\
```
不再有 CMD 解析错误。状态含义：内容准备成功、Prompt 已产生、按配置停在 Flow 提交前；`success=false` 与 `verified_draft=null` 属预期，未被误判为 Planner/Prompt 失败；exit code 0 也未被当作草稿保存成功。

## 4. 定向测试

`tests/test_micro_visual_cleanup_fixes.py`：
- `test_stopped_state_readback_is_not_treated_as_failure`
- `test_missing_or_invalid_state_fails_explicitly`
- `test_run_id_mismatch_fails_explicitly`
- `test_draft_saved_without_verified_draft_is_not_success`

全部通过（详见 `CODE_CHANGE_SUMMARY.md` 的测试命令）。
