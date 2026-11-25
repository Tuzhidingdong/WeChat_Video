from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .article_source import ArticleSourceError, load_article_package
from .channels_uploader import UploadBlockedError, UploadUnknownError, upload_run_to_channels
from .fact_card import FactCardError, load_fact_card, read_json, validate_script_claim_links
from .topic_approval import TopicApprovalError, verify_fact_card_approval
from .pipeline import VISUAL_STRATEGIES, run_slice_a
from .upstream_article_source import (
    discover_upstream_literature_runs,
    materialize_upstream_article_package,
)


class DailyPipelineError(RuntimeError):
    pass


def _configured_timezone(timezone_name: str):
    """Resolve a configured timezone, with a narrow Windows-safe Shanghai fallback.

    Some Windows Python installations have no IANA timezone database installed.
    Shanghai has used UTC+08:00 without daylight-saving transitions since 1991,
    which is sufficient for the modern article/daily-job timestamps handled here.
    Other missing timezone names remain fail-closed.
    """
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        if timezone_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise DailyPipelineError(
            f"Invalid configured timezone: {timezone_name!r}; install/provide an IANA timezone database."
        ) from exc


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
    _configured_timezone(timezone_name)
    literature = config.get("literature", {})
    for field in ("upstream_daily_runs_dir", "upstream_account_key", "expected_public_account_biz_id"):
        if not str(literature.get(field) or "").strip():
            raise DailyPipelineError(f"literature.{field} is required for automatic upstream discovery.")
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
    zone = _configured_timezone(str(config["timezone"]))
    if requested:
        try:
            return date.fromisoformat(requested)
        except ValueError as exc:
            raise DailyPipelineError("--published-date must be YYYY-MM-DD.") from exc
    return datetime.now(zone).date() - timedelta(days=1)


def _article_date_window(config: dict[str, Any], requested: str | None) -> tuple[date, date, set[date]]:
    """Inclusive Asia/Shanghai date window for literature discovery.

    Default: today and the preceding six calendar days (7 calendar days total).
    An explicit --published-date is a single-day diagnostic override and never
    becomes the BAT default.
    """
    zone = _configured_timezone(str(config["timezone"]))
    if requested:
        try:
            day = date.fromisoformat(requested)
        except ValueError as exc:
            raise DailyPipelineError("--published-date must be YYYY-MM-DD.") from exc
        return day, day, {day}
    try:
        lookback = int((config.get("literature") or {}).get("lookback_days", 7))
    except (TypeError, ValueError):
        lookback = 7
    lookback = max(1, min(lookback, 365))
    today = datetime.now(zone).date()
    start = today - timedelta(days=lookback - 1)
    return start, today, {start + timedelta(days=index) for index in range(lookback)}


def _count_upstream_runs(upstream_root: Path, account_key: str) -> int:
    count = 0
    if not upstream_root.is_dir():
        return 0
    for date_dir in upstream_root.iterdir():
        account_dir = date_dir / account_key if date_dir.is_dir() else None
        if account_dir and account_dir.is_dir():
            count += sum(1 for run in account_dir.iterdir() if run.is_dir() and (run / "slot1.md").is_file())
    return count


def _rejection_categories(rejected: list[dict[str, str]]) -> dict[str, int]:
    categories: dict[str, int] = {}
    for item in rejected:
        reason = str(item.get("reason") or "")
        if "Cannot read" in reason:
            key = "incomplete_upstream_artifact"
        elif "No matching Video evidence bundle" in reason:
            key = "missing_independent_source_evidence"
        elif "publication" in reason.casefold() or "ct" in reason.casefold():
            key = "publication_time_evidence"
        else:
            key = "other"
        categories[key] = categories.get(key, 0) + 1
    return categories


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": candidate.get("article_id"),
        "appmsgid": candidate.get("appmsgid"),
        "title": candidate.get("title"),
        "published_at": candidate.get("published_at"),
        "local_date": candidate.get("local_date"),
        "source_run_id": candidate.get("source_run_id"),
    }


