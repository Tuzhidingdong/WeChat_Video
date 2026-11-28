import hashlib, json, shutil
from pathlib import Path
ROOT=Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode\micro-visual-phase1")
R=ROOT/"outputs/pre_flow_cleanup_retest_20261128"
job_dirs=sorted([p for p in (ROOT/"outputs").glob("*cleanup_20261128_*") if p.is_dir()], key=lambda p:p.stat().st_mtime)
job=job_dirs[-1]
mv_dirs=sorted([p for p in (ROOT/"outputs").glob("mv*") if p.is_dir() and p.name.startswith("mv")], key=lambda p:p.stat().st_mtime)
summary=max([p for p in mv_dirs if list(p.glob("*micro_visual_content_summary"))], key=lambda p:p.stat().st_mtime)
sr=max(summary.glob("*micro_visual_content_summary"), key=lambda p:p.stat().st_mtime)
for name,src in [
 ("visual_theme_binding.json",job/"visual_theme_binding.json"),
 ("FINAL_FLOW_PROMPT.txt",job/"flow_prompt.txt"),
 ("STAGE_A_RESULT_RAW.txt",sr/"visual_theme_raw.txt"),
 ("STAGE_A_RESULT.json",sr/"visual_theme_raw.json"),
 ("stage_a_session.json",sr/"stage_a_session.json"),
 ("stage_a_normalized.json",sr/"visual_theme.json"),
 ("content_summary.json",sr/"summary.json"),
 ("content_manifest.json",sr/"article_summary_manifest.json"),
 ("micro_visual_plan.json",job/"micro_visual_plan.json"),
]:
    if src.is_file(): shutil.copy2(src,R/name)

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
binding=json.loads((R/"visual_theme_binding.json").read_text(encoding="utf-8"))
prompt_bytes=(R/"FINAL_FLOW_PROMPT.txt").read_bytes()
prompt_text=(R/"FINAL_FLOW_PROMPT.txt").read_text(encoding="utf-8").strip()
session=json.loads((R/"stage_a_session.json").read_text(encoding="utf-8"))
(R/"STAGE_A_SESSION.md").write_text(
 "# Stage A 真实 Session\n\n" + json.dumps(session,ensure_ascii=False,indent=2) + "\n", encoding="utf-8")
lines=["# ARTIFACT SHA256 (raw file bytes)"]
for p in sorted(R.rglob("*")):
    if p.is_file() and p.name != "ARTIFACT_SHA256.txt": lines.append(f"{sha(p)}  {p.relative_to(R)}")
lines.append(f"{hashlib.sha256(prompt_text.encode()).hexdigest()}  normalized_prompt_text_sha256  (FINAL_FLOW_PROMPT.txt stripped trailing newline)")
(R/"ARTIFACT_SHA256.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
print("job",job.name)
print("summary_run",sr.name)
print("binding",json.dumps(binding,ensure_ascii=False,indent=2))
print("session",json.dumps(session,ensure_ascii=False,indent=2)[:600])
print("prompt_file_sha256",sha(R/"FINAL_FLOW_PROMPT.txt"))
print("normalized_prompt_text_sha256",hashlib.sha256(prompt_text.encode()).hexdigest())
