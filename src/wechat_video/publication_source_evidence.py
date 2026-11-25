"""Structured publication-source evidence for literature articles.

This module records and validates evidence that was OBSERVED in a visible browser
and then exported as a structured JSON file. It never opens a browser, performs
HTTP requests, reads credentials, or calls WeChat APIs. Its only write is the
atomic addition of one evidence file to an already identified Video output run.

The independent source (official album page URL + observed DOM relation) is kept
separate from the verified article URL. A verified article URL alone is never
accepted as its own independent source.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .article_source import validate_canonical_article_url

EVIDENCE_FILENAME = "publication_source_evidence.json"
_AUTH_KEYS = {"token", "access_token", "auth", "code", "pass_ticket"}
_IDENTITY_KEYS = ("__biz", "mid", "idx", "sn", "chksm")
_ORIGINAL_EVIDENCE_FILES = (
    "url_verification_evidence.json",
    "upload_preflight_report.json",
    "article_read_count_probe.json",
    "article_summary_manifest.json",
    "source_record.json",
)


class PublicationSourceEvidenceError(ValueError):
    """Raised when publication-source evidence is absent, malformed or inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationSourceEvidenceError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicationSourceEvidenceError(f"Expected a JSON object in {path}.")
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def article_url_identity(url: Any) -> dict[str, str]:
    """Return the stable article identity query fields, ignoring tracking parameters."""
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query, keep_blank_values=True)
    return {
        key: str(query[key][0])
        for key in _IDENTITY_KEYS
        if query.get(key) and str(query[key][0])
    }


def _query_value(url: Any, key: str) -> str:
    query = parse_qs(urlparse(str(url or "")).query, keep_blank_values=True)
    values = query.get(key) or []
    return str(values[0]) if values else ""


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PublicationSourceEvidenceError(f"{label} is required.")
    return text


def _validate_album_url(url: Any, *, expected_biz_id: str) -> str:
    text = _require_text(url, "source_page.url")
    parsed = urlparse(text)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "mp.weixin.qq.com"
        or parsed.path != "/mp/appmsgalbum"
        or not (query.get("__biz") and query.get("album_id"))
    ):
        raise PublicationSourceEvidenceError(
            "source_page.url must be an observed https mp.weixin.qq.com/mp/appmsgalbum URL."
        )
    if any(key.casefold() in _AUTH_KEYS for key in query):
        raise PublicationSourceEvidenceError("source_page.url must not contain authentication parameters.")
    biz = str(query["__biz"][0])
    if biz != expected_biz_id:
        raise PublicationSourceEvidenceError(
            f"source_page.url __biz {biz!r} does not match expected {expected_biz_id!r}."
        )
    return text