def _parse_published_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DailyPipelineError(f"Invalid published_at timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise DailyPipelineError("published_at must include an explicit timezone offset.")
    return parsed


def _published_local_date(value: str, timezone_name: str) -> date:
    return _parse_published_at(value).astimezone(_configured_timezone(timezone_name)).date()


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


def _usage_totals_from_tokens(tokens: dict[str, Any]) -> dict[str, int]:
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    return {
        "input": int(tokens.get("input") or 0),
        "output": int(tokens.get("output") or 0),
        "reasoning": int(tokens.get("reasoning") or 0),
        "cache_read": int(
            cache.get("read")
            or tokens.get("cache_read")
            or tokens.get("cacheRead")
            or 0
        ),
        "cache_write": int(
            cache.get("write")
            or tokens.get("cache_write")
            or tokens.get("cacheWrite")
            or tokens.get("cache_write_5m")
            or 0
        ) + int(cache.get("write_5m") or cache.get("write_1h") or 0),
    }


def _usage_result(
    *,
    session_ids: set[str],
    step_count: int,
    totals: dict[str, int],
    cost_total: float,
    cost_available: bool,
    source: str,
    complete: bool,
) -> dict[str, Any]:
    token_total = totals["input"] + totals["output"] + totals["reasoning"]
    return {
        "available": step_count > 0 and token_total > 0,
        "complete": complete,
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
        "source": source,
    }


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
    final_step_seen = False
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
        step_totals = _usage_totals_from_tokens(tokens)
        for key, value in step_totals.items():
            totals[key] += value
        if part.get("cost") is not None:
            try:
                cost_total += float(part["cost"])
                cost_available = True
            except (TypeError, ValueError):
                pass
        step_count += 1
        if str(part.get("reason") or "").casefold() == "stop":
            final_step_seen = True
    # Keep normal input/output/reasoning usage distinct from cache I/O.
    # In particular, cache read/write is not added to the primary token total.
    return _usage_result(
        session_ids=session_ids,
        step_count=step_count,
        totals=totals,
        cost_total=cost_total,
        cost_available=cost_available,
        source="OpenCode --format json step_finish events",
        complete=final_step_seen,
    )


def _extract_exported_model_usage(
    exported: dict[str, Any],
    *,
    fallback_session_id: str,
) -> dict[str, Any]:
    """Read token/cost totals from OpenCode's durable session export."""
    session_info = exported.get("info")
    if not isinstance(session_info, dict):
        session_info = exported.get("session") if isinstance(exported.get("session"), dict) else {}
    session_id = str(session_info.get("id") or fallback_session_id).strip()
    totals = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }
    step_count = 0
    cost_total = 0.0
    cost_available = False
    messages = exported.get("messages")
    if not isinstance(messages, list):
        raise DailyPipelineError("OpenCode session export has no messages array.")
    for message in messages:
        if not isinstance(message, dict):
            continue
        info = message.get("info") if isinstance(message.get("info"), dict) else {}
        if str(info.get("role") or "").casefold() != "assistant":
            continue
        parts = message.get("parts") if isinstance(message.get("parts"), list) else []
        finish_parts = [
            part for part in parts
            if isinstance(part, dict) and str(part.get("type") or "").casefold() in {"step-finish", "step_finish"}
        ]
        if finish_parts:
            for part in finish_parts:
                tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
                part_totals = _usage_totals_from_tokens(tokens)
                for key, value in part_totals.items():
                    totals[key] += value
                if part.get("cost") is not None:
                    try:
                        cost_total += float(part["cost"])
                        cost_available = True
                    except (TypeError, ValueError):
                        pass
                step_count += 1
            continue

        # Some OpenCode versions retain the aggregated usage on assistant
        # message.info even when the terminal step-finish part is absent.
        tokens = info.get("tokens") if isinstance(info.get("tokens"), dict) else {}
        if tokens:
            message_totals = _usage_totals_from_tokens(tokens)
            for key, value in message_totals.items():
                totals[key] += value
            if info.get("cost") is not None:
                try:
                    cost_total += float(info["cost"])
                    cost_available = True
                except (TypeError, ValueError):
                    pass
            step_count += 1

    if step_count == 0:
        raise DailyPipelineError("OpenCode session export contains no assistant token usage.")
    return _usage_result(
        session_ids={session_id} if session_id else set(),
        step_count=step_count,
        totals=totals,
        cost_total=cost_total,
        cost_available=cost_available,
        source="OpenCode opencode session export",
        complete=True,
    )


