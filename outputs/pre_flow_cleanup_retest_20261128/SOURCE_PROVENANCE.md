# 本次来源与身份绑定

## 来源

| 项目 | 值 |
|---|---|
| 来源类型 | 已有 `daily_runs`（非本次新采集） |
| source_run_id | `20261124T145207-d1e7fee3` |
| article_id | `100000884_0` |
| slot1 路径 | `E:\Agent\WeChat\data\daily_runs\2026-11-24\research_subscription\20261124T145207-d1e7fee3\slot1.md` |
| slot1 / source SHA256 | `0f3456a638798e44eef071d6710bd9644b727aab619dcb05cfe0ce5f9511b7f2` |
| Article Package | `runtime/upstream_article_packages/100000884_0/20261124T145207-d1e7fee3/`（同源同 SHA 身份绑定复用） |

本次 BAT3 按现有生产规则从 `daily_runs` 发现并校验来源，未启动 WeChat_control launcher，未新增主动采集能力；历史来源复用不报告为新采集。设计依据见 `outputs/root_cause_investigation_20261128/bat3_acquisition_freeze_recheck/`。

## 本次绑定（真实 `visual_theme_binding.json`）

| 字段 | 值 |
|---|---|
| run_id | `mv-20261128205646-927b777d` |
| article_id | `100000884_0` |
| source_run_id | `20261124T145207-d1e7fee3`（已修复，不再是 null） |
| source_article_sha256 | `0f3456a638798e44eef071d6710bd9644b727aab619dcb05cfe0ce5f9511b7f2` |
| summary_sha256 | `73561b7573943be6272f15720a2e3ef8ff32fba463f9e3d2a7592da27944d6ec` |
| visual_theme_sha256 | `5d38e14180af66571e79dbb694596bf5cb5f51eb1599fb1d1498816bcf2ac58e` |
| flow_prompt_sha256 | `4db725d6bd1d3e943e8e0ced6e1c9bf891f3803dd446f0441ca340bb771351a9`（归一化 Prompt 文本 SHA） |

`source_run_id` 来自 `selected_article.run_id` / `acquisition.run_id`，不是硬编码；本次值与来源目录一致。