def validate_observation(observation: dict[str, Any], *, expected_biz_id: str) -> dict[str, Any]:
    """Validate a browser-exported observation without fabricating any value."""
    if int(observation.get("schema_version") or 0) != 1:
        raise PublicationSourceEvidenceError("Observation schema_version must be 1.")
    if observation.get("read_only") is not True:
        raise PublicationSourceEvidenceError("Observation must explicitly record read_only=true.")
    method = _require_text(observation.get("capture_method"), "capture_method")
    if method != "visible_browser_dom_observation":
        raise PublicationSourceEvidenceError(f"Unsupported capture_method {method!r}.")

    observed_at = _require_text(observation.get("observed_at"), "observed_at")
    try:
        parsed_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationSourceEvidenceError("observed_at must be an ISO-8601 timestamp.") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise PublicationSourceEvidenceError("observed_at must contain an explicit timezone offset.")

    identity = observation.get("identity")
    if not isinstance(identity, dict):
        raise PublicationSourceEvidenceError("identity must be an object.")
    for key in ("article_id", "appmsgid", "account_name", "title", "markdown_sha256"):
        _require_text(identity.get(key), f"identity.{key}")
    sha = str(identity["markdown_sha256"]).strip().casefold()
    if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        raise PublicationSourceEvidenceError("identity.markdown_sha256 must be a SHA-256 digest.")

    source_page = observation.get("source_page")
    if not isinstance(source_page, dict):
        raise PublicationSourceEvidenceError("source_page must be an object.")
    album_url = _validate_album_url(source_page.get("url"), expected_biz_id=expected_biz_id)

    entry = observation.get("article_entry")
    if not isinstance(entry, dict):
        raise PublicationSourceEvidenceError("article_entry must be an object.")
    title_text = _require_text(entry.get("title_text"), "article_entry.title_text")
    if title_text != str(identity["title"]).strip():
        raise PublicationSourceEvidenceError("Observed entry title does not match the upstream article title.")
    link_attribute = _require_text(entry.get("link_attribute"), "article_entry.link_attribute")
    href_raw = _require_text(entry.get("link_href_raw"), "article_entry.link_href_raw")
    resolved = validate_canonical_article_url(entry.get("resolved_article_url"))
    href_identity = article_url_identity(href_raw)
    resolved_identity = article_url_identity(resolved)
    if not href_identity or href_identity != resolved_identity:
        raise PublicationSourceEvidenceError(
            "The observed raw href and the browser-resolved article URL do not identify the same article."
        )
    if resolved_identity.get("__biz") != expected_biz_id:
        raise PublicationSourceEvidenceError("Resolved article URL __biz does not match the target account.")
    data_msgid = _require_text(entry.get("data_msgid"), "article_entry.data_msgid")
    data_itemidx = _require_text(entry.get("data_itemidx"), "article_entry.data_itemidx")
    if data_msgid != resolved_identity.get("mid"):
        raise PublicationSourceEvidenceError("Observed data_msgid conflicts with the article URL mid.")
    if data_itemidx != resolved_identity.get("idx"):
        raise PublicationSourceEvidenceError("Observed data_itemidx conflicts with the article URL idx.")
    if data_itemidx != "1":
        raise PublicationSourceEvidenceError("Literature Slot 1 entry must have data_itemidx=1.")

    relation = observation.get("dom_relation")
    if not isinstance(relation, dict):
        raise PublicationSourceEvidenceError("dom_relation must be an object.")
    container_tag = _require_text(relation.get("container_tag"), "dom_relation.container_tag")
    link_tag = _require_text(relation.get("link_tag"), "dom_relation.link_tag")
    container_attrs = relation.get("container_attributes")
    link_attrs = relation.get("link_attributes")
    if not isinstance(container_attrs, dict) or not isinstance(link_attrs, dict):
        raise PublicationSourceEvidenceError("dom_relation attributes must be objects.")
    if link_attribute not in container_attrs:
        raise PublicationSourceEvidenceError(
            "dom_relation.container_attributes does not contain the observed link_attribute."
        )
    if str(container_attrs.get(link_attribute)) != href_raw:
        raise PublicationSourceEvidenceError("Observed link attribute value differs from link_href_raw.")
    if str(container_attrs.get("data-title") or "").strip() != title_text:
        raise PublicationSourceEvidenceError("Observed container data-title differs from the article title.")
    if str(container_attrs.get("data-msgid") or "").strip() != data_msgid:
        raise PublicationSourceEvidenceError("Observed container data-msgid differs from article_entry.data_msgid.")
    if str(container_attrs.get("data-itemidx") or "").strip() != data_itemidx:
        raise PublicationSourceEvidenceError("Observed container data-itemidx differs from article_entry.data_itemidx.")
    if not any(str(value).strip() for value in link_attrs.values()):
        raise PublicationSourceEvidenceError("dom_relation.link_attributes must contain observed values.")

    screenshot = observation.get("evidence_screenshot")
    if screenshot is not None and not isinstance(screenshot, str):
        raise PublicationSourceEvidenceError("evidence_screenshot must be a string when present.")

    return {
        "schema_version": 1,
        "capture_method": method,
        "read_only": True,
        "observed_at": parsed_time.isoformat(),
        "identity": {
            "article_id": str(identity["article_id"]).strip(),
            "appmsgid": str(identity["appmsgid"]).strip(),
            "account_name": str(identity["account_name"]).strip(),
            "title": str(identity["title"]).strip(),
            "markdown_sha256": sha,
        },
        "source_page": {"url": album_url},
        "article_entry": {
            "title_text": title_text,
            "link_attribute": link_attribute,
            "link_href_raw": href_raw,
            "resolved_article_url": resolved,
            "data_msgid": data_msgid,
            "data_itemidx": data_itemidx,
        },
        "dom_relation": {
            "container_tag": container_tag,
            "container_attributes": dict(container_attrs),
            "link_tag": link_tag,
            "link_attributes": dict(link_attrs),
        },
        "evidence_screenshot": str(screenshot) if screenshot else None,
        "observation_note": str(observation.get("observation_note") or ""),
    }