def _export_model_usage(
    executable: str,
    session_id: str,
    project_root: Path,
    *,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Read durable usage metadata without retaining the exported transcript."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="wechat-video-opencode-usage-",
            suffix=".json",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            completed = subprocess.run(
                [executable, "session", "export", session_id],
                cwd=project_root,
                stdout=handle,
                stderr=subprocess.PIPE,
                timeout=max(15, min(timeout_seconds, 120)),
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        if completed.returncode != 0:
            return None
        exported = json.loads(temporary_path.read_text(encoding="utf-8"))
        if not isinstance(exported, dict):
            return None
        return _extract_exported_model_usage(
            exported,
            fallback_session_id=session_id,
        )
    except (
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        DailyPipelineError,
    ):
        return None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


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
    if not usage.get("complete") and usage.get("session_ids"):
        # OpenCode may finish a run without flushing its final step_finish
        # event to JSONL. Recover only the usage counters from the durable
        # session export, and delete the temporary transcript immediately.
        exported_usage = _export_model_usage(
            resolved,
            str(usage["session_ids"][0]),
            project_root,
            timeout_seconds=int(opencode_cfg.get("timeout_seconds", 1800)),
        )
        if exported_usage and exported_usage.get("available"):
            usage = exported_usage
        else:
            usage["complete"] = False
            usage["fallback_export"] = "unavailable"
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
            f"cost_usd={usage.get('cost') if usage.get('cost_available') else 'not-reported'} "
            f"complete={usage.get('complete', False)} source={usage.get('source')}"
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
                "published_at", "canonical_url", "upstream_run_dir", "upstream_run_id",
                "publication_time_provenance", "rejected_package_count",
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
    requested_date: str | None = None,
) -> dict[str, Any]:
    lit = config["literature"]
    upstream_root = _project_path(project_root, str(lit["upstream_daily_runs_dir"]))
    outputs = _project_path(project_root, str(config.get("outputs_root", "outputs")))
    window_start, window_end, window_dates = _article_date_window(config, requested_date)
    candidates, rejected = discover_upstream_literature_runs(
        upstream_root,
        publication_evidence_root=outputs,
        account_key=str(lit["upstream_account_key"]),
        account_name=str(config["upload"]["account_name"]),
        expected_biz_id=str(lit["expected_public_account_biz_id"]),
        target_date=window_end,
        timezone_name=str(config["timezone"]),
        target_dates=window_dates,
    )
    seen_ids = _existing_article_ids(outputs)
    eligible: list[dict[str, Any]] = []
    rendered: list[dict[str, Any]] = []
    for candidate in candidates:
        if str(candidate["article_id"]) in seen_ids:
            rendered.append(candidate)
            continue
        eligible.append(candidate)
    deferred = eligible[1:]
    expiring = [item for item in deferred if item.get("local_date") == window_start.isoformat()]
    window_info = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "lookback_days": len(window_dates),
        "timezone": str(config["timezone"]),
        "upstream_root": str(upstream_root),
        "upstream_run_count": _count_upstream_runs(upstream_root, str(lit["upstream_account_key"])),
        "found_article_count": len(candidates),
        "evidence_complete_candidate_count": len(candidates),
        "already_rendered_count": len(rendered),
        "rejected_count": len(rejected),
        "rejection_categories": _rejection_categories(rejected),
        "rejected_packages": rejected[:30],
        "deferred_candidates": [_candidate_summary(item) for item in deferred],
        "expiring_candidates": [_candidate_summary(item) for item in expiring],
    }
    if not eligible:
        return {
            "state": "SKIPPED_NO_ELIGIBLE_ARTICLE",
            "published_date": published_date.isoformat(),
            **window_info,
            "candidate_count": len(candidates),
            "eligible_candidate_count": 0,
            "selected_article": None,
            "reason": "No evidence-complete, formally published article within the rolling window that has not already been produced.",
            "automatic_publication": False,
        }

    selected = eligible[0]
    # Validate the explicit model before writing even the Video-local materialized
    # package. The upstream WeChat_control run remains strictly read-only.
    _planner_preflight(config)
    package_root = _project_path(
        project_root,
        str(lit.get("materialized_package_root", "runtime/upstream_article_packages")),
    )
    package_dir = materialize_upstream_article_package(selected, package_root)
    selected["path"] = package_dir

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
        selected_package=str(package_dir),
        upstream_run_dir=str(selected["source_run_dir"]),
        upstream_run_id=str(selected["source_run_id"]),
        selected_title=selected["title"],
        selected_article=_candidate_summary(selected),
        published_at=selected["published_at"],
        canonical_url=selected["canonical_url"],
        selection_policy=str(lit.get("selection_policy") or "newest_first"),
        candidate_count=len(eligible),
        candidate_article_ids=[item["article_id"] for item in eligible],
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        lookback_days=len(window_dates),
        upstream_run_count=window_info["upstream_run_count"],
        found_article_count=window_info["found_article_count"],
        rejected_count=len(rejected),
        rejection_categories=window_info["rejection_categories"],
        deferred_candidates=window_info["deferred_candidates"],
        expiring_candidates=window_info["expiring_candidates"],
        rejected_packages=rejected[:30],
        source_record_sha256=selected["markdown_sha256"],
        publication_time_provenance=selected["publication_time_details"],
    )
    package = load_article_package(package_dir)
    article = package["article"]
    planner_dir = _project_path(project_root, str(config.get("runtime_root", "runtime/daily_pipelines"))) / "planner" / published_date.isoformat() / selected["article_id"]
    planner_dir.mkdir(parents=True, exist_ok=True)
    attachments = [
        package_dir / "article.json",
        package_dir / "article.md",
        package_dir / "images.json",
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
        article_dir=package_dir,
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
    # An absent or not-yet-populated topic pool is a normal safe-skip
    # condition, not a pipeline exception. Never infer or generate a topic
    # when the governed Fact Card registry is unavailable.
    if not cards_root.is_dir():
        return [], [{
            "fact_card": str(cards_root),
            "reason": "fact_cards_directory_missing_no_approved_topics",
        }]
    if not sources_path.is_file():
        return [], [{
            "fact_card": str(sources_path),
            "reason": "fact_card_sources_missing_no_approved_topics",
        }]
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


def _load_selected_popularization_card(
    project_root: Path,
    card_path: Path,
    sources_path: Path,
    *,
    expected_card_sha256: str,
    expected_source_sha256: str,
) -> dict[str, Any]:
    """Recheck approval and source hashes immediately before content planning."""
    if _sha256(card_path) != expected_card_sha256:
        raise DailyPipelineError("Selected Fact Card changed after eligibility selection.")
    if _sha256(sources_path) != expected_source_sha256:
        raise DailyPipelineError("Fact Card sources changed after eligibility selection.")
    card, _, pending = load_fact_card(
        card_path,
        sources_path,
        allow_pending_review=True,
    )
    approval = verify_fact_card_approval(project_root, card_path, sources_path)
    if approval is None:
        raise DailyPipelineError("Selected Fact Card no longer has a verifiable human approval.")
    if pending and approval.get("approval_type") != "local_hash_bound":
        raise DailyPipelineError(
            "A pending Fact Card is eligible only with its exact hash-bound local approval record."
        )
    return card


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
    sources_path = _project_path(project_root, str(pop["sources_file"]))
    card = _load_selected_popularization_card(
        project_root,
        Path(selected["path"]),
        sources_path,
        expected_card_sha256=str(selected["fact_card_sha256"]),
        expected_source_sha256=str(selected["source_record_sha256"]),
    )
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


def inspect_daily_literature_sources(
    project_root: Path,
    *,
    published_date: str | None = None,
) -> dict[str, Any]:
    """Read-only discovery report; never materializes packages or starts production."""
    project_root = project_root.resolve()
    config = _load_config(project_root)
    window_start, window_end, window_dates = _article_date_window(config, published_date)
    lit = config["literature"]
    upstream_root = _project_path(project_root, str(lit["upstream_daily_runs_dir"]))
    evidence_root = _project_path(project_root, str(config.get("outputs_root", "outputs")))
    candidates, rejected = discover_upstream_literature_runs(
        upstream_root,
        publication_evidence_root=evidence_root,
        account_key=str(lit["upstream_account_key"]),
        account_name=str(config["upload"]["account_name"]),
        expected_biz_id=str(lit["expected_public_account_biz_id"]),
        target_date=window_end,
        timezone_name=str(config["timezone"]),
        target_dates=window_dates,
    )
    seen_ids = _existing_article_ids(evidence_root)
    visible_candidates = []
    for candidate in candidates:
        details = dict(candidate["publication_time_details"])
        visible_candidates.append({
            "article_id": candidate["article_id"],
            "appmsgid": candidate["appmsgid"],
            "title": candidate["title"],
            "published_at": candidate["published_at"],
            "local_date": candidate["local_date"],
            "source_run_id": candidate["source_run_id"],
            "source_run_dir": str(candidate["source_run_dir"]),
            "slot1_markdown_sha256": candidate["markdown_sha256"],
            "canonical_url": candidate["canonical_url"],
            "publication_time_field_path": candidate["publication_time_field_path"],
            "publication_time_provenance": details,
            "verified_local_image_count": len(candidate.get("image_assets") or []),
            "image_asset_source": candidate.get("image_asset_source"),
            "verified_video_image_count": candidate.get("verified_video_image_count", 0),
            "publication_evidence_dir": str(candidate.get("publication_evidence_dir") or ""),
            "already_rendered": str(candidate["article_id"]) in seen_ids,
        })
    unseen = [item for item in visible_candidates if not item["already_rendered"]]
    deferred = unseen[1:]
    expiring = [item for item in deferred if item.get("local_date") == window_start.isoformat()]
    return {
        "state": "SOURCE_CANDIDATES_FOUND" if unseen else "SKIPPED_NO_ELIGIBLE_ARTICLE",
        "mode": "READ_ONLY_DISCOVERY",
        "published_date": window_end.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "lookback_days": len(window_dates),
        "timezone": str(config["timezone"]),
        "upstream_daily_runs_root": str(upstream_root),
        "publication_evidence_root": str(evidence_root),
        "upstream_run_count": _count_upstream_runs(upstream_root, str(lit["upstream_account_key"])),
        "found_article_count": len(candidates),
        "candidate_count": len(visible_candidates),
        "eligible_candidate_count": len(unseen),
        "already_rendered_count": len(visible_candidates) - len(unseen),
        "rejected_count": len(rejected),
        "rejection_categories": _rejection_categories(rejected),
        "selected_candidate": unseen[0] if unseen else None,
        "deferred_candidates": deferred,
        "expiring_candidates": expiring,
        "candidates": visible_candidates,
        "rejected_run_count": len(rejected),
        "rejected_runs": rejected[:50],
        "side_effects": {
            "materialized_package": False,
            "open_code_started": False,
            "tts_started": False,
            "manim_started": False,
            "ffmpeg_started": False,
            "upload_attempted": False,
        },
    }


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
            result = _run_literature_locked(
                project_root, config, published_date=target, requested_date=published_date
            )
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
    zone = _configured_timezone(str(config["timezone"]))
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
    pop_date = datetime.now(_configured_timezone(str(config["timezone"]))).date()
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
