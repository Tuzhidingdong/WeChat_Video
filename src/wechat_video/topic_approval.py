"""One-time, hash-bound approval for a scientific Fact Card."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fact_card import load_fact_card, read_json


class TopicApprovalError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def approval_path(project_root: Path, fact_card_id: str) -> Path:
    safe_id = "".join(ch for ch in fact_card_id if ch.isalnum() or ch in "._-")
    if not safe_id or safe_id != fact_card_id:
        raise TopicApprovalError("Invalid fact_card_id for local approval path.")
    return project_root.resolve() / "runtime" / "topic_approvals" / f"{safe_id}.json"


def verify_fact_card_approval(
    project_root: Path,
    card_path: Path,
    source_path: Path,
) -> dict[str, Any] | None:
    """Return a verified local/tracked approval, None if a pending card is unapproved."""
    project_root = project_root.resolve()
    card_path = card_path.resolve()
    source_path = source_path.resolve()
    card, _, pending = load_fact_card(
        card_path, source_path, allow_pending_review=True
    )
    if not pending:
        return {
            "approval_type": "tracked_fact_card",
            "fact_card_id": card["fact_card_id"],
            "approved_by": card.get("approved_by"),
            "approved_at": card.get("approved_at"),
            "fact_card_sha256": _sha256(card_path),
            "source_record_sha256": _sha256(source_path),
        }

    path = approval_path(project_root, str(card["fact_card_id"]))
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TopicApprovalError(f"Local topic approval record is unreadable: {path.name}") from exc
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise TopicApprovalError(f"Unsupported local topic approval record: {path.name}")
    if record.get("fact_card_id") != card["fact_card_id"]:
        raise TopicApprovalError("Local topic approval record references a different Fact Card.")
    if record.get("fact_card_sha256") != _sha256(card_path):
        raise TopicApprovalError("Fact Card changed after approval; explicit re-approval is required.")
    if record.get("source_record_sha256") != _sha256(source_path):
        raise TopicApprovalError("Source record changed after approval; explicit re-approval is required.")
    if not record.get("approved_by") or not record.get("approved_at"):
        raise TopicApprovalError("Local topic approval record is missing approver metadata.")
    record["approval_type"] = "local_hash_bound"
    return record


def approve_fact_card(
    project_root: Path,
    card_path: Path,
    *,
    approved_by: str,
    confirmation: str | None = None,
    input_fn=input,
) -> dict[str, Any]:
    """Record one explicit human approval for a Fact Card and its source record."""
    project_root = project_root.resolve()
    card_path = card_path.resolve()
    fact_cards_root = (project_root / "fact_cards").resolve()
    if not card_path.is_relative_to(fact_cards_root):
        raise TopicApprovalError("Only a Fact Card under project fact_cards/ can be approved.")
    if not approved_by.strip():
        raise TopicApprovalError("approved_by must not be empty.")
    source_path = fact_cards_root / "sources.json"
    card, sources, _ = load_fact_card(
        card_path, source_path, allow_pending_review=True
    )
    fact_card_id = str(card.get("fact_card_id") or "").strip()
    if not fact_card_id:
        raise TopicApprovalError("Fact Card has no fact_card_id.")

    target = approval_path(project_root, fact_card_id)
    card_hash = _sha256(card_path)
    source_hash = _sha256(source_path)
    if target.is_file():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if (
            existing.get("fact_card_sha256") == card_hash
            and existing.get("source_record_sha256") == source_hash
        ):
            raise TopicApprovalError("This exact Fact Card/source pair is already approved locally.")

    print("\n即将一次性批准该科学选题进入本地 Verified Topic Pool：")
    print(f"Fact Card ID：{fact_card_id}")
    print(f"主题：{card.get('title', '')}")
    print(f"视频号短标题：{card.get('channels_title', '(未设置)')}")
    print(f"核心问题：{card.get('scientific_question', '')}")
    print(f"适用范围：{card.get('scope', '')}")
    print("\n科学主张：")
    for claim in card.get("claims", []):
        print(f"- [{claim.get('claim_id', '')}] {claim.get('statement', '')}")
        if claim.get("conditions"):
            print(f"  条件：{'；'.join(str(x) for x in claim['conditions'])}")
        if claim.get("caveats"):
            print(f"  局限：{'；'.join(str(x) for x in claim['caveats'])}")
    print("\n来源：")
    source_by_id = {
        str(source.get("source_id")): source
        for source in sources.get("sources", [])
        if isinstance(source, dict)
    }
    needed_ids = sorted({
        str(source_id)
        for claim in card.get("claims", [])
        for source_id in (claim.get("source_ids") or [])
    })
    for source_id in needed_ids:
        source = source_by_id.get(source_id, {})
        print(f"- {source_id}: {source.get('title', '')} {source.get('doi', '')}".strip())
    print("\n此批准只对上面这份 Fact Card 和 source record 的精确 SHA-256 内容有效。")
    phrase = f"APPROVE FACT CARD {fact_card_id}"
    response = confirmation if confirmation is not None else input_fn(
        f"确认已审阅科学主张、适用条件和来源？输入 {phrase}："
    )
    if response.strip() != phrase:
        raise TopicApprovalError("Approval phrase did not match; no topic approval was written.")

    record = {
        "schema_version": 1,
        "fact_card_id": fact_card_id,
        "fact_card_sha256": card_hash,
        "source_record_sha256": source_hash,
        "approved_by": approved_by.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "approval_status_at_review": card.get("approval_status"),
        "approval_scope": "this exact Fact Card and source record; one-time approval for daily draft production",
        "daily_video_policy": "strict_qa_pass_then_unpublished_draft; user_publishes_manually",
    }
    _write_json_atomic(target, record)
    return record
