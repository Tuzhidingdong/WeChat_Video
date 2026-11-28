from pathlib import Path
p = Path('outputs/pre_flow_cleanup_retest_20261128/EXECUTION_REPORT.md')
lines = p.read_text(encoding='utf-8').splitlines()
for i, line in enumerate(lines):
    if line.startswith('4. Planner'):
        lines[i] = '4. Planner：Session `ses_dddc530eeffefk79YX2Zs0YkHP`，steps=1，tokens=15786（本次 `LOGS/bat_stdout.log`）。'
p.write_text("\n".join(lines) + "\n", encoding='utf-8')
