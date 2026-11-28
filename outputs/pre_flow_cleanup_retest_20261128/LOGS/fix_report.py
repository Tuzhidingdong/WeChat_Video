from pathlib import Path
p = Path('outputs/pre_flow_cleanup_retest_20261128/EXECUTION_REPORT.md')
t = p.read_text(encoding='utf-8')
t = t.replace(
    '4. Planner：Session `ses_ddddf8fa9ffe8HqvbP5eHlzrZn`（日志见 `LOGS/bat_stdout.log`）——注意这是**上一次运行**的 Planner；本次日志中 Planner 产物绑定本次 run_id。',
    '4. Planner：Session `ses_dddc530eeffefk79YX2Zs0YkHP`，steps=1，tokens=15786（本次 `LOGS/bat_stdout.log`）。',
)
p.write_text(t, encoding='utf-8')