def validate_binding(
    evidence: dict[str, Any],
    *,
    article_id: str,
    appmsgid: str,
    title: str,
    markdown_sha256: str,
    verified_article_url: str,
    expected_biz_id: str,
) -> dict[str, Any]:
    """Bind a stored observation to one upstream article and one verified URL."""
    identity = evidence.get("identity") or {}
    for field, expected in (
        ("article_id", article_id),
        ("appmsgid", appmsgid),
        ("title", title),
    ):
        if str(identity.get(field) or "").strip() != str(expected).strip():
            raise PublicationSourceEvidenceError(
                f"Source evidence identity.{field} does not match the candidate article."
            )
    if str(identity.get("markdown_sha256") or "").casefold() != str(markdown_sha256).casefold():
        raise PublicationSourceEvidenceError("Source evidence markdown_sha256 does not match slot1.md.")
    entry = evidence.get("article_entry") or {}
    if str(entry.get("title_text") or "").strip() != str(title).strip():
        raise PublicationSourceEvidenceError("Observed page title does not match the candidate article.")
    verified_identity = article_url_identity(verified_article_url)
    if not verified_identity:
        raise PublicationSourceEvidenceError("The verified article URL has no stable article identity fields.")
    for source_key in ("resolved_article_url", "link_href_raw"):
        observed_identity = article_url_identity(entry.get(source_key))
        if observed_identity != verified_identity:
            raise PublicationSourceEvidenceError(
                f"Source evidence {source_key} does not match the verified article URL."
            )
    if verified_identity.get("__biz") != expected_biz_id:
        raise PublicationSourceEvidenceError("Verified article URL __biz does not match the target account.")
    album_url = str((evidence.get("source_page") or {}).get("url") or "")
    _validate_album_url(album_url, expected_biz_id=expected_biz_id)
    relation = evidence.get("dom_relation") or {}
    return {
        "album_url": album_url,
        "data_msgid": str(entry.get("data_msgid") or ""),
        "data_itemidx": str(entry.get("data_itemidx") or ""),
        "observed_at": str(evidence.get("observed_at") or ""),
        "link_attribute": str(entry.get("link_attribute") or ""),
        "container_tag": str(relation.get("container_tag") or ""),
        "link_tag": str(relation.get("link_tag") or ""),
    }


def read_source_evidence(directory: Path) -> dict[str, Any] | None:
    path = Path(directory) / EVIDENCE_FILENAME
    if not path.is_file():
        return None
    return _read_json(path)


