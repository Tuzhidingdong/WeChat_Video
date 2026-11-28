from __future__ import annotations
import hashlib, json, subprocess
from datetime import datetime
from pathlib import Path
ROOT=Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode\micro-visual-phase1")
R=ROOT/"outputs/pre_flow_cleanup_retest_20261128"
CFG=ROOT/"config/micro_visual.json"; STATE=ROOT/"runtime/micro_visual_last_status.json"
original=CFG.read_bytes(); sha0=hashlib.sha256(original).hexdigest()
suffix="cleanup_20261128_"+datetime.now().strftime("%H%M%S")
result={"started_at":datetime.now().isoformat(timespec="seconds"),"config_sha256_before":sha0,
        "temporary_suffix":suffix,"stop_before_flow_submit_unchanged":True,"bat_exit_code":None,"error":None}
try:
    cfg=json.loads(original.decode("utf-8")); cfg["job_id_suffix"]=suffix
    CFG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    p=subprocess.run(["cmd.exe","/c","Run_Literature_Micro_Visual.bat --scheduled"],cwd=ROOT,
                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace")
    (R/"LOGS/bat_stdout.log").write_text(p.stdout or "",encoding="utf-8")
    result["bat_exit_code"]=p.returncode
except Exception as exc:
    result["error"]=f"{type(exc).__name__}: {exc}"
finally:
    CFG.write_bytes(original)
    result["config_sha256_after"]=hashlib.sha256(CFG.read_bytes()).hexdigest()
    result["config_restored_ok"]=result["config_sha256_after"]==sha0
if STATE.is_file():
    result["final_state"]=json.loads(STATE.read_text(encoding="utf-8"))
    (R/"final_status.json").write_bytes(STATE.read_bytes())
result["finished_at"]=datetime.now().isoformat(timespec="seconds")
(R/"run_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2)[:4000])
