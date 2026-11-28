# 本次文章来源与获取方式（如实记录）

## 结论：本次**没有**执行新的 WeChat_control 主动采集；使用的是有明确设计依据的、身份绑定的历史来源复用

任务要求核实“昨天已集成且实际采集成功”的说法。核实结果（只读证据，见 `outputs/root_cause_investigation_20261128/bat3_acquisition_freeze_recheck/`）：

- 当前 BAT3 生产调用链中**不存在**主动采集调用：`micro_visual_pipeline.py:166` 注释明确 `No active collection launcher exists`；`micro_visual_article_source.py` 只有 `discover_upstream_literature_runs()` 只读发现。
- 主动采集模块 `micro_visual_upstream.py` 已于 2026-11-27 18:38 由独立任务 `MICRO_VISUAL_REUSE_READING_DRAFT_SOURCE_AND_FLOW_PROMPT_20261127.md:11-16,25` 明确删除；冻结基线 `MICRO_VISUAL_FORMAL_FREEZE_BASELINE_20261127.md:41` 写明“只读本地 daily_runs，不主动采集”。
- 唯一一次真实 launcher 启动（`PHASE0_REAL_SOURCE_ACCEPTANCE_20261127.md:69-86`）以 `--resume-run` 复用旧 run，未产出 `slot1.md`，Phase 0 阻塞；不存在“主动采集成功并产出新文章”的运行记录。
- 因此不恢复该能力：恢复需要启动会写公众号草稿的 WeChat_control launcher，超出本任务“不操作视频号”的边界。

## 本次实际来源

| 项目 | 值 |
|---|---|
| 文章 ID | `100000884_0` |
| 标题 | 罗巍晁栋梁团队发文 Adv. Mater.：盐效应反常诱导单胶束单层组装筑牢无枝晶界面 |
| 来源 run_id | `20261124T145207-d1e7fee3` |
| 来源类型 | 历史 `daily_runs`（2026-11-24），非本次新采集 |
| 采集时间 | 2026-11-24（WeChat_control 既有产出，非本次运行产生） |
| slot1 路径 | `E:\Agent\WeChat\data\daily_runs\2026-11-24\research_subscription\20261124T145207-d1e7fee3\slot1.md` |
| slot1 / source SHA256 | `0f3456a638798e44eef071d6710bd9644b727aab619dcb05cfe0ce5f9511b7f2` |
| Article Package | `runtime/upstream_article_packages/100000884_0/20261124T145207-d1e7fee3/`（SHA 一致才身份绑定复用） |
| 本次读取路径 | 同上，日志与 `micro_visual_plan.json` 均记录 |

复用依据：`upstream_article_source.py:928-939` 先重算 slot1 SHA 并与发现结果比对，article_id 与 article.md SHA 完全一致才复用，冲突即拒绝覆盖。这是合法的同源同 SHA 复用，**不是**错误复用其他文章，也**不是**新采集。
