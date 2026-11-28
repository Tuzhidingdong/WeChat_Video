# 三项修正代码摘要

| 文件 | 修改前 SHA256 | 修改后 SHA256 |
|---|---|---|
| `Run_Literature_Micro_Visual.bat` | `ec30da40115dfc84f5afb8b9b652829bb503e05d1513c8bb9eb6e8041ae5683b` | `cfe2efe41a9b86c79d3f8471e6dff03a3e4dfbb235cb203087e15a7dbec6ad27` |
| `src/wechat_video/micro_visual_status_readback.py` | 新增 | `26a21dec43b590ce2c26443ddf255a441080d68111e5757d859ec9566b3d3223` |
| `src/wechat_video/micro_visual_theme.py` | `1c77b3dbf322479bfb1815c25b18d0ad9357a7d8a00cc92481e35bc28f7a6c29` | `5ac0408474465ab962fe24df9635c39a54daba7bb7b98352bd13d46accd35b22` |
| `src/wechat_video/micro_visual_pipeline.py` | `4d55102f...`（PR#5 后为 `86b7181bc259a9226d74732ef27dafed82bbf7d1bca839b41b8e93dba4ef45af`） | `524c2e9c3c50f9b85c2ce9a761d61e9e9c0e7ce24a7327d4e150f3138cc5dcfa` |
| `tests/test_micro_visual_cleanup_fixes.py` | 新增 | 见 ARTIFACT_SHA256.txt |
| `tests/test_micro_visual_article_theme_pipeline.py` | `aad0514361b08b604e2647b0aebdc8d6c1a061e617774b9bf0007fab0f97d4a4` | 见 ARTIFACT_SHA256.txt |

## 修正内容

1. **BAT 状态读取**：移除 `FOR /F` + 反引号内嵌双引号调用；改为独立辅助脚本 + 临时文件 + `set /p`。修复全角冒号导致的 `']' is not recognized`。状态语义：区分 `STOPPED_BEFORE_FLOW_SUBMIT`（预期停止）、`DRAFT_SAVED`（需验证草稿）、缺失/非法/身份不匹配（真实错误）；不以 exit 0 或 success=false 单独判定。
2. **Stage A 原始输出**：`extract_visual_theme()` 在模型响应返回时立即写 `visual_theme_raw.json` / `visual_theme_raw.txt` / `stage_a_session.json`（含动态取得的 session_ids、agent、model、附件、run_id、article_id）。未二次调用模型，未从整理后的 `visual_theme.json` 反向拼装。
3. **source_run_id**：`visual_theme_binding.json` 的生产写入改为使用 `acquisition.get("run_id") or selected_article.get("run_id")`，不再从 evidence 读取不存在的字段；新增定向断言防止回退为 null。

## 未修改

Stage A 证据校验（PR#5 已取消）、Agent/模型/Planner/Stage B 规则、文章发现策略、Flow 配置、上传器、BAT2、WeChat_control、账号/付款/发布配置、浏览器会话。

## 定向测试

命令：
```
.venv\Scripts\python.exe -m pytest -q tests/test_micro_visual_cleanup_fixes.py tests/test_micro_visual_article_theme_pipeline.py tests/test_micro_visual_theme.py tests/test_micro_visual_summary_and_cli.py tests/test_micro_visual_upstream_and_flow_id.py
```
结果：**35 passed / 0 failed**。未运行无关庞大测试集。
