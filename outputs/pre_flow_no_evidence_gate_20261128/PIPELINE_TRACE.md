# 各阶段输入输出与产物路径

| 阶段 | 输入 | 输出 / 产物 | SHA / ID | 证据 |
|---|---|---|---|---|
| BAT3 入口 | `Run_Literature_Micro_Visual.bat --scheduled` | CLI `run-literature-micro-visual` | run_id `mv-20261128202758-270af5b1` | `LOGS/bat_stdout.log`、`run_result.json` |
| 文章发现/来源校验 | 本地 daily_runs | 来源 run `20261124T145207-d1e7fee3`，slot1 SHA `0f3456a6…` | article `100000884_0` | `micro_visual_plan.json`、BAT 日志 |
| Article Package | slot1.md | `runtime/upstream_article_packages/100000884_0/20261124T145207-d1e7fee3/` | article.json SHA `bdabb4b4…` | 身份绑定复用 |
| Planner | article.json/md/images.json | `runtime/micro_visual_article/.../planner/summary.json` | session `ses_ddddf8fa9ffe8HqvbP5eHlzrZn`；copied `planner_summary.json` | `planner_report.json` |
| Content-only Summary | Planner summary | `outputs/mv7/20261128_203040_883208_100000884_0_micro_visual_content_summary/` | copied `content_summary.json`、`content_manifest.json`、`content_qa.json`；summary SHA `3e8b1205…` | manifest 绑定本次 run_id |
| Stage A | 本次 summary + 本次 article.md | 3 候选，选中 A | session `ses_ddddd1ea9ffeSi0eAv5fHawZAT`；copied `STAGE_A_RESULT.json`；theme SHA `f927461f…` | BAT 日志 + transcript |
| 证据校验 | Stage A 输出 | **已取消**，直接放行 | 代码中无证据检查 | `CODE_CHANGE_SUMMARY.md` |
| Stage B | Stage A 选中候选 | `flow_prompt.txt` | SHA `6628881f…`，binding 同 SHA | `FINAL_FLOW_PROMPT.txt`、`visual_theme_binding.json` |
| 停止 | Flow 提交前 | 状态 `STOPPED_BEFORE_FLOW_SUBMIT` | exit 0，台账 `flow_submitted=None` | `final_status.json` |

## 主题与 Prompt 对应

Stage A 选中候选 A：
- subject：`Composite micelles`
- action：`Laterally assemble into a single monolayer`
- environment：`Emulsion droplet interface`

最终画面句：`composite micelles laterally assemble into a single monolayer within an emulsion droplet interface`。固定约束（15s/9:16/720p/x1/无文字/无字幕/无人声/纯器乐/单次不 Extend）完整保留。
