from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .article_source import ArticleSourceError, load_article_package
from .channels_uploader import UploadBlockedError, UploadUnknownError, upload_run_to_channels
from .fact_card import FactCardError, load_fact_card, read_json, validate_script_claim_links
from .topic_approval import TopicApprovalError, verify_fact_card_approval
from .pipeline import VISUAL_STRATEGIES, run_slice_a


class DailyPipelineError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DailyPipelineError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DailyPipelineError(f"Expected a JSON object in {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _load_config(project_root: Path) -> dict[str, Any]:
    path = project_root / "configs" / "daily_pipelines.json"
    config = _read_json(path)
    if config.get("schema_version") != 1:
        raise DailyPipelineError("Unsupported daily_pipelines.json schema_version.")
    timezone_name = str(config.get("timezone") or "")
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise DailyPipelineError(f"Invalid configured timezone: {timezone_name!r}") from exc
    if not config.get("literature", {}).get("article_inbox_dir"):
        raise DailyPipelineError("literature.article_inbox_dir is required.")
    if not config.get("popularization", {}).get("fact_cards_dir"):
        raise DailyPipelineError("popularization.fact_cards_dir is required.")
    if config.get("upload", {}).get("automatic_publication") is not False:
        raise DailyPipelineError("Daily pipelines must keep automatic_publication=false.")
    if config.get("upload", {}).get("draft_only") is not True:
        raise DailyPipelineError("Daily pipelines require draft_only=true.")
    return config


@contextmanager
def _pipeline_lock(project_root: Path, config: dict[str, Any]) -> Iterator[None]:
    """Cross-process lock: one renderer/uploader may operate the shared Edge profile at a time."""
    lock_path = _project_path(project_root, str(config.get("runtime_root", "runtime/daily_pipelines"))) / "pipeline.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = max(1, int(config.get("lock_wait_seconds", 3600)))
    handle = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    start = time.monotonic()
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (OSError, BlockingIOError):
                if time.monotonic() - start >= timeout:
                    raise DailyPipelineError(f"Timed out waiting for daily pipeline lock: {lock_path}")
                time.sleep(0.25)
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _target_article_date(config: dict[str, Any], requested: str | None) -> date:
    zone = ZoneInfo(str(config["timezone"]))
    if requested:
        try:
            return date.fromisoformat(requested)
        except ValueError as exc:
            raise DailyPipelineError("--published-date must be YYYY-MM-DD.") from exc
    return datetime.now(zone).date() - timedelta(days=1)


def _parse_published_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DailyPipelineError(f"Invalid published_at timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise DailyPipelineError("published_at must include an explicit timezone offset.")
    return parsed


def _published_local_date(value: str, timezone_name: str) -> date:
    return _parse_published_at(value).astimezone(ZoneInfo(timezone_name)).date()


def _existing_article_ids(outputs_root: Path) -> set[str]:
    seen: set[str] = set()
    if not outputs_root.is_dir():
        return seen
    for manifest_path in outputs_root.glob("*/article_summary_manifest.json"):
        try:
            manifest = _read_json(manifest_path)
        except DailyPipelineError:
            continue
        article_id = str(manifest.get("article_id") or "")
        if article_id:
            seen.add(article_id)
    return seen


def _discover_literature_packages(
    inbox: Path,
    outputs_root: Path,
    target_date: date,
    timezone_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    if not inbox.is_dir():
        raise DailyPipelineError(f"Literature article inbox does not exist: {inbox}")
    seen_ids = _existing_article_ids(outputs_root)
    for article_json in sorted(inbox.rglob("article.json")):
        package_dir = article_json.parent
        try:
            package = load_article_package(package_dir)
            article = package["article"]
            local_date = _published_local_date(str(article["published_at"]), timezone_name)
            if local_date != target_date:
                continue
            article_id = str(article["article_id"])
            if article_id in seen_ids:
                rejected.append({"path": str(package_dir), "reason": "article_already_has_generated_run"})
                continue
            candidates.append({
                "path": package_dir,
                "article_id": article_id,
                "title": str(article["title"]),
                "published_at": str(article["published_at"]),
                "local_date": local_date.isoformat(),
                "markdown_sha256": str(package["markdown_sha256"]),
                "image_count": len(package["images"]),
            })
        except (ArticleSourceError, DailyPipelineError) as exc:
            rejected.append({"path": str(package_dir), "reason": str(exc)})
    candidates.sort(
        key=lambda item: (
            _parse_published_at(str(item["published_at"])).timestamp(),
            str(item["article_id"]),
        ),
        reverse=True,
    )
    return candidates, rejected


def _extract_model_usage(stdout: str) -> dict[str, Any]:
    session_ids: set[str] = set()
    step_count = 0
    totals = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }
    cost_total = 0.0
    cost_available = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        session_id = str(event.get("sessionID") or "").strip()
        if session_id:
            session_ids.add(session_id)
        if event.get("type") != "step_finish":
            continue
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        totals["input"] += int(tokens.get("input") or 0)
        totals["output"] += int(tokens.get("output") or 0)
        totals["reasoning"] += int(tokens.get("reasoning") or 0)
        totals["cache_read"] += int(
            cache.get("read")
            or tokens.get("cache_read")
            or tokens.get("cacheRead")
            or 0
        )
        totals["cache_write"] += int(
            cache.get("write")
            or tokens.get("cache_write")
            or tokens.get("cacheWrite")
            or tokens.get("cache_write_5m")
            or 0
        ) + int(cache.get("write_5m") or cache.get("write_1h") or 0)
        if part.get("cost") is not None:
            try:
                cost_total += float(part["cost"])
                cost_available = True
            except (TypeError, ValueError):
                pass
        step_count += 1
    # Keep normal input/output/reasoning usage distinct from cache I/O.
    # In particular, cache read/write is not added to the primary token total.
    token_total = totals["input"] + totals["output"] + totals["reasoning"]
    return {
        "available": step_count > 0 and token_total > 0,
        "session_ids": sorted(session_ids),
        "step_count": step_count,
        "tokens": {
            **totals,
            "total": token_total,
            "total_including_cache_io": token_total + totals["cache_read"] + totals["cache_write"],
        },
        "cost": round(cost_total, 8) if cost_available else None,
        "cost_currency": "USD" if cost_available else None,
        "cost_available": cost_available,
        "source": "OpenCode --format json step_finish events",
    }


def _extract_model_text(stdout: str) -> str:
    """Accept plain JSON or OpenCode JSONL text events; reject empty/ambiguous output."""
    chunks: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
        elif event.get("type") in {"text", "message"} and isinstance(event.get("text"), str):
            chunks.append(event["text"])
        elif event.get("type") == "step_finish":
            message = event.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    chunks.extend(
                        str(item.get("text"))
                        for item in content
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    )
    text_value = "".join(chunks).strip() if chunks else stdout.strip()
    if not text_value:
        raise DailyPipelineError("OpenCode returned no text content.")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text_value):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text_value[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
    raise DailyPipelineError("OpenCode output did not contain one valid JSON object.")


def _planner_preflight(config: dict[str, Any]) -> tuple[str, str, str]:
    opencode_cfg = config.get("opencode") or {}
    executable = str(opencode_cfg.get("executable") or "opencode")
    agent = str(opencode_cfg.get("agent") or "daily-content-planner")
    model = str(opencode_cfg.get("model") or "").strip()
    if bool(opencode_cfg.get("require_explicit_model", True)) and not model:
        raise DailyPipelineError(
            "No OpenCode model is explicitly configured. Set opencode.model in "
            "configs/daily_pipelines.json before automated content planning; "
            "the daily pipeline will not silently inherit a machine-default model."
        )
    resolved = shutil.which(executable)
    if not resolved and Path(executable).is_file():
        resolved = str(Path(executable).resolve())
    if not resolved:
        raise DailyPipelineError(f"OpenCode executable not found on PATH: {executable}")
    return resolved, agent, model


def _run_content_planner(
    project_root: Path,
    config: dict[str, Any],
    *,
    prompt: str,
    attachments: list[Path],
) -> dict[str, Any]:
    opencode_cfg = config.get("opencode") or {}
    resolved, agent, model = _planner_preflight(config)
    print(
        f"[CONTENT PLANNER] role={agent} model={model} "
        f"project={project_root} attachments={len(attachments)}"
    )
    cmd = [resolved, "run", "--format", "json", "--agent", agent]
    if model:
        cmd.extend(["--model", model])
    for path in attachments:
        if not path.is_file():
            raise DailyPipelineError(f"Planner attachment does not exist: {path}")
        cmd.extend(["--file", str(path.resolve())])
    cmd.append(prompt)
    try:
        completed = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60, int(opencode_cfg.get("timeout_seconds", 1800))),
            check=False,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise DailyPipelineError("OpenCode content planning timed out; no video rendering was started.") from exc
    if completed.returncode != 0:
        raise DailyPipelineError(
            f"OpenCode content planning failed with exit code {completed.returncode}: "
            f"{completed.stderr[-2000:]}"
        )
    raw = _extract_model_text(completed.stdout)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DailyPipelineError(f"Planner JSON is invalid: {exc}") from exc
    if not isinstance(result, dict):
        raise DailyPipelineError("Planner must return a JSON object.")
    usage = _extract_model_usage(completed.stdout)
    result["_planner_run_metadata"] = {
        "agent": agent,
        "model": model,
        "project_root": str(project_root),
        "attachments": [str(path.resolve()) for path in attachments],
        "usage": usage,
    }
    if usage.get("available"):
        print(
            "[CONTENT PLANNER USAGE] "
            f"session={','.join(usage.get('session_ids', [])) or 'unavailable'} "
            f"steps={usage.get('step_count')} "
            f"tokens={usage.get('tokens', {}).get('total')} "
            f"cost_usd={usage.get('cost') if usage.get('cost_available') else 'not-reported'}"
        )
    else:
        print("[CONTENT PLANNER USAGE] Token/cost telemetry was not supplied by this OpenCode run.")
    return result


def _cjk_count(value: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def _literature_prompt(article: dict[str, Any], article_sha256: str) -> str:
    return f"""
Create one source-grounded Chinese one-minute literature-reading video summary.
The attached article.json, article.md and images.json are the only allowed evidence.
Return exactly one JSON object with this schema:
{{
 "schema_version":1,
 "article_id":"{article['article_id']}",
 "source_article_sha256":"{article_sha256}",
 "summary_title":"...",
 "channels_title":"6-16 Chinese characters",
 "core_thesis":"...",
 "thesis_claim_ids":["C1"],
 "claims":[{{"claim_id":"C1","statement":"...","source_excerpt":"exact contiguous excerpt from article.md"}}],
 "speech_units":[{{"unit_id":"U01","spoken_text":"...","display_text":"...","claim_ids":["C1"],"visual_trigger_ids":["B01"],"pause_after_ms":500}}],
 "beats":[
  {{"beat_id":"B01","unit_id":"U01","kind":"hook","headline":"...","body":"...","claim_ids":["C1"]}},
  {{"beat_id":"B02","unit_id":"U02","kind":"image","headline":"...","body":"...","image_ids":["IMG01"],"claim_ids":["C1"]}},
  {{"beat_id":"B03","unit_id":"U03","kind":"stat","headline":"...","body":"...","stat_value":"...","stat_label":"...","claim_ids":["C1"]}},
  {{"beat_id":"B04","unit_id":"U04","kind":"compare","headline":"...","left":{{"label":"...","detail":"..."}},"right":{{"label":"...","detail":"..."}},"claim_ids":["C1"]}},
  {{"beat_id":"B05","unit_id":"U05","kind":"mechanism","headline":"...","body":"...","steps":["...","...","..."],"claim_ids":["C1"]}},
  {{"beat_id":"B06","unit_id":"U06","kind":"quote","headline":"...","quote":"exact article quote","claim_ids":["C1"]}},
  {{"beat_id":"B07","unit_id":"U07","kind":"takeaway","headline":"...","body":"...","claim_ids":["C1"]}}
 ],
 "cover_duration_ms":1500,
 "outro_duration_ms":1800,
 "source_line":"成核生长 · 文献精读"
}}
Requirements:
- Use 5-8 speech units and exactly one beat per unit. The sample beat kinds above are examples; select only what fits the source, do not invent data/quotes.
- Every claim's source_excerpt must be exact, contiguous text from article.md.
- Every claim must be referenced by at least one speech unit; thesis_claim_ids must exist.
- Every beat beat_id must be listed in its unit visual_trigger_ids.
- Use only image IDs from images.json; if no relevant local image, do not invent image IDs.
- Numeric values/units/conditions/comparisons/limitations/uncertainty must be source-grounded.
- Keep 222-235 Chinese Han characters in concatenated spoken_text. Do not pad or remove evidence just to hit the count; if impossible return {{"error":"CONTENT_BUDGET_CONFLICT","reason":"..."}}.
- Use plain Chinese before technical terms; avoid promotional wording.
- No source URL or link field. The app adds the fixed end card: 更多详细解读见【成核生长】同名公众号.
- Return JSON only.
""".strip()


def _popularization_prompt(card: dict[str, Any], angle: str) -> str:
    return f"""
Create one English-narrated science-popularization script with Simplified Chinese subtitles.
Use only the attached approved Fact Card and sources.json. Do not create any new scientific claim.
The required editorial_angle_id is exactly "{angle}".
Return exactly one JSON object:
{{
 "script_id":"{card.get('fact_card_id','FACT')}-DAILY",
 "editorial_angle_id":"{angle}",
 "title":"...",
 "language":"en-US",
 "target_duration_seconds":[55,65],
 "rhythm_blocks":[
  {{"block_id":"HOOK","target_ms":[0,6000],"purpose":"open with the central question"}},
  {{"block_id":"EXPLANATION","target_ms":[6000,42000],"purpose":"explain evidence and mechanism"}},
  {{"block_id":"LIMITS","target_ms":[42000,54000],"purpose":"state conditions and limits"}},
  {{"block_id":"TAKEAWAY","target_ms":[54000,65000],"purpose":"conclude"}}
 ],
 "speech_units":[
  {{"unit_id":"U01","raw_text":"...","display_text":"...","spoken_text":"...","display_text_zh":"...","claim_ids":["C1"],"visual_trigger_ids":["TRIGGER"],"rhythm_block_id":"HOOK","pause_after_ms":250}}
 ],
 "pronunciation_review_text":"..."
}}
Requirements:
- Use 10-22 concise English speech units suitable for 55-65 seconds and Chinese subtitles.
- Keep every English unit and its Chinese subtitle semantically equivalent.
- Every unit must link only to actual claim IDs in the card.
- Do not create numerical values, units, mechanisms, materials, experiments or conclusions absent from the Fact Card.
- Preserve all stated conditions, caveats and uncertainty.
- The script must fit the exact approved editorial angle; use only the model strategy already registered for that angle.
- Return JSON only. If the card is unsuitable for a short explainer, return {{"error":"CONTENT_NOT_SUITABLE","reason":"..."}}.
""".strip()


def _job_paths(project_root: Path, config: dict[str, Any], local_date: date) -> Path:
    root = _project_path(project_root, str(config.get("runtime_root", "runtime/daily_pipelines")))
    return root / "jobs" / f"{local_date.isoformat()}"


def _start_job(path: Path, *, content_type: str, local_date: date, source_id: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = _read_json(path)
        state = str(existing.get("state") or "")
        if state == "DRAFT_SAVED":
            return {**existing, "already_completed": True}
        raise DailyPipelineError(
            f"Daily job already exists with state {state or 'UNKNOWN'}; refusing automatic rerun. "
            "Inspect the saved job record and reconcile any upload uncertainty first."
        )
    record = {
        "schema_version": 1,
        "content_type": content_type,
        "local_date": local_date.isoformat(),
        "source_id": source_id,
        "state": "SELECTED",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "automatic_publication": False,
    }
    _atomic_json(path, record)
    return record


def _update_job(path: Path, record: dict[str, Any], state: str, **fields: Any) -> dict[str, Any]:
    record = {**record, **fields, "state": state, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    _atomic_json(path, record)
    return record


def _find_upload_job_for_run(
    project_root: Path,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    run_dir_text = str(record.get("run_dir") or "")
    if not run_dir_text:
        return None
    run_id = Path(run_dir_text).name
    config_path = project_root / "config" / "channels_upload.json"
    try:
        upload_config = _read_json(config_path)
        jobs_root = _project_path(
            project_root, str(upload_config.get("jobs_dir") or "runtime/upload_jobs")
        )
    except DailyPipelineError:
        return None
    if not jobs_root.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for path in jobs_root.glob("*.json"):
        try:
            item = _read_json(path)
        except DailyPipelineError:
            continue
        if str(item.get("source_run_id") or path.stem) == run_id:
            matches.append(item)
    if not matches:
        exact = jobs_root / f"{run_id}.json"
        if exact.is_file():
            try:
                matches.append(_read_json(exact))
            except DailyPipelineError:
                pass
    matches.sort(key=lambda item: int(item.get("upload_attempt", 1)))
    return matches[-1] if matches else None


def _mark_daily_job(
    project_root: Path,
    config: dict[str, Any],
    local_date: date,
    content_type: str,
    state: str,
    error: str,
) -> str:
    job_path = _job_paths(project_root, config, local_date) / f"{content_type}.json"
    if not job_path.is_file():
        return state
    try:
        record = _read_json(job_path)
        existing_state = str(record.get("state") or "")
        if existing_state == "DRAFT_SAVED":
            return "DRAFT_SAVED"
        upload_job = _find_upload_job_for_run(project_root, record)
        upload_state = str((upload_job or {}).get("state") or "")
        if upload_state == "DRAFT_SAVED":
            _update_job(
                job_path,
                record,
                "DRAFT_SAVED",
                upload_job_id=upload_job.get("job_id"),
                verified_draft=upload_job.get("verified_draft"),
                account_name=upload_job.get("account_name"),
                automatic_publication=False,
                recovered_from_upload_journal=True,
                error=error,
            )
            return "DRAFT_SAVED"
        if upload_state == "BLOCKED_LINK_NOT_PERSISTED":
            final_state = "BLOCKED_LINK_NOT_PERSISTED"
        elif upload_state in {"SAVE_REQUESTED", "UPLOAD_UNKNOWN", "UPLOADING", "PREPARED"}:
            final_state = "UPLOAD_UNKNOWN"
        elif upload_state in {"CREATED", "FAILED_BEFORE_SAVE", "BLOCKED_DUPLICATE_TITLE"}:
            # The uploader journal proves no draft-save result was confirmed.
            # Do not automatically retry; report a known pre-save block/failure.
            final_state = "FAILED"
        else:
            # No upload journal generally means failure occurred before the
            # uploader created a job. An existing daily UPLOADING state without
            # its matching uploader record remains uncertain.
            final_state = "UPLOAD_UNKNOWN" if existing_state in {"UPLOADING", "UPLOAD_UNKNOWN"} else state
        if existing_state != "DRAFT_SAVED":
            _update_job(job_path, record, final_state, error=error)
        return final_state
    except Exception:
        # The uploader's own job journal remains the authoritative recovery
        # record if this higher-level daily summary cannot be updated.
        return state


def _record_daily_report(
    project_root: Path,
    config: dict[str, Any],
    local_date: date,
    results: dict[str, Any],
) -> None:
    reports_root = _project_path(
        project_root, str(config.get("runtime_root", "runtime/daily_pipelines"))
    ) / "reports"
    path = reports_root / f"{local_date.isoformat()}.json"
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = _read_json(path)
        except DailyPipelineError:
            existing = {}
    jobs = dict(existing.get("jobs") or {})
    for content_type in ("literature", "popularization"):
        value = results.get(content_type)
        if not isinstance(value, dict):
            continue
        jobs[content_type] = {
            key: value.get(key)
            for key in (
                "state", "source_id", "selected_title", "run_dir", "video_path",
                "video_sha256", "upload_job_id", "account_name", "verified_draft",
                "error", "reason", "candidate_count", "approved_card_count", "planner_metadata",
            )
            if key in value
        }
    _atomic_json(path, {
        "schema_version": 1,
        "timezone": str(config.get("timezone") or "Asia/Shanghai"),
        "local_date": local_date.isoformat(),
        "jobs": jobs,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "automatic_publication": False,
    })


def _write_run_manifest(run_dir: Path, record: dict[str, Any]) -> None:
    manifest = run_dir / "daily_pipeline_manifest.json"
    _atomic_json(manifest, {
        "schema_version": 1,
        "content_type": record.get("content_type"),
        "local_date": record.get("local_date"),
        "source_id": record.get("source_id"),
        "job_state": record.get("state"),
        "source_record_sha256": record.get("source_record_sha256"),
        "summary_or_script_sha256": record.get("summary_or_script_sha256"),
        "video_sha256": record.get("video_sha256"),
        "upload_job_id": record.get("upload_job_id"),
        "automatic_publication": False,
    })


def _run_literature_locked(
    project_root: Path,
    config: dict[str, Any],
    *,
    published_date: date,
) -> dict[str, Any]:
    lit = config["literature"]
    inbox = _project_path(project_root, str(lit["article_inbox_dir"]))
    outputs = _project_path(project_root, str(config.get("outputs_root", "outputs")))
    candidates, rejected = _discover_literature_packages(
        inbox, outputs, published_date, str(config["timezone"])
    )
    if not candidates:
        return {
            "state": "SKIPPED_NO_ELIGIBLE_ARTICLE",
            "published_date": published_date.isoformat(),
            "candidate_count": 0,
            "rejected_package_count": len(rejected),
            "rejected_packages": rejected[:30],
            "reason": "No complete, published, previous-day literature package is available.",
            "automatic_publication": False,
        }
    selected = candidates[0]
    _planner_preflight(config)
    job_path = _job_paths(project_root, config, published_date) / "literature.json"
    record = _start_job(
        job_path,
        content_type="literature",
        local_date=published_date,
        source_id=selected["article_id"],
    )
    if record.get("already_completed"):
        return record
    record = _update_job(
        job_path, record, "CONTENT_PLANNING",
        selected_package=str(selected["path"]),
        selected_title=selected["title"],
        selection_policy="latest_published_at",
        candidate_count=len(candidates),
        candidate_article_ids=[item["article_id"] for item in candidates],
        rejected_packages=rejected[:30],
        source_record_sha256=selected["markdown_sha256"],
    )
    package = load_article_package(Path(selected["path"]))
    article = package["article"]
    planner_dir = _project_path(project_root, str(config.get("runtime_root", "runtime/daily_pipelines"))) / "planner" / published_date.isoformat() / selected["article_id"]
    planner_dir.mkdir(parents=True, exist_ok=True)
    attachments = [
        Path(selected["path"]) / "article.json",
        Path(selected["path"]) / "article.md",
        Path(selected["path"]) / "images.json",
    ]
    summary = _run_content_planner(
        project_root, config,
        prompt=_literature_prompt(article, str(package["markdown_sha256"])),
        attachments=attachments,
    )
    if summary.get("error"):
        raise DailyPipelineError(f"Literature content planning blocked: {summary.get('error')}: {summary.get('reason','')}")
    if summary.get("article_id") != article["article_id"]:
        raise DailyPipelineError("Planner summary article_id does not match the selected article.")
    if summary.get("source_article_sha256") != package["markdown_sha256"]:
        raise DailyPipelineError("Planner summary source hash does not match the selected article.")
    spoken = "".join(str(unit.get("spoken_text") or "") for unit in summary.get("speech_units", []))
    count = _cjk_count(spoken)
    if not 222 <= count <= 235:
        raise DailyPipelineError(f"Planner summary has {count} Chinese Han characters; expected 222–235.")
    summary["cover_duration_ms"] = int(lit.get("cover_duration_ms", 1500))
    summary["outro_duration_ms"] = int(lit.get("outro_duration_ms", 1800))
    summary["source_line"] = "成核生长 · 文献精读"
    summary_path = planner_dir / "summary.json"
    _atomic_json(summary_path, summary)
    _atomic_json(planner_dir / "planner_run_report.json", summary["_planner_run_metadata"])
    record = _update_job(
        job_path, record, "CONTENT_READY",
        summary_path=str(summary_path),
        summary_or_script_sha256=_sha256(summary_path),
        spoken_cjk_characters=count,
        planner_metadata=summary.get("_planner_run_metadata"),
    )
    from .article_summary import run_article_summary
    run_dir = run_article_summary(
        project_root,
        article_dir=Path(selected["path"]),
        summary_path=summary_path,
        output_root=outputs,
    )
    record = _update_job(
        job_path, record, "VIDEO_QA_PASSED",
        run_dir=str(run_dir),
        video_path=str((run_dir / "final.mp4").resolve()),
        video_sha256=_sha256(run_dir / "final.mp4"),
        technical_qa=_read_json(run_dir / "qa_report.json").get("overall_status"),
        content_upload_eligible=_read_json(run_dir / "content_qa_report.json").get("upload_eligible"),
    )
    if record.get("technical_qa") != "PASS" or record.get("content_upload_eligible") is not True:
        raise DailyPipelineError("Literature output did not meet technical and content upload gates.")
    record = _update_job(job_path, record, "UPLOADING")
    upload = upload_run_to_channels(project_root, run_dir)
    if upload.get("state") == "BLOCKED_LINK_NOT_PERSISTED":
        record = _update_job(
            job_path, record, "BLOCKED_LINK_NOT_PERSISTED",
            upload_job_id=upload.get("job_id"),
            verified_draft=upload.get("verified_draft"),
            account_name=upload.get("account_name"),
            extended_link_persistence=upload.get("extended_link_persistence"),
            blocking_reason=upload.get("blocking_reason"),
            automatic_publication=False,
        )
        _write_run_manifest(run_dir, record)
        return record
    if upload.get("state") != "DRAFT_SAVED":
        raise DailyPipelineError(f"Uploader returned unexpected state: {upload.get('state')}")
    record = _update_job(
        job_path, record, "DRAFT_SAVED",
        upload_job_id=upload.get("job_id"),
        verified_draft=upload.get("verified_draft"),
        account_name=upload.get("account_name"),
        extended_link_persistence=upload.get("extended_link_persistence"),
        automatic_publication=False,
    )
    _write_run_manifest(run_dir, record)
    return record


def _popularization_duration_gate(run_dir: Path, target_seconds: list[Any]) -> dict[str, Any]:
    timeline_path = run_dir / "audio_timing.json"
    if not timeline_path.is_file():
        report = {
            "status": "FAIL",
            "reason": "audio_timing.json is missing.",
            "target_seconds": target_seconds,
        }
    else:
        timeline = _read_json(timeline_path)
        measured = float(timeline.get("total_duration_seconds", 0))
        if not isinstance(target_seconds, list) or len(target_seconds) != 2:
            raise DailyPipelineError("popularization.target_duration_seconds must be [minimum, maximum].")
        minimum = float(target_seconds[0])
        maximum = float(target_seconds[1])
        report = {
            "status": "PASS" if minimum <= measured <= maximum else "FAIL",
            "measured_seconds": round(measured, 3),
            "minimum_seconds": minimum,
            "maximum_seconds": maximum,
            "measurement_authority": "audio_timing.json measured PCM sample clock",
        }
    _atomic_json(run_dir / "daily_duration_gate.json", report)
    return report


def _approved_popularization_cards(project_root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    pop = config["popularization"]
    cards_root = _project_path(project_root, str(pop["fact_cards_dir"]))
    sources_path = _project_path(project_root, str(pop["sources_file"]))
    if not cards_root.is_dir():
        raise DailyPipelineError(f"Fact Card directory does not exist: {cards_root}")
    if not sources_path.is_file():
        raise DailyPipelineError(f"Fact Card sources file does not exist: {sources_path}")
    sources = _read_json(sources_path)
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for card_path in sorted(cards_root.glob("*.json")):
        if card_path.resolve() == sources_path.resolve():
            continue
        try:
            card, _, pending = load_fact_card(card_path, sources_path, allow_pending_review=True)
            approval = verify_fact_card_approval(project_root, card_path, sources_path)
            # A hash-bound local approval is valid even when the tracked card
            # remains marked DRAFT_PENDING_USER_REVIEW. Never infer approval
            # from the status field alone.
            if pending and approval is None:
                rejected.append({"fact_card": str(card_path), "reason": "not_approved"})
                continue
            if approval is None:
                rejected.append({"fact_card": str(card_path), "reason": "approval_record_not_verified"})
                continue
            if str(card.get("editorial_angle_id") or "") not in VISUAL_STRATEGIES:
                rejected.append({"fact_card": str(card_path), "reason": "no_registered_visual_strategy"})
                continue
            approved.append({
                "path": card_path,
                "fact_card_id": str(card["fact_card_id"]),
                "title": str(card.get("title") or ""),
                "channels_title": str(card.get("channels_title") or ""),
                "editorial_angle_id": str(card["editorial_angle_id"]),
                "approved_at": str(card.get("approved_at") or approval.get("approved_at") or ""),
                "fact_card_sha256": _sha256(card_path),
                "source_record_sha256": _sha256(sources_path),
            })
        except (FactCardError, TopicApprovalError, DailyPipelineError, ValueError) as exc:
            rejected.append({"fact_card": str(card_path), "reason": str(exc)})
    approved.sort(key=lambda item: (item["approved_at"], item["fact_card_id"], item["editorial_angle_id"]))
    return approved, rejected


def _read_history(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "used_fact_card_ids": [], "jobs": []}
    value = _read_json(path)
    if value.get("schema_version") != 1:
        raise DailyPipelineError("Unsupported popularization history schema.")
    return value


def _run_popularization_locked(
    project_root: Path,
    config: dict[str, Any],
    *,
    local_date: date,
) -> dict[str, Any]:
    pop = config["popularization"]
    approved, rejected = _approved_popularization_cards(project_root, config)
    history_path = _project_path(project_root, str(pop["history_file"]))
    history = _read_history(history_path)
    used = {str(item) for item in history.get("used_fact_card_ids", [])}
    eligible = [item for item in approved if item["fact_card_id"] not in used]
    if not eligible:
        return {
            "state": "SKIPPED_NO_APPROVED_TOPIC",
            "local_date": local_date.isoformat(),
            "approved_card_count": len(approved),
            "unused_approved_card_count": 0,
            "rejected_card_count": len(rejected),
            "rejected_cards": rejected[:30],
            "reason": "No unused, human-approved Fact Card with a registered visual strategy is available.",
            "automatic_publication": False,
        }
    selected = eligible[0]
    _planner_preflight(config)
    job_path = _job_paths(project_root, config, local_date) / "popularization.json"
    record = _start_job(
        job_path,
        content_type="popularization",
        local_date=local_date,
        source_id=selected["fact_card_id"],
    )
    if record.get("already_completed"):
        return record
    # Consume the topic once selected; failures must not silently recycle it.
    if selected["fact_card_id"] not in used:
        history["used_fact_card_ids"] = sorted(used | {selected["fact_card_id"]})
        history.setdefault("jobs", []).append({
            "local_date": local_date.isoformat(),
            "fact_card_id": selected["fact_card_id"],
            "fact_card_sha256": selected["fact_card_sha256"],
            "selected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        _atomic_json(history_path, history)
    record = _update_job(
        job_path, record, "CONTENT_PLANNING",
        fact_card_path=str(selected["path"]),
        fact_card_sha256=selected["fact_card_sha256"],
        source_record_sha256=selected["source_record_sha256"],
        editorial_angle_id=selected["editorial_angle_id"],
    )
    card, _, pending = load_fact_card(
        Path(selected["path"]),
        _project_path(project_root, str(pop["sources_file"])),
        allow_pending_review=False,
    )
    if pending:
        raise DailyPipelineError("A selected Fact Card became unapproved after selection.")
    sources_path = _project_path(project_root, str(pop["sources_file"]))
    planner_dir = _project_path(project_root, str(config.get("runtime_root", "runtime/daily_pipelines"))) / "planner" / local_date.isoformat() / selected["fact_card_id"]
    planner_dir.mkdir(parents=True, exist_ok=True)
    script = _run_content_planner(
        project_root, config,
        prompt=_popularization_prompt(card, selected["editorial_angle_id"]),
        attachments=[Path(selected["path"]), sources_path],
    )
    if script.get("error"):
        raise DailyPipelineError(f"Popularization content planning blocked: {script.get('error')}: {script.get('reason','')}")
    if str(script.get("editorial_angle_id") or "") != selected["editorial_angle_id"]:
        raise DailyPipelineError("Generated script changed the approved Fact Card editorial angle.")
    validate_script_claim_links(script, card)
    script_path = planner_dir / "script.json"
    _atomic_json(script_path, script)
    record = _update_job(
        job_path, record, "CONTENT_READY",
        script_path=str(script_path),
        summary_or_script_sha256=_sha256(script_path),
        planner_metadata=script.get("_planner_run_metadata"),
    )
    _atomic_json(planner_dir / "planner_run_report.json", script["_planner_run_metadata"])
    run_dir = run_slice_a(
        project_root,
        card_path=Path(selected["path"]),
        script_path=script_path,
        output_root=Path(str(config.get("outputs_root", "outputs"))),
        allow_pending_review=False,
    )
    qa = _read_json(run_dir / "qa_report.json")
    duration_gate = _popularization_duration_gate(
        run_dir,
        list(pop.get("target_duration_seconds") or [55, 65]),
    )
    qa_passed = qa.get("overall_status") == "PASS"
    duration_passed = duration_gate.get("status") == "PASS"
    record = _update_job(
        job_path, record, "VIDEO_QA_PASSED" if qa_passed and duration_passed else "VIDEO_QA_FAILED",
        run_dir=str(run_dir),
        video_path=str((run_dir / "final.mp4").resolve()),
        video_sha256=_sha256(run_dir / "final.mp4"),
        technical_qa=qa.get("overall_status"),
        duration_gate=duration_gate,
    )
    if not qa_passed:
        raise DailyPipelineError("Popularization technical QA did not PASS.")
    if not duration_passed:
        raise DailyPipelineError(
            "Popularization measured programme duration is outside the configured "
            f"{duration_gate.get('minimum_seconds')}–{duration_gate.get('maximum_seconds')} second range."
        )
    record = _update_job(job_path, record, "UPLOADING")
    upload = upload_run_to_channels(project_root, run_dir)
    if upload.get("state") != "DRAFT_SAVED":
        raise DailyPipelineError(f"Uploader returned unexpected state: {upload.get('state')}")
    record = _update_job(
        job_path, record, "DRAFT_SAVED",
        upload_job_id=upload.get("job_id"),
        verified_draft=upload.get("verified_draft"),
        account_name=upload.get("account_name"),
        automatic_publication=False,
    )
    _write_run_manifest(run_dir, record)
    return record


def run_daily_literature(
    project_root: Path,
    *,
    published_date: str | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    config = _load_config(project_root)
    if not config["literature"].get("enabled", True):
        return {"state": "DISABLED", "content_type": "literature"}
    target = _target_article_date(config, published_date)
    with _pipeline_lock(project_root, config):
        try:
            result = _run_literature_locked(project_root, config, published_date=target)
        except UploadUnknownError as exc:
            recovered_state = _mark_daily_job(
                project_root, config, target, "literature", "UPLOAD_UNKNOWN", str(exc)
            )
            result = {"state": recovered_state, "content_type": "literature", "error": str(exc)}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            failed_state = _mark_daily_job(project_root, config, target, "literature", "FAILED", message)
            result = {"state": failed_state, "content_type": "literature", "error": message}
        _record_daily_report(project_root, config, target, {"literature": result})
        return result


def run_daily_popularization(
    project_root: Path,
    *,
    local_date: str | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    config = _load_config(project_root)
    if not config["popularization"].get("enabled", True):
        return {"state": "DISABLED", "content_type": "popularization"}
    zone = ZoneInfo(str(config["timezone"]))
    target = date.fromisoformat(local_date) if local_date else datetime.now(zone).date()
    with _pipeline_lock(project_root, config):
        try:
            result = _run_popularization_locked(project_root, config, local_date=target)
        except UploadUnknownError as exc:
            recovered_state = _mark_daily_job(
                project_root, config, target, "popularization", "UPLOAD_UNKNOWN", str(exc)
            )
            result = {"state": recovered_state, "content_type": "popularization", "error": str(exc)}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            failed_state = _mark_daily_job(project_root, config, target, "popularization", "FAILED", message)
            result = {"state": failed_state, "content_type": "popularization", "error": message}
        _record_daily_report(project_root, config, target, {"popularization": result})
        return result


def run_daily_two_videos(project_root: Path, *, published_date: str | None = None) -> dict[str, Any]:
    """Run both independent jobs sequentially under one shared lock and continue after one fails."""
    project_root = project_root.resolve()
    config = _load_config(project_root)
    literature_date = _target_article_date(config, published_date)
    pop_date = datetime.now(ZoneInfo(str(config["timezone"]))).date()
    results: dict[str, Any] = {
        "schema_version": 1,
        "automatic_publication": False,
        "account_name": str(config["upload"]["account_name"]),
    }
    with _pipeline_lock(project_root, config):
        for key, enabled, callback, target in (
            ("literature", bool(config["literature"].get("enabled", True)), _run_literature_locked, literature_date),
            ("popularization", bool(config["popularization"].get("enabled", True)), _run_popularization_locked, pop_date),
        ):
            if not enabled:
                results[key] = {"state": "DISABLED"}
                continue
            try:
                if key == "literature":
                    results[key] = callback(project_root, config, published_date=target)
                else:
                    results[key] = callback(project_root, config, local_date=target)
            except UploadUnknownError as exc:
                recovered_state = _mark_daily_job(
                    project_root, config, target, key, "UPLOAD_UNKNOWN", str(exc)
                )
                results[key] = {"state": recovered_state, "error": str(exc)}
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                failed_state = _mark_daily_job(project_root, config, target, key, "FAILED", message)
                results[key] = {"state": failed_state, "error": message}
    states = [
        results[key].get("state")
        for key in ("literature", "popularization")
        if isinstance(results.get(key), dict)
    ]
    acceptable = {"DRAFT_SAVED", "SKIPPED_NO_ELIGIBLE_ARTICLE", "SKIPPED_NO_APPROVED_TOPIC", "DISABLED"}
    if states and all(state == "DRAFT_SAVED" for state in states):
        results["overall_state"] = "DRAFTS_SAVED"
    elif states and all(state in acceptable for state in states):
        results["overall_state"] = "COMPLETED_WITH_SKIPS"
    else:
        results["overall_state"] = "PARTIAL_OR_BLOCKED"
    _record_daily_report(project_root, config, pop_date, results)
    if literature_date != pop_date:
        _record_daily_report(project_root, config, literature_date, {
            "literature": results.get("literature", {}),
        })
    return results
