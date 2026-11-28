import hashlib, json
from pathlib import Path
ROOT=Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode\micro-visual-phase1")
R=ROOT/"outputs/pre_flow_cleanup_retest_20261128"
b=json.loads((R/"visual_theme_binding.json").read_text(encoding="utf-8"))
p=(R/"FINAL_FLOW_PROMPT.txt").read_bytes()
text=p.decode("utf-8").strip()
print("binding", b["flow_prompt_sha256"])
print("file_bytes_sha", hashlib.sha256(p).hexdigest())
print("text_sha", hashlib.sha256(text.encode("utf-8")).hexdigest())
print("text_len", len(text))
