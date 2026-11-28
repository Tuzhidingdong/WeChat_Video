# BAT3 生成前全流程执行报告（取消 Stage A 证据校验后）

## 结论：本次真实 BAT3 入口执行成功，生成了本次运行的最终 Flow Prompt，停在 Flow 提交前

- 命令：`cmd.exe /c Run_Literature_Micro_Visual.bat --scheduled`
- run_id：`mv-20261128202758-270af5b1`
- job_id：`20261128_100000884_0_micro_visual_nogate_20261128_202757`
- BAT exit code：`0`；业务状态：`STOPPED_BEFORE_FLOW_SUBMIT`
- 最终 Prompt SHA：`6628881f384836e18b9c9a1fbe5f52f3930e2d888cd98bc80206dc596b2f9553`
- 全程未调用 Flow、未消耗 credits、未打开视频号、未上传/保存/发布

## 一、真实执行证据

- `LOGS/bat_stdout.log`：Planner Session `ses_ddddf8fa9ffe8HqvbP5eHlzrZn`（steps=1，tokens=29220）；Stage A Session `ses_ddddd1ea9ffeSi0eAv5fHawZAT`（steps=1，tokens=23016）；结果 JSON 含 `STOPPED_BEFORE_FLOW_SUBMIT`、`flow_prompt_path`、`flow_prompt_sha256`。
- `run_result.json`：配置原始 SHA `09b31814…e9c`，仅临时替换 `job_id_suffix`，退出后原样恢复且 SHA 一致；`stop_before_flow_submit=true` 未改。
- `final_status.json`：状态文件与 run_id 同批次。
- 台账最后一条：本次 job_id，`draft_state=STOPPED_BEFORE_FLOW_SUBMIT`，`flow_submitted=None`。

## 二、失败与恢复

本次运行一次成功，无失败、无重试。此前 read-only 调查发现的 Planner 19 claims 与 Stage A 证据校验问题，本次未复现：本次 Planner 输出通过解析，Stage A 证据关卡已按要求取消。

## 三、取消证据关卡的证明

`src/wechat_video/micro_visual_theme.py` 的 `validate_theme()` 现在只做数据结构检查（对象类型、字段存在、文本非空/非中文、schema_version、selected_id 可解析、identity 一致），**不再**检查：
- claim id 是否存在；
- source_excerpt 是否属于原文；
- evidence_paraphrase 是否与字段词形匹配；
- unsupported_visual_details 是否与字段冲突。

Stage A 选定候选后直接进入 Stage B；本次 Stage A 输出含 3 个候选并选定 A，Stage B 成功编译。

## 四、证据类别

- **真实执行**：BAT 日志、Session、产物 SHA、台账、状态文件。
- **静态检查**：源码中无证据校验调用、配置值、调用链。
- **历史证据**：文章获取设计依据（见 `SOURCE_PROVENANCE.md`），说明本次为身份绑定的历史来源复用，不冒充新采集。
