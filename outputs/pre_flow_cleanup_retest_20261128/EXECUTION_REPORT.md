# BAT3 收尾修复后真实入口重新验收（2026-11-28）

## 结论：真实 BAT3 入口完整执行到 Flow 提交前，生成本次 Prompt；无 Flow 调用

- 命令：`cmd.exe /c Run_Literature_Micro_Visual.bat --scheduled`
- 最终 run_id：`mv-20261128205646-927b777d`
- 业务状态：`STOPPED_BEFORE_FLOW_SUBMIT`；BAT exit code `0`
- 最终 Prompt 文件 SHA256（原始字节）：`8f342972526c6c13ee42a81ec76215de298afcc1417a5d684f1b33a94c615577`
- 归一化 Prompt 文本 SHA256（去尾部换行、LF）：`4db725d6bd1d3e943e8e0ced6e1c9bf891f3803dd446f0441ca340bb771351a9`
- Stage A Session：`ses_dddbf75e8ffet67de3uX3heIvn`（由生产写入的 `stage_a_session.json` 动态取得，未二次调用模型）

## 一、执行过程

1. BAT3 启动：CLI `run-literature-micro-visual`，新 suffix `cleanup_20261128_205646`，配置仅临时改 suffix，退出后 SHA 恢复 `09b31814…e9c`。
2. 文章发现：只读 `daily_runs`，本次来源 run `20261124T145207-d1e7fee3`（详见 `SOURCE_PROVENANCE.md`）。
3. Article Package：身份绑定复用（同源同 SHA）。
4. Planner：Session `ses_dddc530eeffefk79YX2Zs0YkHP`，steps=1，tokens=15786（本次 `LOGS/bat_stdout.log`）。
5. Content-only Summary：本次 `outputs/mv9/20261128_210304_628380_100000884_0_micro_visual_content_summary/`，summary SHA `73561b75…44d6`；无 TTS/WordBoundary/视频产物。
6. Stage A：真实 Agent `micro-visual-theme-extractor`，Session `ses_dddbf75e8ffet67de3uX3heIvn`，原始响应已在生产写入时保存（`STAGE_A_RESULT_RAW.txt` / `STAGE_A_RESULT.json`），未做证据校验阻断。
7. Stage B：编译本次最终 Prompt，写入 `FINAL_FLOW_PROMPT.txt`，binding 中 `source_run_id` 已正确为 `20261124T145207-d1e7fee3`。
8. BAT 收尾：正确输出 `[STOPPED_BEFORE_FLOW_SUBMIT] run_id=... exit_code=0 ...`，无 CMD 引号错误。

## 二、失败与恢复

首次收尾修复后运行（`LOGS/attempt1/`）虽然成功，但 BAT 尾部仍有 `']' is not recognized` 的 CMD 解析错误（源于 `echo [INFO] 状态文件：` 的全角冒号）。定位后改为 ASCII 冒号，随后**从 BAT3 入口重新完整执行**一次（本次报告对应这次运行），日志尾部已无该错误。未拼接不同运行产物。

## 三、证据类别

- **真实执行**：BAT 日志、Session、产物 SHA、binding、状态文件。
- **静态检查**：源码与配置、三项修复的代码位置。
- **历史证据**：文章来源采用历史 daily_runs 的设计依据（已如实记录，未报告成新采集）。