def _bundle_matches_identity(
    directory: Path,
    *,
    article_id: str,
    appmsgid: str,
    title: str,
    markdown_sha256: str,
) -> bool:
    manifest_path = directory / "article_summary_manifest.json"
    source_path = directory / "source_record.json"
    if not manifest_path.is_file() or not source_path.is_file():
        return False
    try:
        manifest = _read_json(manifest_path)
        source = _read_json(source_path)
    except PublicationSourceEvidenceError:
        return False
    for record in (manifest, source):
        values = {
            "article_id": [str(v) for v in _record_values(record, "article_id", "source_article_id")],
            "appmsgid": [str(v) for v in _record_values(record, "appmsgid", "source_appmsgid")],
            "title": [str(v) for v in _record_values(record, "article_title", "title", "source_article_title")],
            "sha": [str(v).casefold() for v in _record_values(
                record, "source_article_sha256", "article_markdown_sha256", "source_article_markdown_sha256"
            )],
        }
        if not (
            article_id in values["article_id"]
            and appmsgid in values["appmsgid"]
            and title in values["title"]
            and markdown_sha256.casefold() in values["sha"]
        ):
            return False
    return True


def _record_values(record: dict[str, Any], *keys: str) -> list[Any]:
    found: list[Any] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and not isinstance(item, (dict, list)):
                    found.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(record)
    return found


def record_source_evidence(
    *,
    observation_path: Path,
    evidence_root: Path,
    expected_biz_id: str,
) -> dict[str, Any]:
    """Validate an observation and atomically add it to the unique matching bundle."""
    observation = _read_json(Path(observation_path).resolve())
    evidence = validate_observation(observation, expected_biz_id=expected_biz_id)
    identity = evidence["identity"]
    root = Path(evidence_root).resolve()
    if not root.is_dir():
        raise PublicationSourceEvidenceError(f"Video evidence root does not exist: {root}")

    matches: list[Path] = []
    for manifest in sorted(root.rglob("article_summary_manifest.json")):
        directory = manifest.parent
        if not all((directory / name).is_file() for name in _ORIGINAL_EVIDENCE_FILES):
            continue
        if _bundle_matches_identity(
            directory,
            article_id=identity["article_id"],
            appmsgid=identity["appmsgid"],
            title=identity["title"],
            markdown_sha256=identity["markdown_sha256"],
        ):
            matches.append(directory)
    if not matches:
        raise PublicationSourceEvidenceError(
            "No unique Video evidence bundle matches the observed article identity and SHA-256."
        )
    if len(matches) > 1:
        raise PublicationSourceEvidenceError(
            "Multiple Video evidence bundles match the observed article; refusing to choose: "
            + ", ".join(str(item) for item in matches)
        )
    target = matches[0] / EVIDENCE_FILENAME
    if target.exists():
        raise PublicationSourceEvidenceError(f"Refusing to overwrite existing evidence file: {target}")

    verification = _read_json(matches[0] / "url_verification_evidence.json")
    article_urls = [
        value for value in _record_values(verification, "url", "resolved_url")
        if isinstance(value, str) and urlparse(value).hostname == "mp.weixin.qq.com"
    ]
    if not article_urls:
        raise PublicationSourceEvidenceError("url_verification_evidence.json has no recorded article URL.")
    unique_urls = {validate_canonical_article_url(value) for value in article_urls}
    if len(unique_urls) != 1:
        raise PublicationSourceEvidenceError("url_verification_evidence.json records conflicting article URLs.")
    validate_binding(
        evidence,
        article_id=identity["article_id"],
        appmsgid=identity["appmsgid"],
        title=identity["title"],
        markdown_sha256=identity["markdown_sha256"],
        verified_article_url=next(iter(unique_urls)),
        expected_biz_id=expected_biz_id,
    )

    _write_json_atomic(target, evidence)
    return {
        "state": "SOURCE_EVIDENCE_RECORDED",
        "evidence_path": str(target),
        "evidence_bundle": str(matches[0]),
        "identity": identity,
        "source_page_url": evidence["source_page"]["url"],
        "resolved_article_url": evidence["article_entry"]["resolved_article_url"],
        "observed_at": evidence["observed_at"],
        "original_files_untouched": True,
    }
