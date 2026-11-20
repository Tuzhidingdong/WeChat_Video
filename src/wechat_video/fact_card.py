from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FactCardError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FactCardError(f"找不到 JSON 文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise FactCardError(f"JSON 格式错误：{path}，{exc}") from exc
    if not isinstance(value, dict):
        raise FactCardError(f"JSON 根节点必须是对象：{path}")
    return value


def load_fact_card(
    card_path: Path,
    source_path: Path,
    *,
    allow_pending_review: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    card = read_json(card_path)
    source_doc = read_json(source_path)
    status = str(card.get("approval_status", "")).upper()
    pending = status != "APPROVED"

    if pending and not allow_pending_review:
        raise FactCardError(
            "Fact Card 尚未获人工批准。默认生产路径已阻止继续。"
            "审阅样片可使用 --review-sample 生成，但必须保持不可发布标记。"
        )
    if status == "APPROVED" and not (
        card.get("approved_by") and card.get("approved_at")
    ):
        raise FactCardError(
            "Fact Card 标记为 APPROVED，但缺少 approved_by / approved_at；拒绝信任该状态。"
        )

    claims = card.get("claims")
    sources = source_doc.get("sources")
    if not isinstance(claims, list) or not claims:
        raise FactCardError("Fact Card 必须包含非空 claims 列表。")
    if not isinstance(sources, list) or not sources:
        raise FactCardError("来源记录必须包含非空 sources 列表。")

    source_ids = {
        str(item.get("source_id"))
        for item in sources
        if isinstance(item, dict) and item.get("source_id")
    }
    claim_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise FactCardError("每条 claim 必须是 JSON 对象。")
        claim_id = str(claim.get("claim_id", "")).strip()
        if not claim_id or claim_id in claim_ids:
            raise FactCardError(f"claim_id 缺失或重复：{claim_id!r}")
        claim_ids.add(claim_id)
        if not claim.get("statement"):
            raise FactCardError(f"{claim_id} 缺少 statement。")
        linked_sources = set(claim.get("source_ids") or [])
        if not linked_sources or not linked_sources.issubset(source_ids):
            raise FactCardError(
                f"{claim_id} 的来源引用为空或未在 source record 中定义：{sorted(linked_sources)}"
            )
        if claim.get("evidence_status") not in {
            "FULL_TEXT_LOCATED",
            "ABSTRACT_DIRECT_SUPPORT",
        }:
            raise FactCardError(
                f"{claim_id} 的证据状态不足以用于科学动画：{claim.get('evidence_status')}"
            )
        if claim.get("caveats") is None:
            raise FactCardError(f"{claim_id} 必须显式记录适用条件/局限。")

    return card, source_doc, pending


def validate_script_claim_links(
    script: dict[str, Any],
    card: dict[str, Any],
) -> None:
    valid_claims = {str(x["claim_id"]) for x in card["claims"]}
    units = script.get("speech_units")
    if not isinstance(units, list) or not units:
        raise FactCardError("脚本必须包含非空 speech_units。")
    seen: set[str] = set()
    for unit in units:
        unit_id = str(unit.get("unit_id", "")).strip()
        if not unit_id or unit_id in seen:
            raise FactCardError(f"speech unit ID 缺失或重复：{unit_id!r}")
        seen.add(unit_id)
        for field in ("raw_text", "display_text", "spoken_text"):
            if not str(unit.get(field, "")).strip():
                raise FactCardError(f"{unit_id} 缺少 {field}。")
        refs = set(unit.get("claim_ids") or [])
        if not refs or not refs.issubset(valid_claims):
            raise FactCardError(
                f"{unit_id} 引用了不存在的 claim：{sorted(refs - valid_claims)}"
            )
        if not unit.get("visual_trigger_ids"):
            raise FactCardError(f"{unit_id} 未定义 visual_trigger_ids。")
