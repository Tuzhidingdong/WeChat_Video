import hashlib, json, shutil, sqlite3
from pathlib import Path
ROOT=Path(r"C:\Users\Administrator\AppData\Local\Temp\opencode\micro-visual-phase1")
R=ROOT/"outputs/pre_flow_no_evidence_gate_20261128"
JOB=ROOT/"outputs/20261128_100000884_0_micro_visual_nogate_20261128_202757"
SUM=ROOT/"outputs/mv7/20261128_203040_883208_100000884_0_micro_visual_content_summary"
PLAN=ROOT/"runtime/micro_visual_article/20261128_100000884_0_micro_visual_nogate_20261128_202757/planner"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
for name,p in [("flow_prompt.txt",JOB/"flow_prompt.txt"),("micro_visual_plan.json",JOB/"micro_visual_plan.json"),
               ("visual_theme_binding.json",JOB/"visual_theme_binding.json"),("source_evidence.json",JOB/"source_evidence.json"),
               ("visual_theme.json",SUM/"visual_theme.json"),("content_summary.json",SUM/"summary.json"),
               ("content_manifest.json",SUM/"article_summary_manifest.json"),("content_qa.json",SUM/"content_qa_report.json"),
               ("planner_summary.json",PLAN/"summary.json"),("planner_report.json",PLAN/"planner_run_report.json")]:
    if p.is_file(): shutil.copy2(p,R/name)

# stage A raw output from session, if needed
sid="ses_ddeddd1ea9ffeSi0eAv5fHawZAT"
DB=Path.home()/".local/share/opencode/opencode.db"
con=sqlite3.connect(f"file:{DB.as_posix()}?mode=ro",uri=True)
row=con.execute("SELECT data FROM session_part WHERE session_id=? AND type='text' AND message_id IN (SELECT id FROM session_message WHERE session_id=? AND type='assistant') ORDER BY ordinal",(sid,sid)).fetchone()
con.close()
if row:
    (R/"STAGE_A_RESULT.json").write_text(json.dumps(json.loads(json.loads(row[0])["text"]),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

lines=["# ARTIFACT SHA256"]
for p in sorted(R.rglob("*")):
    if p.is_file() and p.suffix in (".json",".txt",".log"): lines.append(f"{sha(p)}  {p.relative_to(R)}")
(R/"ARTIFACT_SHA256.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")

prompt=(JOB/"flow_prompt.txt").read_text(encoding="utf-8").strip()
print("PROMPT_SHA",hashlib.sha256(prompt.encode()).hexdigest())
print(prompt)
print("--- binding ---")
print(json.dumps(json.loads((JOB/"visual_theme_binding.json").read_text(encoding="utf-8")),ensure_ascii=False,indent=2)[:1600])
print("--- theme selected ---")
t=json.loads((SUM/"visual_theme.json").read_text(encoding="utf-8"))
print("selected",t.get("selected_candidate_id"))
for c in t.get("candidates",[]):
    print(c.get("candidate_id"),[c.get(f,{}).get("text") for f in ("subject","action","environment")])
print("--- planner report ---")
print(json.dumps(json.loads((PLAN/"planner_run_report.json").read_text(encoding="utf-8")),ensure_ascii=False)[:600])
