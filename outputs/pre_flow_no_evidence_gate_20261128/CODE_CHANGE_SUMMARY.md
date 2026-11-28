# 代码修改摘要

## 修改文件

| 文件 | 修改前 SHA256 | 修改后 SHA256 |
|---|---|---|
| `src/wechat_video/micro_visual_theme.py` | `b8abe07dab7d78af8a6abc13828c2b6f9c387d123fd28ce75d07a4c8bb60a4b3` | `1c77b3dbf322479bfb1815c25b18d0ad9357a7d8a00cc92481e35bc28f7a6c29` |
| `tests/test_micro_visual_theme.py` | `2e8b2afea513f8d18357c9dcf835a35cf5dc3324065d82f7895a457f7e470e30` | `e66ef941a38454d5023bea70f719b4f45abbe100bc5f1b3ddf9664701261de9e` |
| `tests/test_micro_visual_article_theme_pipeline.py` | `c6567fdf70dd16f279ac3feab7439661192907ed890366b257b8f6feb739f6f0` | `aad0514361b08b604e2647b0aebdc8d6c1a061e617774b9bf0007fab0f97d4a4` |

## 修改原因与范围

- `micro_visual_theme.py`：`validate_theme()` 从「完整证据契约校验」改为「仅数据结构检查」。删除的检查包括 claim id 存在性、source_excerpt 原文归属、evidence_paraphrase 词形覆盖、unsupported details 冲突、action 动态动词限制。保留：JSON 对象类型、schema_version=2、identity 一致、候选数量与 id 唯一、字段对象与文本非空/非中文。Stage A 选定后直接交给 Stage B。
- `_validate_field()` 保留字段类型检查（`supporting_claim_ids`/`supporting_source_excerpts` 为 list，`evidence_paraphrase` 为 str），但不校验其内容。
- `compile_visual_prompt()` 的编译规则、整短语使用、语法归一化、固定视频约束（含 `SINGLE_GENERATION`）**未改**。
- Agent 定义、模型、Planner、文章发现、content-only summary、Flow 配置、上传器、BAT2 均**未修改**。

## 测试

定向测试命令（8 个文件）：`.venv\Scripts\python.exe -m pytest -q tests/test_micro_visual_theme.py tests/test_micro_visual_article_theme_pipeline.py tests/test_micro_visual_summary_and_cli.py tests/test_micro_visual_upstream_and_flow_id.py tests/test_micro_visual_integration.py tests/test_micro_visual_content_summary.py tests/test_micro_visual_v302.py tests/test_micro_visual_root_cause_fixes.py`

结果：**107 passed / 0 failed**。测试已更新为「证据不匹配不再阻断、结构检查仍有效」。
