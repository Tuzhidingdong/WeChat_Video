"""Real BAT3 entry run with unique suffix and guaranteed config restore."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode\micro-visual-phase1")
REPORT = ROOT / "outputs/pre_flow_no_evidence_gate_20261128"
CONFIG = ROOT / "config/micro_visual.json"
STATE = ROOT / "runtime/micro_visual_last_status.json"
original = CONFIG.read_bytes()
original_sha = hashlib.sha256(original).hexdigest()
suffix = "nogate_20261128_" + datetime.now().strftime("%H%M%S")
result = {
    "started_at": datetime.now().isoformat(timespec="seconds"),
    "config_original_sha256": original_sha,
    "temporary_suffix": suffix,
    "stop_before_flow_submit_unchanged": True,
    "bat_exit_code": None,
    "config_restored_sha256": None,
    "error": None,
}
try:
    cfg = json.loads(original.decode("utf-8"))
    cfg["job_id_suffix"] = suffix
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["cmd.exe", "/c", "Run_Literature_Micro_Visual.bat --scheduled"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    (REPORT / "LOGS/bat_stdout.log").write_text(proc.stdout or "", encoding="utf-8")
    result["bat_exit_code"] = proc.returncode
except Exception as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"
finally:
    CONFIG.write_bytes(original)
    result["config_restored_sha256"] = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    result["config_restored_ok"] = result["config_restored_sha256"] == original_sha
if STATE.is_file():
    result["final_state"] = json.loads(STATE.read_text(encoding="utf-8"))
    (REPORT / "final_status.json").write_bytes(STATE.read_bytes())
result["finished_at"] = datetime.now().isoformat(timespec="seconds")
(REPORT / "run_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
