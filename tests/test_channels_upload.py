from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from wechat_video.channels_metadata import (
    build_channels_metadata,
    build_channels_metadata_for_run_dir,
    validate_channels_metadata,
)
from wechat_video.channels_uploader import (
    UploadBlockedError,
    UploadUnknownError,
    _approval_record,
    _resolve_upload_job_identity,
    _matching_draft_entries,
    _validate_run_for_upload,
    _visible_element_handle,
    _visible_element_handles,
    _fill_field,
    _draft_save_button,
    _draft_save_button_with_info,
    _click_draft_save_once,
    MANUAL_SAVE_MONITOR_JS,
    install_manual_save_monitor,
    read_manual_save_monitor,
    summarize_manual_save_click,
    _finalize_draft_verification,
    _draft_snapshot,
    _open_draft_list_view,
    _open_create_view,
    _video_file_input,
    _set_video_file,
    _wait_for_account_identity,
    _ensure_draft_list_account_identity,
    _account_identity_evidence,
    _login_required_hint,
    _collect_ui_inventory,
    _is_headless_command,
    _verify_new_draft_after_save,
    record_manual_review,
    approve_run,
)
from wechat_video.topic_approval import (
    TopicApprovalError,
    approve_fact_card,
    verify_fact_card_approval,
)





def test_new_source_run_gets_first_upload_attempt_id(tmp_path: Path) -> None:
    job_id, attempt = _resolve_upload_job_identity(
        tmp_path, {"jobs_dir": "runtime/upload_jobs"}, "run-123"
    )
    assert job_id == "run-123"
    assert attempt == 1


def test_failed_before_upload_allocates_new_attempt_without_copying_video(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "runtime" / "upload_jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "run-123.json").write_text(
        json.dumps({
            "job_id": "run-123",
            "state": "FAILED_BEFORE_SAVE",
            "save_click_count": 0,
            "verified_draft": None,
        }),
        encoding="utf-8",
    )

    job_id, attempt = _resolve_upload_job_identity(
        tmp_path, {"jobs_dir": "runtime/upload_jobs"}, "run-123"
    )
    assert job_id == "run-123.upload_attempt_02"
    assert attempt == 2


def test_multiple_proven_pre_upload_failures_keep_separate_attempt_records(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "runtime" / "upload_jobs"
    jobs_dir.mkdir(parents=True)
    safe_failure = {
        "state": "FAILED_BEFORE_SAVE",
        "save_click_count": 0,
        "verified_draft": None,
    }
    (jobs_dir / "run-123.json").write_text(
        json.dumps({"job_id": "run-123", **safe_failure}), encoding="utf-8"
    )
    (jobs_dir / "run-123.upload_attempt_02.json").write_text(
        json.dumps({
            "job_id": "run-123.upload_attempt_02",
            "source_run_id": "run-123",
            **safe_failure,
        }),
        encoding="utf-8",
    )

    job_id, attempt = _resolve_upload_job_identity(
        tmp_path, {"jobs_dir": "runtime/upload_jobs"}, "run-123"
    )
    assert job_id == "run-123.upload_attempt_03"
    assert attempt == 3


def test_unknown_or_started_upload_attempt_cannot_be_bypassed(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "runtime" / "upload_jobs"
    jobs_dir.mkdir(parents=True)
    path = jobs_dir / "run-123.json"
    path.write_text(
        json.dumps({
            "job_id": "run-123",
            "state": "UPLOAD_UNKNOWN",
            "save_click_count": 1,
            "upload_started_at": "2026-11-22T14:00:00",
            "verified_draft": None,
        }),
        encoding="utf-8",
    )
    with pytest.raises(UploadUnknownError):
        _resolve_upload_job_identity(
            tmp_path, {"jobs_dir": "runtime/upload_jobs"}, "run-123"
        )

    path.write_text(
        json.dumps({
            "job_id": "run-123",
            "state": "FAILED_BEFORE_SAVE",
            "save_click_count": 0,
            "upload_started_at": "2026-11-22T14:00:00",
            "verified_draft": None,
        }),
        encoding="utf-8",
    )
    with pytest.raises(UploadBlockedError, match="non-retryable"):
        _resolve_upload_job_identity(
            tmp_path, {"jobs_dir": "runtime/upload_jobs"}, "run-123"
        )

def test_edge_headless_mode_is_detected_without_accepting_unrelated_flags() -> None:
    assert _is_headless_command(["msedge.exe", "--user-data-dir=C:/profile", "--headless=new"])
    assert _is_headless_command(["msedge.exe", "--headless"])
    assert not _is_headless_command(["msedge.exe", "--new-window", "--disable-gpu"])
    assert not _is_headless_command(["msedge.exe", "--disable-headless-mode"])


def test_post_save_draft_verification_mounts_spa_once_then_polls_existing_view(
    monkeypatch,
) -> None:
    import wechat_video.channels_uploader as uploader

    page = _FakePage([_FakeFrame("https://channels.weixin.qq.com/platform")])
    calls = {"navigation": 0, "snapshot": 0}
    snapshots = [
        {
            "view_type": "draft_list",
            "view_verified": True,
            "draft_count": 0,
            "entries": [],
            "view_evidence": {"page_path": "/platform"},
        },
        {
            "view_type": "draft_list",
            "view_verified": True,
            "draft_count": 1,
            "entries": ["临界半径如何决定成核 2026-11-22 10:30"],
            "url": "https://channels.weixin.qq.com/platform",
            "view_evidence": {"page_path": "/platform"},
        },
    ]

    def open_view(_page, _config, _selectors):
        calls["navigation"] += 1

    def read_snapshot(_page, _selectors):
        calls["snapshot"] += 1
        return snapshots[min(calls["snapshot"] - 1, len(snapshots) - 1)]

    monkeypatch.setattr(uploader, "_open_draft_list_view", open_view)
    monkeypatch.setattr(uploader, "_draft_snapshot", read_snapshot)

    after, matches, history, elapsed = _verify_new_draft_after_save(
        page,
        {
            "draft_verify_timeout_seconds": 5,
            "draft_verify_poll_interval_seconds": 0.5,
            "draft_verify_initial_settle_seconds": 0,
        },
        {"draft_status_texts": ["草稿"]},
        title="临界半径如何决定成核",
        before_snapshot={"entries": []},
    )

    assert calls == {"navigation": 1, "snapshot": 2}
    assert after is snapshots[1]
    assert matches == ["临界半径如何决定成核 2026-11-22 10:30"]
    assert len(history) == 2
    assert history[-1]["new_match_count"] == 1
    assert elapsed >= 0
    assert page.wait_calls == [500]


def test_post_save_verification_never_reclassifies_preexisting_same_title_as_new(
    monkeypatch,
) -> None:
    import wechat_video.channels_uploader as uploader

    now = {"value": 0.0}
    monkeypatch.setattr(uploader.time, "monotonic", lambda: now["value"])

    class _AdvancingPage(_FakePage):
        def wait_for_timeout(self, milliseconds):
            super().wait_for_timeout(milliseconds)
            now["value"] += milliseconds / 1000

    page = _AdvancingPage([_FakeFrame("https://channels.weixin.qq.com/platform")])
    snapshots = [
        {
            "view_type": "draft_list",
            "view_verified": True,
            "draft_count": 1,
            "entries": ["临界半径如何决定成核 2026-11-22 10:30"],
            "url": "https://channels.weixin.qq.com/platform",
            "view_evidence": {"page_path": "/platform"},
        }
    ]
    calls = {"snapshot": 0}

    def open_view(_page, _config, _selectors):
        return None

    def read_snapshot(_page, _selectors):
        calls["snapshot"] += 1
        return snapshots[0]

    monkeypatch.setattr(uploader, "_open_draft_list_view", open_view)
    monkeypatch.setattr(uploader, "_draft_snapshot", read_snapshot)

    after, matches, history, elapsed = _verify_new_draft_after_save(
        page,
        {
            "draft_verify_timeout_seconds": 1,
            "draft_verify_poll_interval_seconds": 0.5,
            "draft_verify_initial_settle_seconds": 0,
        },
        {"draft_status_texts": ["草稿"]},
        title="临界半径如何决定成核",
        before_snapshot={
            "entries": ["临界半径如何决定成核 2026-11-21 20:30"]
        },
    )

    assert after is snapshots[0]
    assert matches == []
    assert calls["snapshot"] == 3
    assert len(history) == 3
    assert page.wait_calls == [500, 500]
    assert all(item["preexisting_title_match_count"] == 1 for item in history)
    assert history[-1]["new_match_count"] == 1
    assert elapsed == 1.0


def _make_manual_review_job(root: Path, *, state: str = "UPLOAD_UNKNOWN") -> str:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write(
        config_dir / "channels_upload.json",
        {
            "schema_version": 1,
            "account_name": "成核生长",
            "jobs_dir": "runtime/upload_jobs",
            "selectors_file": "config/selectors.yaml",
            "safety": {
                "allow_publish": False,
                "allow_schedule": False,
                "allow_delete": False,
                "allow_overwrite": False,
                "cdp_host": "127.0.0.1",
            },
        },
    )
    (config_dir / "selectors.yaml").write_text(
        "account_identity:\n  exact_text: 成核生长\n", encoding="utf-8"
    )
    job_id = "20261121_224049_critical_nucleus"
    _write(
        root / "runtime" / "upload_jobs" / f"{job_id}.json",
        {
            "schema_version": 1,
            "job_id": job_id,
            "state": state,
            "title": "临界半径如何决定成核",
            "save_click_count": 1,
            "verified_draft": None,
            "automatic_publication": False,
        },
    )
    return job_id


def test_manual_review_found_records_user_attestation_without_changing_save_clicks(
    tmp_path: Path,
) -> None:
    job_id = _make_manual_review_job(tmp_path)
    row = "临界半径如何决定成核 2026-11-22 10:30"

    result = record_manual_review(
        tmp_path,
        job_id,
        result="draft-found",
        reviewed_by="local reviewer",
        row_text=row,
        confirmation=f"CONFIRM CHANNELS DRAFT FOUND {job_id}",
    )

    job = json.loads(
        (tmp_path / "runtime" / "upload_jobs" / f"{job_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["state"] == "MANUALLY_CONFIRMED_DRAFT"
    assert result["upload_or_save_retried"] is False
    assert job["state"] == "MANUALLY_CONFIRMED_DRAFT"
    assert job["save_click_count"] == 1
    assert job["verified_draft"]["verification_method"] == "manual_user_attestation"
    assert job["verified_draft"]["row_text"] == row
    assert len(job["manual_reviews"]) == 1


def test_manual_not_found_is_time_scoped_and_keeps_same_job_blocked(
    tmp_path: Path,
) -> None:
    job_id = _make_manual_review_job(tmp_path)

    result = record_manual_review(
        tmp_path,
        job_id,
        result="not-found",
        reviewed_by="local reviewer",
        note="Checked the target account's 草稿箱; no row with the exact title was visible.",
        confirmation=f"CONFIRM CHANNELS DRAFT NOT FOUND {job_id}",
    )

    job = json.loads(
        (tmp_path / "runtime" / "upload_jobs" / f"{job_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["state"] == "MANUAL_REVIEW_NOT_FOUND"
    assert result["same_job_retry_allowed"] is False
    assert "time-scoped" in result["note"]
    assert job["state"] == "MANUAL_REVIEW_NOT_FOUND"
    assert job["save_click_count"] == 1
    assert job["verified_draft"] is None
    assert job["manual_review"]["result"] == "not_found_at_review_time"


def test_manual_review_requires_exact_confirmation_and_matching_title(
    tmp_path: Path,
) -> None:
    job_id = _make_manual_review_job(tmp_path)

    with pytest.raises(UploadBlockedError, match="confirmation did not match"):
        record_manual_review(
            tmp_path,
            job_id,
            result="draft-found",
            reviewed_by="local reviewer",
            row_text="临界半径如何决定成核 2026-11-22",
            confirmation="yes",
        )
    with pytest.raises(UploadBlockedError, match="must be copied from 草稿箱"):
        record_manual_review(
            tmp_path,
            job_id,
            result="draft-found",
            reviewed_by="local reviewer",
            row_text="different title",
            confirmation=f"CONFIRM CHANNELS DRAFT FOUND {job_id}",
        )


_RECT_SEQUENCE = itertools.count(1)


class _FakeElement:
    def __init__(
        self, *, text="", attrs=None, tag="div", visible=True, enabled=True,
        child_texts=None,
        on_hover=None,
        on_click=None,
        rect=None,
        ancestors=None,
        outer_html=None,
        click_error=None,
    ):
        self.text = text
        self.attrs = dict(attrs or {})
        self.tag = tag
        self.visible = visible
        self.enabled = enabled
        self.child_texts = list(child_texts or [])
        self.clicked = False
        self.hovered = False
        self.on_hover = on_hover
        self.on_click = on_click
        # Distinct elements get distinct geometry by default. This models two
        # genuinely different DOM nodes; an explicit identical rect lets tests
        # model the SAME node re-observed through another CDP page/frame.
        self.rect = dict(rect) if rect else {
            "x": next(_RECT_SEQUENCE) * 200, "y": 0, "w": 120, "h": 40,
        }
        self.ancestors = list(ancestors or [])
        self.outer_html = outer_html
        self.click_error = click_error
        self.native_click_count = 0
        self.dom_click_count = 0

    def structure(self):
        """Structural evidence returned by the enhanced same-frame DOM scan."""
        attrs = dict(self.attrs)
        href = str(attrs.get("href") or "")
        ancestors = []
        for raw in self.ancestors:
            ancestor = dict(raw)
            tag = str(ancestor.pop("tag", "div"))
            ancestor_href = str(ancestor.get("href") or "")
            if not href and ancestor_href:
                href = ancestor_href
            ancestors.append({
                "tag": tag,
                "id": str(ancestor.get("id") or ""),
                "class_name": str(ancestor.get("class") or ""),
                "role": str(ancestor.get("role") or ""),
                "href": ancestor_href,
                "attributes": {k: str(v) for k, v in ancestor.items()},
            })
        outer = self.outer_html
        if outer is None:
            rendered = " ".join(f'{k}="{v}"' for k, v in attrs.items())
            outer = f"<{self.tag} {rendered}>{self.text}</{self.tag}>"
        return {
            "attributes": {k: str(v) for k, v in attrs.items()},
            "outer_html": outer,
            "href": href,
            "ancestors": ancestors,
            "rect": dict(self.rect),
        }

    def is_visible(self):
        return self.visible

    def is_enabled(self):
        return self.enabled

    def get_attribute(self, name):
        return self.attrs.get(name)

    def inner_text(self, timeout=None):
        return self.text

    def input_value(self, timeout=None):
        if self.tag in {"input", "textarea"}:
            return self.text
        raise ValueError("not an input element")

    def fill(self, value, timeout=None):
        self.text = value

    def _activate(self):
        self.clicked = True
        if self.on_click is not None:
            self.on_click()

    def click(self, timeout=None):
        self.native_click_count += 1
        if self.click_error is not None:
            error = self.click_error
            self.click_error = None  # only the first native attempt fails
            if isinstance(error, BaseException):
                raise error
            raise RuntimeError(error)
        self._activate()

    def set_input_files(self, paths, timeout=None):
        self.files_set = list(paths) if isinstance(paths, (list, tuple)) else [paths]

    def hover(self, timeout=None):
        self.hovered = True
        if self.on_hover is not None:
            self.on_hover()

    def evaluate(self, expression):
        if "tagName.toLowerCase()" in expression:
            return self.tag
        if "matches('a,button,[role=button]')" in expression:
            return False
        if "Array.from(element.children)" in expression:
            return list(self.child_texts)
        if "element.click()" in expression:
            self.dom_click_count += 1
            self._activate()
            return None
        raise NotImplementedError(expression)


class _FakeJSHandle:
    def __init__(self, element):
        self.element = element

    def as_element(self):
        return self.element


class _FakeLocator:
    def __init__(self, items=None):
        self.items = list(items or [])

    @property
    def first(self):
        return self.nth(0)

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]

    def wait_for(self, state=None, timeout=None):
        if not self.items:
            raise TimeoutError("not found")


class _FakeFrame:
    def __init__(
        self,
        url,
        *,
        selectors=None,
        roles=None,
        texts=None,
        inspection=None,
        identity_matches=None,
        locator_unsupported=False,
        video_scan_error=False,
        dom_scan_error=False,
        bind_failures=0,
        scan_failures=0,
    ):
        self.url = url
        self.selectors = dict(selectors or {})
        self.roles = dict(roles or {})
        self.texts = dict(texts or {})
        self.inspection = dict(inspection or {})
        self.identity_matches = list(identity_matches or [])
        self.locator_unsupported = locator_unsupported
        self.video_scan_error = video_scan_error
        self.dom_scan_error = dom_scan_error
        self.bind_failures = int(bind_failures)
        self.scan_failures = int(scan_failures)
        self.last_evaluate_expression = ""
        self.last_evaluate_args = ()
        self.locator_calls = []

    def locator(self, selector):
        self.locator_calls.append(selector)
        if self.locator_unsupported:
            return _FakeLocator([])
        if selector == "input[type='file']":
            items = []
            seen = set()
            for key, values in self.selectors.items():
                if "input[type='file']" not in key:
                    continue
                for item in values:
                    if id(item) not in seen:
                        seen.add(id(item))
                        items.append(item)
            return _FakeLocator(items)
        if selector == "button, [role='button']":
            return _FakeLocator(self.selectors.get(selector, []))
        return _FakeLocator(self.selectors.get(selector, []))

    def _dom_candidates(self, payload):
        selector = str(payload.get("selector") or "")
        items = list(self.selectors.get(selector, []))
        if selector == "button, [role='button']":
            for key, values in self.roles.items():
                if key[0] == "button":
                    items.extend(values)
        unique = []
        seen = set()
        for item in items:
            if id(item) in seen:
                continue
            seen.add(id(item))
            if not item.is_visible():
                continue
            visible_text = " ".join(str(item.inner_text() or "").split())
            aria_label = " ".join(str(item.get_attribute("aria-label") or "").split())
            actual = visible_text or aria_label
            exact = payload.get("exact_text")
            contains = payload.get("contains_text")
            if exact is not None and actual != " ".join(str(exact).split()):
                continue
            if contains is not None and " ".join(str(contains).split()) not in actual:
                continue
            unique.append(item)
        return unique

    def evaluate_handle(self, expression, *args):
        if self.bind_failures > 0:
            self.bind_failures -= 1
            return _FakeJSHandle(None)
        if "__CHANNELS_VISIBLE_ELEMENT_HANDLE__" in expression:
            payload = args[0]
            candidates = self._dom_candidates(payload)
            index = int(payload["visible_index"])
            return _FakeJSHandle(
                candidates[index] if 0 <= index < len(candidates) else None
            )
        if "document.querySelectorAll" not in expression:
            raise NotImplementedError(expression)
        inputs = []
        seen = set()
        for selector, values in self.selectors.items():
            if "input[type='file']" not in selector:
                continue
            for item in values:
                if id(item) not in seen:
                    seen.add(id(item))
                    inputs.append(item)
        index = int(args[0])
        return _FakeJSHandle(inputs[index] if 0 <= index < len(inputs) else None)

    def evaluate(self, expression, *args):
        self.last_evaluate_expression = expression
        self.last_evaluate_args = args
        if "__CHANNELS_VISIBLE_ELEMENT_SCAN__" in expression:
            if self.scan_failures > 0:
                self.scan_failures -= 1
                raise RuntimeError(
                    "此报错可以忽略，iframe主动中断主应用代码在子应用运行 LogicError"
                )
            if self.dom_scan_error:
                raise RuntimeError("simulated same-frame DOM scan failure")
            payload = args[0]
            candidates = self._dom_candidates(payload)
            observed_payload = dict(payload)
            observed_payload["exact_text"] = None
            observed_payload["contains_text"] = None
            observed = self._dom_candidates(observed_payload)
            limit = int(payload.get("limit", 8))

            def describe(item, index):
                visible_text = " ".join(str(item.inner_text() or "").split())
                aria_label = " ".join(
                    str(item.get_attribute("aria-label") or "").split()
                )
                described = {
                    "visible_index": index,
                    "tag": item.tag,
                    "text": visible_text[:160],
                    "aria_label": aria_label[:160],
                    "matched_label": (visible_text or aria_label)[:160],
                    "label_source": (
                        "visible_text" if visible_text
                        else "aria_label" if aria_label
                        else "none"
                    ),
                    "disabled": not item.is_enabled(),
                }
                described.update(item.structure())
                return described

            return {
                "match_count": len(candidates),
                "items": [
                    describe(item, index)
                    for index, item in enumerate(candidates[:limit])
                ],
                "observed_items": (
                    [
                        describe(item, index)
                        for index, item in enumerate(observed[:limit])
                    ]
                    if payload.get("include_observed") is True else []
                ),
            }
        if expression.strip() == "() => document.readyState":
            return "complete"
        if "__CHANNELS_ACCOUNT_IDENTITY_SCAN__" in expression:
            return self.identity_matches
        if "__CHANNELS_VIDEO_FILE_INPUT_SCAN__" in expression:
            if self.video_scan_error:
                raise RuntimeError("simulated frame DOM inspection failure")
            inputs = []
            seen = set()
            for selector, values in self.selectors.items():
                if "input[type='file']" not in selector:
                    continue
                for item in values:
                    if id(item) in seen:
                        continue
                    seen.add(id(item))
                    attrs = item.attrs
                    context = attrs.get("context_text", [])
                    if isinstance(context, str):
                        context = [context]
                    labels = attrs.get("labels", [])
                    if isinstance(labels, str):
                        labels = [labels]
                    inputs.append({
                        "index": len(inputs),
                        "accept": attrs.get("accept", ""),
                        "name": attrs.get("name", ""),
                        "id": attrs.get("id", ""),
                        "class_name": attrs.get("class", ""),
                        "aria_label": attrs.get("aria-label", ""),
                        "title": attrs.get("title", ""),
                        "data_testid": attrs.get("data-testid", ""),
                        "labels": labels,
                        "context_text": context,
                        "visible": item.is_visible(),
                        "matched_selectors": [],
                    })
            return inputs
        if "__CHANNELS_DRAFT_LIST_DOM_SCAN__" in expression:
            config = args[0]

            def items(selector):
                return list(self.selectors.get(selector, []))

            def visible(item):
                return item.is_visible()

            roots = items(config["root_selector"])
            active_tabs = [item for item in items(config["active_tab_selector"]) if visible(item)]
            headers = [item for item in items(config["header_selector"]) if visible(item)]
            bodies = items(config["body_selector"])
            body = bodies[0] if len(bodies) == 1 else None
            row_texts = (
                [str(value).strip() for value in body.child_texts if str(value).strip()]
                if body is not None and visible(body)
                else []
            )
            return {
                "root_count": len(roots),
                "root_visible_count": sum(1 for item in roots if visible(item)),
                "active_tab_texts": [item.inner_text() for item in active_tabs],
                "header_texts": [item.inner_text() for item in headers],
                "body_count": len(bodies),
                "body_visible": bool(body is not None and visible(body)),
                "body_child_count": len(body.child_texts) if body is not None else 0,
                "row_texts": row_texts,
            }
        return self.inspection

    def get_by_role(self, role, name=None, exact=None):
        return _FakeLocator(self.roles.get((role, name, exact), []))

    def get_by_text(self, text, exact=None):
        return _FakeLocator(self.texts.get((text, exact), []))


class _FakePage:
    def __init__(self, frames, *, on_wait=None):
        self.frames = list(frames)
        self.main_frame = self.frames[0]
        self.url = "https://channels.weixin.qq.com/platform/post/create"
        self.on_wait = on_wait
        self.wait_calls = []

    def goto(self, url, wait_until=None, timeout=None):
        self.url = url
        self.main_frame.url = url

    def wait_for_timeout(self, milliseconds):
        self.wait_calls.append(milliseconds)
        if self.on_wait is not None:
            self.on_wait(milliseconds)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_run(root: Path, *, qa_status: str = "PASS") -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write(
        config_dir / "channels_upload.json",
        {
            "schema_version": 1,
            "account_name": "成核生长",
            "create_url": "https://channels.weixin.qq.com/platform/post/create",
            "draft_list_url": "https://channels.weixin.qq.com/platform/post/list",
            "edge_profile_dir": "runtime/edge-profile",
            "session_file": "runtime/edge_session.json",
            "jobs_dir": "runtime/upload_jobs",
            "approvals_dir": "runtime/approvals",
            "selectors_file": "config/selectors.yaml",
            "title_min_chars": 6,
            "title_max_chars": 16,
            "description_max_chars": 1000,
            "default_tags": ["#成核生长"],
            "safety": {
                "allow_publish": False,
                "allow_schedule": False,
                "allow_delete": False,
                "allow_overwrite": False,
                "cdp_host": "127.0.0.1",
            },
        },
    )
    (config_dir / "selectors.yaml").write_text(
        "account_identity:\n  exact_text: 成核生长\n", encoding="utf-8"
    )

    run_dir = root / "outputs" / "20261121_120000_example"
    run_dir.mkdir(parents=True)
    (run_dir / "final.mp4").write_bytes(b"x" * 120_000)
    _write(
        run_dir / "fact_card.json",
        {
            "fact_card_id": "TEST-001",
            "title": "测试科学视频：界面能与体相收益",
            "channels_title": "临界半径如何决定成核",
            "scientific_question": "为什么界面代价与体相收益会相互竞争？",
            "scope": "仅在本测试定义的模型条件下讨论。",
            "claims": [{
                "claim_id": "C1",
                "statement": "测试事实。",
                "source_ids": ["S1"],
                "evidence_status": "FULL_TEXT_LOCATED",
                "caveats": [],
            }],
            "approval_status": "DRAFT_PENDING_USER_REVIEW",
        },
    )
    _write(run_dir / "source_record.json", {"sources": [{"source_id": "S1"}]})
    _write(run_dir / "script.json", {"script_id": "TEST-SCRIPT"})
    _write(
        run_dir / "qa_report.json",
        {
            "overall_status": qa_status,
            "video_summary": {"duration_seconds": 60.0},
        },
    )
    return run_dir


def test_channels_metadata_uses_explicit_short_title_and_only_fact_card_text() -> None:
    card = {
        "fact_card_id": "CNT-1",
        "title": "临界晶核：界面代价与体相收益",
        "channels_title": "临界半径如何决定成核",
        "scientific_question": "为什么有些小晶核会消失，而更大的晶核可能继续长大？",
        "scope": "仅讨论经典均匀成核理论的球形近似。",
    }
    script = {"script_id": "S1", "title": "ignored for facts"}
    result = build_channels_metadata(card, script, "job_1")
    assert result["title"] == card["channels_title"]
    assert 6 <= len(result["title"]) <= 16
    assert card["scientific_question"] in result["description"]
    assert card["scope"] in result["description"]
    assert result["source"] == "fact_card_and_script_metadata"
    assert "ignored for facts" not in result["description"]
    validate_channels_metadata(result)


def test_run_directory_metadata_uses_complete_output_directory_name(tmp_path: Path) -> None:
    run_dir = tmp_path / "outputs" / "20261121_195519_critical_nucleus"
    run_dir.mkdir(parents=True)
    card = {
        "fact_card_id": "TEST-CNT-001",
        "title": "临界晶核自由能",
        "channels_title": "临界半径如何决定成核",
        "scientific_question": "为什么小晶核可能消失，而较大的晶核可能继续长大？",
        "scope": "仅讨论经典均匀成核理论中的球形晶核近似。",
    }
    script = {"script_id": "TEST-SCRIPT-001"}

    metadata = build_channels_metadata_for_run_dir(card, script, run_dir)

    assert metadata["job_id"] == run_dir.name
    assert metadata == build_channels_metadata(card, script, run_dir.name)


def test_metadata_rejects_short_title_outside_6_to_16_chars() -> None:
    with pytest.raises(ValueError, match="6–16"):
        validate_channels_metadata(
            {"job_id": "j1", "title": "这个标题长度明显超过十六个字符了吧", "description": "description"}
        )
    with pytest.raises(ValueError, match="6–16"):
        validate_channels_metadata(
            {"job_id": "j1", "title": "短", "description": "description"}
        )


def test_draft_match_requires_title_and_explicit_draft_status() -> None:
    selectors = {"draft_status_texts": ["草稿", "草稿箱"]}
    snapshot = {
        "entries": [
            "临界半径如何决定成核 已发布",
            "临界半径如何决定成核 草稿 2026-11-21",
        ]
    }
    matches = _matching_draft_entries(snapshot, "临界半径如何决定成核", selectors)
    assert len(matches) == 1
    assert "草稿" in matches[0]


def test_draft_match_uses_verified_draft_manager_membership_without_row_status_label() -> None:
    selectors = {"draft_status_texts": ["草稿", "草稿箱"]}
    verified_draft_snapshot = {
        "view_type": "draft_list",
        "view_verified": True,
        "entries": ["临界半径如何决定成核 2026-11-21 20:30"],
    }
    video_list_snapshot = {
        "view_type": "video_list",
        "view_verified": True,
        "entries": ["临界半径如何决定成核 2026-11-21 20:30"],
    }

    assert len(
        _matching_draft_entries(
            verified_draft_snapshot, "临界半径如何决定成核", selectors
        )
    ) == 1
    assert _matching_draft_entries(
        video_list_snapshot, "临界半径如何决定成核", selectors
    ) == []


def _draft_list_test_selectors() -> dict:
    return {
        "draft_list_path": "/platform/post/draftListManager",
        "draft_list_parent_shell_path": "/platform",
        "draft_list_frame_path": "/micro/content/post/draftListManager",
        "draft_list_root_selector": "div.finder-page.DraftListManager",
        "draft_list_active_tab_selector": "li.weui-desktop-tab__nav_current",
        "draft_list_header_selector": "div.post-list-header",
        "draft_list_body_selector": (
            "div.list-wrapper.draft-list-wrapper div.post-list-body"
        ),
        "draft_list_ready_timeout_seconds": 0,
    }


def test_open_draft_list_view_uses_platform_navigation_to_mount_spa_frame() -> None:
    draft_root = _FakeElement(text="草稿箱", visible=True)
    active_tab = _FakeElement(text="草稿箱 (0)", visible=True)
    header = _FakeElement(text="草稿箱 (0)", visible=True)
    body = _FakeElement(text="", visible=False, child_texts=[])

    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html"
    )

    def mount_draft_manager():
        child.url = (
            "https://channels.weixin.qq.com/micro/content/post/draftListManager"
        )
        child.selectors = {
            "div.finder-page.DraftListManager": [draft_root],
            "li.weui-desktop-tab__nav_current": [active_tab],
            "div.post-list-header": [header],
            "div.list-wrapper.draft-list-wrapper div.post-list-body": [body],
        }

    nav_entry = _FakeElement(
        text="草稿箱 (0)",
        visible=False,
        on_click=mount_draft_manager,
    )
    nav_parent = _FakeElement(
        visible=True,
        on_hover=lambda: setattr(nav_entry, "visible", True),
    )
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/list",
        selectors={
            ".finder-ui-desktop-menu__sub__wrp": [nav_parent],
            ".finder-ui-desktop-sub-menu__item": [nav_entry],
        },
        identity_matches=[{
            "tag": "h2",
            "evidence_type": "visible_text",
            "matched_value": "成核生长",
            "region": "semantic_account_surface",
            "semantic_account_surface": True,
            "identity_surface": "finder_nickname",
            "left": 235,
            "top": 88,
            "width": 212,
            "height": 21,
        }],
    )
    page = _FakePage([main, child])
    selectors = _draft_list_test_selectors()
    selectors.update({
        "draft_list_nav_parent_selectors": [
            ".finder-ui-desktop-menu__sub__wrp"
        ],
        "draft_list_nav_entry_selectors": [
            ".finder-ui-desktop-sub-menu__item"
        ],
        "draft_list_nav_entry_text": "草稿箱",
        "draft_list_nav_timeout_seconds": 0,
    })
    config = {
        "platform_url": "https://channels.weixin.qq.com/platform",
        "account_name": "成核生长",
        "ui_ready_timeout_seconds": 1,
    }

    _open_draft_list_view(page, config, selectors)

    assert page.url == "https://channels.weixin.qq.com/platform"
    assert nav_parent.hovered is True
    assert nav_entry.clicked is True
    assert main.locator_calls == []
    assert child.url.endswith("/micro/content/post/draftListManager")


def _make_draft_list_page(
    *,
    draft_count: int,
    entries: list[str] | None = None,
    parent_path: str = "/platform/post/draftListManager",
):
    main = _FakeFrame(f"https://channels.weixin.qq.com{parent_path}")
    root = _FakeElement(text="草稿箱", visible=True)
    active_tab = _FakeElement(text=f"草稿箱 ({draft_count})", visible=True)
    header = _FakeElement(text=f"草稿箱 ({draft_count})", visible=True)
    body_texts = list(entries or [])
    body = _FakeElement(
        text=" ".join(body_texts),
        visible=bool(draft_count),
        child_texts=body_texts,
    )
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/draftListManager",
        selectors={
            "div.finder-page.DraftListManager": [root],
            "li.weui-desktop-tab__nav_current": [active_tab],
            "div.post-list-header": [header],
            "div.list-wrapper.draft-list-wrapper div.post-list-body": [body],
        },
        locator_unsupported=True,
    )
    page = _FakePage([main, child])
    page.url = f"https://channels.weixin.qq.com{parent_path}"
    return page


def test_draft_snapshot_accepts_verified_zero_count_when_list_body_is_hidden() -> None:
    page = _make_draft_list_page(draft_count=0)

    snapshot = _draft_snapshot(page, _draft_list_test_selectors())

    assert snapshot["view_type"] == "draft_list"
    assert snapshot["view_verified"] is True
    assert snapshot["draft_count"] == 0
    assert snapshot["entries"] == []
    child = page.frames[1]
    assert child.locator("div.finder-page.DraftListManager").count() == 0
    assert "__CHANNELS_DRAFT_LIST_DOM_SCAN__" in child.last_evaluate_expression
    assert snapshot["view_evidence"]["frame_path"] == (
        "/micro/content/post/draftListManager"
    )



def test_draft_snapshot_accepts_platform_shell_when_child_frame_proves_draft_manager() -> None:
    page = _make_draft_list_page(draft_count=0, parent_path="/platform")

    snapshot = _draft_snapshot(page, _draft_list_test_selectors())

    assert snapshot["view_verified"] is True
    assert snapshot["view_evidence"]["page_path"] == "/platform"
    assert snapshot["view_evidence"]["page_route_mode"] == (
        "platform_shell_with_verified_draft_frame"
    )
    assert snapshot["view_evidence"]["frame_path"] == (
        "/micro/content/post/draftListManager"
    )


def test_draft_snapshot_still_rejects_platform_shell_without_dedicated_child_frame() -> None:
    page = _make_draft_list_page(draft_count=0, parent_path="/platform")
    page.frames[1].url = "https://channels.weixin.qq.com/micro/content/post/list"

    with pytest.raises(UploadBlockedError, match="dedicated draft manager"):
        _draft_snapshot(page, _draft_list_test_selectors())


def test_draft_snapshot_rejects_unrecognized_parent_route_even_with_draft_child_frame() -> None:
    page = _make_draft_list_page(draft_count=0, parent_path="/platform/other")

    with pytest.raises(UploadBlockedError, match="dedicated draft manager"):
        _draft_snapshot(page, _draft_list_test_selectors())


def test_draft_snapshot_reads_entries_from_confirmed_draft_list_body() -> None:
    page = _make_draft_list_page(
        draft_count=1,
        entries=["临界半径如何决定成核 2026-11-21 20:30"],
    )

    snapshot = _draft_snapshot(page, _draft_list_test_selectors())
    matches = _matching_draft_entries(
        snapshot,
        "临界半径如何决定成核",
        {"draft_status_texts": ["草稿", "草稿箱"]},
    )

    assert snapshot["draft_count"] == 1
    assert len(snapshot["entries"]) == 1
    assert len(matches) == 1
    child = page.frames[1]
    assert child.locator(
        "div.list-wrapper.draft-list-wrapper div.post-list-body"
    ).count() == 0
    assert "__CHANNELS_DRAFT_LIST_DOM_SCAN__" in child.last_evaluate_expression


def test_draft_snapshot_rejects_video_management_route_even_if_nav_mentions_drafts() -> None:
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/list")
    video_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/list"
    )
    page = _FakePage([main, video_frame])
    page.url = "https://channels.weixin.qq.com/platform/post/list"

    with pytest.raises(UploadBlockedError, match="dedicated draft manager"):
        _draft_snapshot(page, _draft_list_test_selectors())


def test_draft_snapshot_rejects_wrong_active_tab_even_on_draft_manager_route() -> None:
    page = _make_draft_list_page(draft_count=0)
    child = page.frames[1]
    child.selectors["li.weui-desktop-tab__nav_current"] = [
        _FakeElement(text="视频 (0)", visible=True)
    ]
    child.selectors["div.post-list-header"] = [
        _FakeElement(text="视频 (0)", visible=True)
    ]

    with pytest.raises(UploadBlockedError, match="dedicated draft manager"):
        _draft_snapshot(page, _draft_list_test_selectors())


def test_draft_snapshot_blocks_positive_count_without_readable_rows() -> None:
    page = _make_draft_list_page(draft_count=1, entries=[])

    with pytest.raises(UploadBlockedError, match="no readable rows"):
        _draft_snapshot(page, _draft_list_test_selectors())


def test_draft_snapshot_waits_for_rows_rendered_after_draft_manager_shell() -> None:
    page = _make_draft_list_page(draft_count=1, entries=[])
    body = page.frames[1].selectors[
        "div.list-wrapper.draft-list-wrapper div.post-list-body"
    ][0]
    page.on_wait = lambda _milliseconds: setattr(
        body, "child_texts", ["临界半径如何决定成核 2026-11-21 20:30"]
    )
    selectors = _draft_list_test_selectors()
    selectors["draft_list_rows_timeout_seconds"] = 2

    snapshot = _draft_snapshot(page, selectors)

    assert snapshot["draft_count"] == 1
    assert snapshot["entries"] == [
        "临界半径如何决定成核 2026-11-21 20:30"
    ]
    assert page.wait_calls == [500]


def test_matching_verified_draft_entries_counts_rows_not_repeated_title_text() -> None:
    snapshot = {
        "view_type": "draft_list",
        "view_verified": True,
        "entries": [
            "临界半径如何决定成核 临界半径如何决定成核",
            "另一条无关草稿",
        ],
    }

    matches = _matching_draft_entries(
        snapshot,
        "临界半径如何决定成核",
        {"draft_status_texts": ["草稿"]},
    )

    assert len(matches) == 1


def test_pending_sample_requires_explicit_human_approval(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    with pytest.raises(UploadBlockedError, match="Approval phrase did not match"):
        approve_run(
            tmp_path,
            run_dir,
            approved_by="test-user",
            confirmation="NO",
        )
    assert not (tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json").exists()


def test_explicit_approval_is_bound_to_exact_artifact_hashes(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    approval = approve_run(
        tmp_path,
        run_dir,
        approved_by="test-user",
        confirmation="APPROVE TEST-001",
    )
    saved = tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json"
    assert saved.is_file()
    assert approval["fact_card_approved"] is True
    assert approval["video_accepted"] is True
    assert approval["qa_status"] == "PASS"
    assert len(approval["video_sha256"]) == 64

    (run_dir / "final.mp4").write_bytes(b"changed" * 20_000)
    config = {"approvals_dir": "runtime/approvals"}
    with pytest.raises(UploadBlockedError, match="changed or is missing"):
        _approval_record(tmp_path, config, run_dir)


def test_warning_or_failed_qa_cannot_be_approved(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, qa_status="PASS_WITH_WARNINGS")
    with pytest.raises(UploadBlockedError, match="strict QA PASS"):
        approve_run(
            tmp_path,
            run_dir,
            approved_by="test-user",
            confirmation="APPROVE TEST-001",
        )


def test_fact_card_approval_is_one_time_and_hash_bound_to_sources(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    fact_dir = tmp_path / "fact_cards"
    fact_dir.mkdir(parents=True)
    card_path = fact_dir / "test_card.json"
    source_path = fact_dir / "sources.json"
    import shutil

    shutil.copy2(run_dir / "fact_card.json", card_path)
    shutil.copy2(run_dir / "source_record.json", source_path)

    with pytest.raises(TopicApprovalError, match="phrase did not match"):
        approve_fact_card(
            tmp_path,
            card_path,
            approved_by="test-user",
            confirmation="NO",
        )
    approval_file = tmp_path / "runtime" / "topic_approvals" / "TEST-001.json"
    assert not approval_file.exists()

    record = approve_fact_card(
        tmp_path,
        card_path,
        approved_by="test-user",
        confirmation="APPROVE FACT CARD TEST-001",
    )
    assert approval_file.is_file()
    assert record["fact_card_sha256"]
    assert record["source_record_sha256"]

    verified = verify_fact_card_approval(tmp_path, card_path, source_path)
    assert verified is not None
    assert verified["approval_type"] == "local_hash_bound"

    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TopicApprovalError, match="approved source record changed"):
        verify_fact_card_approval(tmp_path, card_path, source_path)


def test_upload_validation_uses_standing_draft_authorization_without_topic_approval(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    config = json.loads(
        (tmp_path / "config" / "channels_upload.json").read_text(encoding="utf-8")
    )

    metadata, qa, authorization = _validate_run_for_upload(tmp_path, run_dir, config)

    assert metadata["title"] == "临界半径如何决定成核"
    assert qa["overall_status"] == "PASS"
    assert authorization["approval_type"] == "standing_user_draft_only_authorization"
    assert authorization["approved_by"] is None
    assert not (tmp_path / "runtime" / "topic_approvals" / "TEST-001.json").exists()
    assert not (tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json").exists()


def test_upload_validation_still_requires_strict_qa_pass_without_approval(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path, qa_status="PASS_WITH_WARNINGS")
    config = json.loads(
        (tmp_path / "config" / "channels_upload.json").read_text(encoding="utf-8")
    )

    with pytest.raises(UploadBlockedError, match="strict PASS"):
        _validate_run_for_upload(tmp_path, run_dir, config)


def test_upload_validation_rejects_metadata_changed_after_fact_card_approval(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    fact_dir = tmp_path / "fact_cards"
    fact_dir.mkdir(parents=True)
    card_path = fact_dir / "test_card.json"
    source_path = fact_dir / "sources.json"
    import shutil

    shutil.copy2(run_dir / "fact_card.json", card_path)
    shutil.copy2(run_dir / "source_record.json", source_path)
    approve_fact_card(
        tmp_path,
        card_path,
        approved_by="test-user",
        confirmation="APPROVE FACT CARD TEST-001",
    )

    changed_metadata = {
        "schema_version": 1,
        "job_id": run_dir.name,
        "account_name": "成核生长",
        "title": "未经批准的另一种标题",
        "description": "Injected description not derived from the Fact Card.",
        "tags": ["#成核生长"],
        "source_fact_card_id": "TEST-001",
        "script_id": "TEST-SCRIPT",
        "source": "manual_edit",
    }
    _write(run_dir / "channels_draft.json", changed_metadata)
    config = json.loads(
        (tmp_path / "config" / "channels_upload.json").read_text(encoding="utf-8")
    )
    with pytest.raises(UploadBlockedError, match="differs from the Fact Card-derived metadata"):
        _validate_run_for_upload(tmp_path, run_dir, config)


def test_preexisting_output_without_new_short_title_uses_approved_card_title(
    tmp_path: Path,
) -> None:
    run_dir = _make_run(tmp_path)
    fact_dir = tmp_path / "fact_cards"
    fact_dir.mkdir(parents=True)
    card_path = fact_dir / "test_card.json"
    source_path = fact_dir / "sources.json"
    import shutil

    # The current approved Fact Card has the new short-title field.
    shutil.copy2(run_dir / "fact_card.json", card_path)
    shutil.copy2(run_dir / "source_record.json", source_path)
    approve_fact_card(
        tmp_path,
        card_path,
        approved_by="test-user",
        confirmation="APPROVE FACT CARD TEST-001",
    )

    # Simulate a video rendered earlier, before channels_title existed.
    output_card_path = run_dir / "fact_card.json"
    old_output_card = json.loads(output_card_path.read_text(encoding="utf-8"))
    old_output_card.pop("channels_title", None)
    _write(output_card_path, old_output_card)

    config = json.loads(
        (tmp_path / "config" / "channels_upload.json").read_text(encoding="utf-8")
    )
    metadata, qa, approval = _validate_run_for_upload(tmp_path, run_dir, config)
    assert metadata["title"] == "临界半径如何决定成核"
    assert qa["overall_status"] == "PASS"
    assert approval["approval_type"] == "standing_user_draft_only_authorization"
    assert approval["channels_title"] == "临界半径如何决定成核"


def test_description_locator_matches_empty_contenteditable_in_child_iframe() -> None:
    editor = _FakeElement(
        text="",
        attrs={"contenteditable": "", "data-placeholder": "添加描述"},
        tag="div",
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        selectors={"[contenteditable][data-placeholder='添加描述']": [editor]},
        locator_unsupported=True,
    )
    page = _FakePage([main, child])

    locator = _visible_element_handle(
        page,
        [
            "[contenteditable][data-placeholder='添加描述']",
            "[contenteditable][data-placeholder*='描述']",
        ],
    )
    assert locator is editor


def test_fill_description_in_child_iframe_contenteditable() -> None:
    editor = _FakeElement(
        attrs={"contenteditable": "", "data-placeholder": "添加描述"},
        tag="div",
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        selectors={"[contenteditable][data-placeholder*='描述']": [editor]},
        locator_unsupported=True,
    )
    page = _FakePage([main, child])

    _fill_field(
        page,
        {"description_input": ["[contenteditable][data-placeholder*='描述']"]},
        "description_input",
        "测试描述内容",
    )
    assert editor.text == "测试描述内容"


def test_draft_save_button_is_found_inside_child_iframe() -> None:
    save = _FakeElement(text="保存草稿", tag="button")
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        roles={("button", "保存草稿", True): [save]},
        locator_unsupported=True,
    )
    page = _FakePage([main, child])

    assert _draft_save_button(
        page, {"draft_save_button_text": ["保存草稿"]}
    ) is save


def _save_button_page(*buttons):
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        roles={("button", "保存草稿", True): list(buttons)},
        locator_unsupported=True,
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    return _FakePage([main, child]), child


_SAVE_SELECTORS = {"draft_save_button_text": ["保存草稿"]}


def test_manual_save_monitor_script_is_read_only() -> None:
    """The installed monitor must observe only - never act on the page."""
    lowered = MANUAL_SAVE_MONITOR_JS.lower()
    for forbidden in (
        "preventdefault",
        "stoppropagation",
        "stopimmediatepropagation",
        "dispatchevent",
        ".click(",
        ".submit(",
    ):
        assert forbidden not in lowered
    for required in ("pointerdown", "pointerup", "mousedown", "mouseup", "click", "mutationobserver"):
        assert required in lowered


class _MonitorFrame(_FakeFrame):
    def __init__(self, url, events, mutations):
        super().__init__(url)
        self.events = events
        self.mutations = mutations

    def evaluate(self, expression, *args):
        if "__CHANNELS_MANUAL_SAVE_EVENTS__" in expression:
            return self.events
        if "__CHANNELS_MANUAL_SAVE_MUTATIONS__" in expression:
            return self.mutations
        if "MutationObserver" in expression:
            return "installed"
        return super().evaluate(expression, *args)


def _manual_save_page(events, mutations):
    frame = _MonitorFrame(
        "https://channels.weixin.qq.com/micro/content/post/create", events, mutations
    )
    return _FakePage([_FakeFrame("https://channels.weixin.qq.com/platform/post/create"), frame])


def test_manual_save_monitor_install_and_read() -> None:
    events = [{"type": "click", "isTrusted": True, "nearestButton": {"innerText": "保存草稿"}}]
    page = _manual_save_page(events, [])
    selectors = {"creator_form_frame_path": "/micro/content/post/create"}

    installed = install_manual_save_monitor(page, selectors)
    assert installed["installed"] is True
    assert installed["frame_url"].endswith("/micro/content/post/create")

    trace = read_manual_save_monitor(page, selectors)
    assert trace["events"] == events
    assert trace["mutations"] == []


def test_summarize_manual_save_click_from_real_capture() -> None:
    def event(kind):
        return {
            "type": kind,
            "isTrusted": True,
            "nearestButton": {
                "innerText": "保存草稿",
                "className": "weui-desktop-btn weui-desktop-btn_default",
            },
            "target": {"innerText": "保存草稿"},
            "hitElement": {"innerText": "保存草稿"},
        }

    events = [event(kind) for kind in ("pointerdown", "mousedown", "pointerup", "mouseup", "click")]

    summary = summarize_manual_save_click(events, [])

    assert summary["trusted_click_count"] == 1
    assert summary["save_button_clicked"] is True
    assert summary["target_buttons"] == ["保存草稿"]
    assert summary["hit_elements"] == ["保存草稿"]
    assert summary["same_node_across_pointer_phases"] is True
    assert summary["mutation_count"] == 0


def test_summarize_manual_save_click_records_replacement() -> None:
    mutations = [{"type": "childList", "target": {"innerText": "保存草稿"}}]
    summary = summarize_manual_save_click([], mutations)
    assert summary["trusted_click_count"] == 0
    assert summary["save_button_clicked"] is False
    assert summary["mutation_count"] == 1


def test_finalize_draft_verification_requires_unique_new_row(tmp_path, monkeypatch) -> None:
    """Only one matching DraftListManager row may produce DRAFT_SAVED."""
    import wechat_video.channels_uploader as uploader

    monkeypatch.setattr(uploader, "_save_job", lambda *_a, **_k: None)
    after = {"url": "https://channels.weixin.qq.com/platform/post/draftListManager"}
    row = "临界半径如何决定成核 草稿 2026-11-22 20:30"
    job = {"save_click_count": 1, "save_click_returned": True}

    uploader._finalize_draft_verification(
        job,
        tmp_path / "job.json",
        after=after,
        verified=[row],
        verification_history=[{"match_count": 1}],
        title="临界半径如何决定成核",
    )

    assert job["state"] == "DRAFT_SAVED"
    assert job["verified_draft"]["row_text"] == row
    assert job["verified_draft"]["title"] == "临界半径如何决定成核"
    assert job["post_upload_snapshot"] == after
    assert job["automatic_publication"] is False
    assert job["save_action"]["click_count"] == 1


@pytest.mark.parametrize("rows", [[], ["row one", "row two"]])
def test_finalize_draft_verification_rejects_non_unique_rows(
    tmp_path, monkeypatch, rows
) -> None:
    import wechat_video.channels_uploader as uploader

    monkeypatch.setattr(uploader, "_save_job", lambda *_a, **_k: None)
    job = {"save_click_count": 1, "save_click_returned": True}

    with pytest.raises(UploadUnknownError):
        uploader._finalize_draft_verification(
            job,
            tmp_path / "job.json",
            after={"url": "https://channels.weixin.qq.com/platform/post/draftListManager"},
            verified=rows,
            verification_history=[{"match_count": len(rows)}],
            title="临界半径如何决定成核",
        )

    assert job["state"] == "UPLOAD_UNKNOWN"
    assert "verified_draft" not in job
    assert job["verification_matches"] == len(rows)


def test_click_draft_save_once_rebinds_after_spa_rerender(tmp_path, monkeypatch) -> None:
    """A handle cached before an SPA re-render is not the one that gets clicked."""
    import wechat_video.channels_uploader as uploader

    old = _FakeElement(text="保存草稿", tag="button")
    fresh = _FakeElement(text="保存草稿", tag="button")
    page, child = _save_button_page(old)
    assert _draft_save_button(page, _SAVE_SELECTORS) is old
    # SPA re-render swaps the live node.
    child.roles[("button", "保存草稿", True)] = [fresh]
    saved = []
    monkeypatch.setattr(uploader, "_save_job", lambda _p, j: saved.append(dict(j)))
    job = {"state": "PREPARED"}

    _click_draft_save_once(page, _SAVE_SELECTORS, job, tmp_path / "job.json")

    assert fresh.clicked is True
    assert old.clicked is False
    assert fresh.native_click_count == 1
    assert job["state"] == "SAVE_REQUESTED"
    assert job["save_click_attempted"] is True
    assert job["save_click_returned"] is True
    assert job["save_click_count"] == 1
    diag = job["save_button_diagnostics"]
    assert diag["frame_url"] == "https://channels.weixin.qq.com/micro/content/post/create"
    assert diag["visible"] is True and diag["enabled"] is True
    assert diag["binding"] == "fresh_same_frame_element_handle"
    assert saved[-1]["state"] == "SAVE_REQUESTED"


def test_click_draft_save_once_fails_closed_on_multiple_buttons(tmp_path, monkeypatch) -> None:
    import wechat_video.channels_uploader as uploader

    first = _FakeElement(text="保存草稿", tag="button")
    second = _FakeElement(text="保存草稿", tag="button")
    page, _ = _save_button_page(first, second)
    monkeypatch.setattr(uploader, "_save_job", lambda _p, _j: None)
    job = {"state": "PREPARED"}

    with pytest.raises(UploadBlockedError, match="More than one visible exact"):
        _click_draft_save_once(page, _SAVE_SELECTORS, job, tmp_path / "job.json")

    assert first.clicked is False and second.clicked is False
    assert job["state"] == "PREPARED"


@pytest.mark.parametrize("visible,enabled", [(False, True), (True, False)])
def test_click_draft_save_once_skips_hidden_or_disabled_button(
    tmp_path, monkeypatch, visible, enabled
) -> None:
    import wechat_video.channels_uploader as uploader

    button = _FakeElement(text="保存草稿", tag="button", visible=visible, enabled=enabled)
    page, _ = _save_button_page(button)
    monkeypatch.setattr(uploader, "_save_job", lambda _p, _j: None)
    job = {"state": "PREPARED"}

    with pytest.raises(UploadBlockedError):
        _click_draft_save_once(page, _SAVE_SELECTORS, job, tmp_path / "job.json")

    assert button.clicked is False
    assert job["state"] == "PREPARED"


def test_click_draft_save_once_records_full_timeout_error(tmp_path, monkeypatch) -> None:
    """A raised click records message and traceback and leaves state uncertain."""
    import wechat_video.channels_uploader as uploader

    error = TimeoutError("Element is not attached to the DOM after 10000ms")
    button = _FakeElement(text="保存草稿", tag="button", click_error=error)
    page, _ = _save_button_page(button)
    monkeypatch.setattr(uploader, "_save_job", lambda _p, _j: None)
    job = {"state": "PREPARED"}

    with pytest.raises(UploadUnknownError):
        _click_draft_save_once(page, _SAVE_SELECTORS, job, tmp_path / "job.json")

    assert button.native_click_count == 1
    assert button.dom_click_count == 0
    assert job["state"] == "UPLOAD_UNKNOWN"
    assert job["save_click_attempted"] is True
    assert job["save_click_returned"] is False
    assert job["save_click_error_type"] == "TimeoutError"
    assert "not attached to the DOM" in job["save_click_error_message"]
    assert "Traceback" in job["save_click_traceback"]
    assert job["save_click_count"] == 1
    assert "save_failed_at" in job


def test_click_draft_save_once_never_uses_dom_click_fallback(tmp_path, monkeypatch) -> None:
    """Detached/frame errors must not trigger a second form of activation."""
    import wechat_video.channels_uploader as uploader

    error = RuntimeError("Element is not attached to the DOM")
    button = _FakeElement(text="保存草稿", tag="button", click_error=error)
    page, _ = _save_button_page(button)
    monkeypatch.setattr(uploader, "_save_job", lambda _p, _j: None)
    job = {"state": "PREPARED"}

    with pytest.raises(UploadUnknownError):
        _click_draft_save_once(page, _SAVE_SELECTORS, job, tmp_path / "job.json")

    assert button.native_click_count == 1
    assert button.dom_click_count == 0
    assert job["state"] == "UPLOAD_UNKNOWN"
    assert job["save_click_error_message"] == "Element is not attached to the DOM"


def test_open_create_view_activates_unique_post_card_spa_entry(monkeypatch) -> None:
    import wechat_video.channels_uploader as uploader

    upload = _FakeElement(
        attrs={"accept": "video/mp4,video/*"},
        tag="input",
        visible=False,
    )
    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    entry_clicks = {"count": 0}

    def mount_creator_form():
        entry_clicks["count"] += 1
        create_frame.selectors["input[type='file']"] = [upload]

    entry = _FakeElement(
        text="发表视频",
        tag="button",
        attrs={"href": "/platform/post/create"},
        ancestors=[{"tag": "a", "class": "creator-entry-link"}],
        on_click=mount_creator_form,
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform")
    card = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html",
        selectors={"button, [role='button']": [entry]},
        locator_unsupported=True,
    )
    page = _FakePage([main, create_frame, card])
    identity_checks = []
    monkeypatch.setattr(
        uploader,
        "_ensure_account_identity",
        lambda *_args, **_kwargs: identity_checks.append("verified"),
    )

    _open_create_view(
        page,
        {
            "platform_url": "https://channels.weixin.qq.com/platform",
            "account_name": "成核生长",
        },
        {
            "create_nav_frame_path": "/micro/content/iframe/post-card.html",
            "create_nav_button_text": "发表视频",
            "create_nav_timeout_seconds": 0,
        },
    )

    assert page.url == "https://channels.weixin.qq.com/platform"
    assert identity_checks == ["verified"]
    assert entry.clicked is True
    assert entry_clicks["count"] == 1
    assert create_frame.selectors["input[type='file']"] == [upload]
    assert card.locator_calls == []
    assert "__CHANNELS_VISIBLE_ELEMENT_SCAN__" in card.last_evaluate_expression


def test_open_create_view_matches_aria_label_when_button_has_no_rendered_text(
    monkeypatch,
) -> None:
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    entry = _FakeElement(
        text="",
        attrs={"aria-label": "发表视频"},
        tag="button",
        ancestors=[{"tag": "a", "href": "/micro/content/post/create"}],
        on_click=lambda: create_frame.selectors.update(
            {"input[type='file']": [_FakeElement(attrs={"accept": "video/*"}, tag="input")]}
        ),
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform")
    card = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html",
        selectors={"button, [role='button']": [entry]},
        locator_unsupported=True,
    )
    page = _FakePage([main, card, create_frame])
    monkeypatch.setattr(
        uploader, "_ensure_account_identity", lambda *_args, **_kwargs: None
    )

    _open_create_view(
        page,
        {
            "platform_url": "https://channels.weixin.qq.com/platform",
            "account_name": "成核生长",
        },
        {
            "create_nav_frame_path": "/micro/content/iframe/post-card.html",
            "create_nav_button_text": "发表视频",
            "create_nav_timeout_seconds": 0,
        },
    )

    assert entry.clicked is True
    assert card.locator_calls == []
    assert "getAttribute(\"aria-label\")" in card.last_evaluate_expression


def test_open_create_view_failure_captures_target_frame_button_diagnostics(
    monkeypatch,
) -> None:
    import wechat_video.channels_uploader as uploader

    unrelated = _FakeElement(
        text="管理内容",
        attrs={"aria-label": "管理内容"},
        tag="button",
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform")
    card = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html",
        selectors={"button, [role='button']": [unrelated]},
        locator_unsupported=True,
    )
    page = _FakePage([main, card])
    monkeypatch.setattr(
        uploader, "_ensure_account_identity", lambda *_args, **_kwargs: None
    )

    with pytest.raises(UploadBlockedError, match="Sanitized target-frame button diagnostics") as caught:
        _open_create_view(
            page,
            {
                "platform_url": "https://channels.weixin.qq.com/platform",
                "account_name": "成核生长",
            },
            {
                "create_nav_frame_path": "/micro/content/iframe/post-card.html",
                "create_nav_button_text": "发表视频",
                "create_nav_timeout_seconds": 0,
            },
        )

    diagnostics = caught.value.diagnostics
    assert diagnostics["expected_button_label"] == "发表视频"
    assert diagnostics["matching_frame_count"] == 1
    assert diagnostics["frame_observations"][0]["frame_url"] == card.url
    assert diagnostics["frame_observations"][0]["ready_state"] == "complete"
    assert diagnostics["frame_observations"][0]["visible_buttons"][0]["matched_label"] == "管理内容"
    assert diagnostics["frame_observations"][0]["visible_buttons"][0]["label_source"] == "visible_text"
    assert unrelated.clicked is False


def test_open_create_view_rejects_ambiguous_creator_entry_without_clicking(
    monkeypatch,
) -> None:
    import wechat_video.channels_uploader as uploader

    first = _FakeElement(text="发表视频", tag="button")
    second = _FakeElement(text="发表视频", tag="button")
    main = _FakeFrame("https://channels.weixin.qq.com/platform")
    card = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html",
        selectors={"button, [role='button']": [first, second]},
        locator_unsupported=True,
    )
    page = _FakePage([main, card])
    monkeypatch.setattr(
        uploader, "_ensure_account_identity", lambda *_args, **_kwargs: None
    )

    with pytest.raises(UploadBlockedError, match="structurally-proven"):
        _open_create_view(
            page,
            {
                "platform_url": "https://channels.weixin.qq.com/platform",
                "account_name": "成核生长",
            },
            {
                "create_nav_frame_path": "/micro/content/iframe/post-card.html",
                "create_nav_button_text": "发表视频",
                "create_nav_timeout_seconds": 0,
            },
        )

    assert first.clicked is False
    assert second.clicked is False


def test_open_create_view_does_not_click_same_text_in_unconfigured_frame(
    monkeypatch,
) -> None:
    import wechat_video.channels_uploader as uploader

    entry = _FakeElement(text="发表视频", tag="button")
    main = _FakeFrame("https://channels.weixin.qq.com/platform")
    wrong_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        selectors={"button, [role='button']": [entry]},
    )
    page = _FakePage([main, wrong_frame])
    monkeypatch.setattr(
        uploader, "_ensure_account_identity", lambda *_args, **_kwargs: None
    )

    with pytest.raises(UploadBlockedError, match="structurally-proven"):
        _open_create_view(
            page,
            {
                "platform_url": "https://channels.weixin.qq.com/platform",
                "account_name": "成核生长",
            },
            {
                "create_nav_frame_path": "/micro/content/iframe/post-card.html",
                "create_nav_button_text": "发表视频",
                "create_nav_timeout_seconds": 0,
            },
        )

    assert entry.clicked is False


def _create_view_config() -> dict:
    return {
        "platform_url": "https://channels.weixin.qq.com/platform",
        "account_name": "成核生长",
    }


def _create_view_selectors(**overrides) -> dict:
    selectors = {
        "create_nav_frame_path": "/micro/content/iframe/post-card.html",
        "create_nav_button_text": "发表视频",
        "create_nav_timeout_seconds": 0,
    }
    selectors.update(overrides)
    return selectors


def _post_card_frame(*elements) -> _FakeFrame:
    return _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html",
        selectors={"button, [role='button']": list(elements)},
        locator_unsupported=True,
    )


def test_visible_element_handles_retries_transient_bind_failure() -> None:
    """An SPA re-render between scan and bind must not block a read-only lookup."""
    entry = _FakeElement(text="草稿箱", tag="a")
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/platform",
        selectors={"a": [entry]},
        bind_failures=1,
    )
    page = _FakePage([frame])

    handles = _visible_element_handles(page, "a", limit=8, contains_text="草稿箱")

    assert handles == [entry]


def test_visible_element_handles_retries_benign_spa_scan_error() -> None:
    """The SPA's ignorable LogicError must not abort a read-only lookup."""
    entry = _FakeElement(text="草稿箱", tag="a")
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/platform",
        selectors={"a": [entry]},
        scan_failures=1,
    )
    page = _FakePage([frame])

    handles = _visible_element_handles(page, "a", limit=8, contains_text="草稿箱")

    assert handles == [entry]


class _FakeUploadInput:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def set_input_files(self, path, timeout=None):
        self.calls += 1
        if self.error is not None:
            raise RuntimeError(self.error)


class _StrictContentEditable:
    """Models a real ElementHandle where inner_text() rejects a timeout kwarg."""

    def __init__(self, value=""):
        self.value = value
        self.filled = None

    def fill(self, text, timeout=None):
        self.filled = text

    def input_value(self, *args, **kwargs):
        raise ValueError("not an input element")

    def inner_text(self, *args, **kwargs):
        if args or kwargs:
            raise TypeError("inner_text() got an unexpected keyword argument 'timeout'")
        return self.value


def test_fill_field_reads_contenteditable_without_timeout_kwarg(monkeypatch) -> None:
    """The ElementHandle inner_text fallback must not pass a timeout argument."""
    import wechat_video.channels_uploader as uploader

    field = _StrictContentEditable(value="临界半径如何决定成核")
    monkeypatch.setattr(uploader, "_visible_element_handle", lambda *_a, **_k: field)

    uploader._fill_field(
        _FakePage([_FakeFrame("https://channels.weixin.qq.com/platform")]),
        {"title_input": ["textarea"]},
        "title_input",
        "临界半径如何决定成核",
    )

    assert field.filled == "临界半径如何决定成核"


def test_set_video_file_prefers_stable_locator(monkeypatch) -> None:
    """The historically proven, auto-rebinding Locator path is used first."""
    import wechat_video.channels_uploader as uploader

    upload = _FakeElement(attrs={"accept": "video/*"}, tag="input")
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        selectors={"input[type='file'][accept*='video']": [upload]},
    )
    monkeypatch.setattr(
        uploader,
        "_video_file_input",
        lambda *_a, **_k: pytest.fail("DOM-handle fallback must not be used"),
    )

    uploader._set_video_file(_FakePage([frame]), {}, "video.mp4")

    assert upload.files_set == ["video.mp4"]


def test_set_video_file_refreshes_detached_input(monkeypatch) -> None:
    """A detached input is rebound once before any file is actually selected."""
    import wechat_video.channels_uploader as uploader

    stale = _FakeUploadInput("Cannot set input files to detached element")
    fresh = _FakeUploadInput()
    inputs = iter([stale, fresh])
    monkeypatch.setattr(uploader, "_video_file_input", lambda *_a, **_k: next(inputs))

    uploader._set_video_file(
        _FakePage([_FakeFrame("https://channels.weixin.qq.com/platform")]), {}, "video.mp4"
    )

    assert stale.calls == 1
    assert fresh.calls == 1


def test_set_video_file_does_not_retry_other_errors(monkeypatch) -> None:
    """Only detachment is retried; every other failure surfaces immediately."""
    import wechat_video.channels_uploader as uploader

    failing = _FakeUploadInput("permission denied")
    lookups = []

    def fake_lookup(*_a, **_k):
        lookups.append(1)
        return failing

    monkeypatch.setattr(uploader, "_video_file_input", fake_lookup)

    with pytest.raises(RuntimeError, match="permission denied"):
        uploader._set_video_file(
        _FakePage([_FakeFrame("https://channels.weixin.qq.com/platform")]), {}, "video.mp4"
    )

    assert failing.calls == 1
    assert len(lookups) == 1


def test_open_create_view_distinguishes_same_named_buttons_by_structure(monkeypatch) -> None:
    """Shape (a): identical labels, one proven create-navigation target."""
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    decoy = _FakeElement(
        text="发表视频",
        tag="button",
        attrs={"class": "post-card-teaser-button", "data-slot": "teaser"},
        ancestors=[{"tag": "div", "class": "post-card-promo"}],
    )
    correct = _FakeElement(
        text="发表视频",
        tag="button",
        attrs={"class": "publish-action", "data-nav-url": "/platform/post/create"},
        ancestors=[{"tag": "div", "class": "post-card-actions"}],
        on_click=lambda: create_frame.selectors.update(
            {"input[type='file']": [_FakeElement(attrs={"accept": "video/*"}, tag="input")]}
        ),
    )
    page = _FakePage(
        [_FakeFrame("https://channels.weixin.qq.com/platform"),
         _post_card_frame(decoy, correct), create_frame]
    )
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert correct.clicked is True
    assert decoy.clicked is False
    assert create_frame.selectors["input[type='file']"]
    assert page.wait_calls[0] == 750


def test_open_create_view_deduplicates_repeated_scans_of_same_button(monkeypatch) -> None:
    """Shape (b): the same node observed through several CDP frames/pages."""
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    shared = _FakeElement(
        text="发表视频",
        tag="button",
        attrs={"href": "/platform/post/create"},
        rect={"x": 985, "y": 485, "w": 120, "h": 40},
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(shared),
        _post_card_frame(shared),
        create_frame,
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    # Two qualifying records would have failed closed as ambiguous; one click
    # proves the duplicate scan records collapsed into a single candidate.
    assert shared.clicked is True


def test_open_create_view_fails_closed_on_indistinguishable_ambiguity(monkeypatch) -> None:
    """Shape (c): two genuinely distinct but structurally identical buttons."""
    import wechat_video.channels_uploader as uploader

    first = _FakeElement(
        text="发表视频", tag="button",
        attrs={"class": "post-card__cta"},
        ancestors=[{"tag": "div", "class": "post-card"}],
    )
    second = _FakeElement(
        text="发表视频", tag="button",
        attrs={"class": "post-card__cta"},
        ancestors=[{"tag": "div", "class": "post-card"}],
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(first, second),
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    with pytest.raises(UploadBlockedError) as caught:
        _open_create_view(page, _create_view_config(), _create_view_selectors())

    diagnostics = caught.value.diagnostics
    assert diagnostics["unique_candidate_count"] == 2
    assert diagnostics["qualifying_candidate_count"] == 0
    assert len(diagnostics["creator_entry_candidates"]) == 2
    assert diagnostics["creator_entry_candidates"][0]["ancestors"]
    assert first.clicked is False
    assert second.clicked is False


def test_open_create_view_clicks_primary_context_for_two_href_free_spa_entries(
    monkeypatch,
) -> None:
    """Real 20261122_192030 DOM shape: two identical buttons, no URL attribute.

    Both are genuine creation entries in different UI states; the persistent
    list-header action must win over the empty-state action without using
    coordinates, DOM order or array index.
    """
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    markup = (
        '<button type="button" class="weui-desktop-btn weui-desktop-btn_primary">'
        "发表视频</button>"
    )
    attrs = {"type": "button", "class": "weui-desktop-btn weui-desktop-btn_primary"}

    def mount_form():
        create_frame.selectors["input[type='file']"] = [
            _FakeElement(attrs={"accept": "video/*"}, tag="input")
        ]

    header = _FakeElement(
        text="发表视频",
        tag="button",
        attrs=dict(attrs),
        outer_html=markup,
        rect={"x": 985, "y": 485, "w": 120, "h": 40},
        ancestors=[
            {"tag": "div", "class": "weui-desktop-btn_wrp"},
            {"tag": "div", "class": "post"},
            {"tag": "div", "class": "post-list-header"},
            {"tag": "div", "class": "post-list"},
            {"tag": "div", "class": "finder-card wrap"},
        ],
        on_click=mount_form,
    )
    empty_state = _FakeElement(
        text="发表视频",
        tag="button",
        attrs=dict(attrs),
        outer_html=markup,
        rect={"x": 569, "y": 791, "w": 120, "h": 40},
        ancestors=[
            {"tag": "div", "class": "weui-desktop-btn_wrp"},
            {"tag": "div", "class": "option"},
            {"tag": "div", "class": "none-post"},
            {"tag": "div", "class": "post-list"},
            {"tag": "div", "class": "finder-card wrap"},
        ],
        on_click=mount_form,
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(header, empty_state),
        create_frame,
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert header.clicked is True
    assert empty_state.clicked is False
    assert create_frame.selectors["input[type='file']"]


def test_open_create_view_falls_back_to_single_dom_click_when_native_click_fails(
    monkeypatch,
) -> None:
    """Off-viewport SPA button: native click rejected, one DOM click activates."""
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    activations = {"count": 0}

    def mount_form():
        activations["count"] += 1
        if create_frame not in page.frames:
            page.frames.append(create_frame)
        create_frame.selectors["input[type='file']"] = [
            _FakeElement(attrs={"accept": "video/*"}, tag="input")
        ]

    entry = _FakeElement(
        text="发表视频",
        tag="button",
        rect={"x": 985, "y": 485, "w": 120, "h": 40},
        ancestors=[
            {"tag": "div", "class": "post-list-header"},
            {"tag": "div", "class": "post-list"},
            {"tag": "div", "class": "finder-card wrap"},
        ],
        click_error="Element is outside of viewport",
        on_click=mount_form,
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(entry),
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert entry.native_click_count == 1
    assert entry.dom_click_count == 1
    assert activations["count"] == 1
    assert create_frame.selectors["input[type='file']"]


def test_open_create_view_fails_closed_when_two_spa_entries_share_context(
    monkeypatch,
) -> None:
    """Two proven entries at the SAME priority remain ambiguous -> no click."""
    import wechat_video.channels_uploader as uploader

    first = _FakeElement(
        text="发表视频",
        tag="button",
        rect={"x": 985, "y": 485, "w": 120, "h": 40},
        ancestors=[
            {"tag": "div", "class": "post-list-header"},
            {"tag": "div", "class": "post-list"},
            {"tag": "div", "class": "finder-card wrap"},
        ],
    )
    second = _FakeElement(
        text="发表视频",
        tag="button",
        rect={"x": 569, "y": 791, "w": 120, "h": 40},
        ancestors=[
            {"tag": "div", "class": "post-list-header"},
            {"tag": "div", "class": "post-list"},
            {"tag": "div", "class": "finder-card wrap"},
        ],
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(first, second),
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    with pytest.raises(UploadBlockedError, match="same highest-priority") as caught:
        _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert caught.value.diagnostics["qualifying_candidate_count"] == 2
    assert first.clicked is False
    assert second.clicked is False


def test_open_create_view_ignores_same_name_button_outside_post_card(
    monkeypatch,
) -> None:
    """A same-name button lacking post-card ancestry can never be selected."""
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )

    def mount_form():
        create_frame.selectors["input[type='file']"] = [
            _FakeElement(attrs={"accept": "video/*"}, tag="input")
        ]

    outside = _FakeElement(
        text="发表视频",
        tag="button",
        rect={"x": 10, "y": 10, "w": 120, "h": 40},
        ancestors=[{"tag": "div", "class": "site-global-header"}],
    )
    inside = _FakeElement(
        text="发表视频",
        tag="button",
        rect={"x": 985, "y": 485, "w": 120, "h": 40},
        ancestors=[
            {"tag": "div", "class": "post-list-header"},
            {"tag": "div", "class": "post-list"},
            {"tag": "div", "class": "finder-card wrap"},
        ],
        on_click=mount_form,
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(outside, inside),
        create_frame,
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert inside.clicked is True
    assert outside.clicked is False


def test_open_create_view_ignores_proven_entry_in_wrong_frame(monkeypatch) -> None:
    """Shape (d): a valid-looking entry in a different frame must never be clicked."""
    import wechat_video.channels_uploader as uploader

    wrong = _FakeElement(
        text="发表视频", tag="button", attrs={"href": "/platform/post/create"}
    )
    wrong_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        selectors={"button, [role='button']": [wrong]},
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(),
        wrong_frame,
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    with pytest.raises(UploadBlockedError, match="structurally-proven"):
        _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert wrong.clicked is False


def test_open_create_view_clicks_unique_structural_entry_once(monkeypatch) -> None:
    """Shape (e): one unique, visible, enabled, structurally-proven entry."""
    import wechat_video.channels_uploader as uploader

    clicks = {"count": 0}
    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )

    def on_click():
        clicks["count"] += 1
        create_frame.selectors["input[type='file']"] = [
            _FakeElement(attrs={"accept": "video/*"}, tag="input")
        ]

    entry = _FakeElement(
        text="发表视频",
        tag="button",
        ancestors=[{"tag": "a", "href": "/micro/content/post/create", "class": "create-entry"}],
        on_click=on_click,
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(entry),
        create_frame,
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert entry.clicked is True
    assert clicks["count"] == 1


def test_open_create_view_waits_for_creator_form_frame_after_click(monkeypatch) -> None:
    """The create form frame is awaited only after the CTA has been clicked."""
    import wechat_video.channels_uploader as uploader

    create_frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create"
    )
    def mount_form():
        if create_frame not in page.frames:
            page.frames.append(create_frame)

    entry = _FakeElement(
        text="发表视频", tag="button", attrs={"href": "/platform/post/create"},
        on_click=mount_form,
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(entry),
    ])
    assert create_frame not in page.frames
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    _open_create_view(page, _create_view_config(), _create_view_selectors())

    assert entry.clicked is True
    assert create_frame in page.frames
    assert page.wait_calls == [750]


def test_open_create_view_fails_closed_when_form_frame_never_mounts(monkeypatch) -> None:
    import wechat_video.channels_uploader as uploader

    entry = _FakeElement(
        text="发表视频", tag="button", attrs={"href": "/platform/post/create"}
    )
    page = _FakePage([
        _FakeFrame("https://channels.weixin.qq.com/platform"),
        _post_card_frame(entry),
    ])
    monkeypatch.setattr(uploader, "_ensure_account_identity", lambda *_a, **_k: None)

    with pytest.raises(UploadBlockedError, match="did not mount") as caught:
        _open_create_view(
            page,
            _create_view_config(),
            _create_view_selectors(creator_form_ready_timeout_seconds=0),
        )

    assert entry.clicked is True
    assert caught.value.diagnostics["expected_creator_form_frame_path"] == (
        "/micro/content/post/create"
    )


def test_video_file_input_is_found_in_main_frame_when_form_fields_are_in_iframe() -> None:
    upload = _FakeElement(
        attrs={"accept": "video/mp4,video/x-m4v,video/*", "multiple": "multiple"},
        tag="input",
    )
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        selectors={
            "input[type='file'][accept*='video']": [upload],
            "input[type='file']": [upload],
        },
    )
    child = _FakeFrame("https://channels.weixin.qq.com/micro/content/post/create")
    page = _FakePage([main, child])

    assert _video_file_input(
        page,
        {"video_file_input": ["input[type='file'][accept*='video']"], "video_file_input_timeout_seconds": 0},
    ) is upload


def test_video_file_input_binds_node_inside_child_frame_without_locator_count() -> None:
    upload = _FakeElement(
        attrs={"accept": "video/mp4"},
        tag="input",
        visible=False,
    )
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        selectors={"input[type='file']": [upload]},
        locator_unsupported=True,
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    page = _FakePage([main, child])

    assert _video_file_input(
        page,
        {"video_file_input": ["input[type='file']"], "video_file_input_timeout_seconds": 0},
    ) is upload


def test_video_file_input_ignores_image_control_and_allows_hidden_video_input() -> None:
    video = _FakeElement(
        attrs={"accept": "video/mp4,video/*", "aria-label": "上传视频"},
        tag="input",
        visible=False,
    )
    cover = _FakeElement(
        attrs={"accept": "image/png,image/jpeg", "aria-label": "上传封面"},
        tag="input",
        visible=True,
    )
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        selectors={"input[type='file']": [video, cover]},
    )
    page = _FakePage([main])

    assert _video_file_input(
        page,
        {"video_file_input": ["input[type='file']"], "video_file_input_timeout_seconds": 0},
    ) is video


def test_video_file_input_uses_video_label_when_accept_is_missing() -> None:
    cover = _FakeElement(
        attrs={"labels": ["上传封面"], "context_text": ["封面图片"]},
        tag="input",
    )
    video = _FakeElement(
        attrs={"labels": ["上传视频"], "context_text": ["选择视频文件"]},
        tag="input",
    )
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        selectors={"input[type='file']": [cover, video]},
    )
    page = _FakePage([main])

    assert _video_file_input(
        page,
        {"video_file_input": ["input[type='file']"], "video_file_input_timeout_seconds": 0},
    ) is video


def test_video_file_input_waits_for_delayed_frame_mount() -> None:
    upload = _FakeElement(
        attrs={"accept": "video/mp4"},
        tag="input",
        visible=False,
    )
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    page = _FakePage(
        [main],
        on_wait=lambda _milliseconds: main.selectors.update(
            {"input[type='file']": [upload]}
        ),
    )

    assert _video_file_input(
        page,
        {"video_file_input": ["input[type='file']"], "video_file_input_timeout_seconds": 1},
    ) is upload
    assert page.wait_calls == [500]


def test_video_file_input_rejects_multiple_equally_valid_video_controls() -> None:
    first = _FakeElement(attrs={"accept": "video/mp4"}, tag="input")
    second = _FakeElement(attrs={"accept": "video/*"}, tag="input")
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        selectors={"input[type='file']": [first, second]},
    )
    page = _FakePage([main])

    with pytest.raises(UploadBlockedError, match="Candidate summary"):
        _video_file_input(
            page,
            {"video_file_input": ["input[type='file']"], "video_file_input_timeout_seconds": 0},
        )


def test_video_file_input_fails_closed_when_any_frame_cannot_be_scanned() -> None:
    upload = _FakeElement(attrs={"accept": "video/mp4"}, tag="input")
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        selectors={"input[type='file']": [upload]},
    )
    unscannable = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        video_scan_error=True,
    )
    page = _FakePage([main, unscannable])

    with pytest.raises(UploadBlockedError, match="frame scan summary"):
        _video_file_input(
            page,
            {"video_file_input": ["input[type='file']"], "video_file_input_timeout_seconds": 0},
        )


def test_account_identity_waits_and_checks_child_frames() -> None:
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        identity_matches=[{
            "tag": "h2",
            "evidence_type": "visible_text",
            "matched_value": "成核生长",
            "region": "semantic_account_surface",
            "semantic_account_surface": True,
            "identity_surface": "finder_nickname",
            "left": 235,
            "top": 88,
            "width": 212,
            "height": 21,
        }],
    )
    page = _FakePage([main, child])

    assert _wait_for_account_identity(
        page,
        "成核生长",
        {"account_identity": {"exact_text": "成核生长"}},
        wait_seconds=0,
    ) is True


def test_draft_list_identity_waits_for_delayed_spa_account_node() -> None:
    identity_evidence = {
        "tag": "h2",
        "evidence_type": "visible_text",
        "matched_value": "成核生长",
        "region": "semantic_account_surface",
        "semantic_account_surface": True,
        "identity_surface": "finder_nickname",
        "left": 235,
        "top": 88,
        "width": 212,
        "height": 21,
    }
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/list",
        identity_matches=[],
    )
    page = _FakePage(
        [frame],
        on_wait=lambda _milliseconds: frame.identity_matches.append(identity_evidence),
    )

    _ensure_draft_list_account_identity(
        page,
        {"account_name": "成核生长", "ui_ready_timeout_seconds": 15},
        {"account_identity": {"exact_text": "成核生长"}},
    )

    assert page.wait_calls == [500]


def test_account_identity_uses_visible_lower_left_dom_text_and_accessible_attributes() -> None:
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        identity_matches=[{
            "tag": "span",
            "evidence_type": "visible_text",
            "matched_value": "成核生长",
            "region": "lower_left",
            "semantic_account_surface": False,
            "left": 12,
            "top": 930,
            "width": 80,
            "height": 20,
        }],
    )
    page = _FakePage([main])

    evidence = _account_identity_evidence(main, "成核生长")
    assert evidence[0]["region"] == "lower_left"
    assert _wait_for_account_identity(
        page, "成核生长", {"account_identity": {"exact_text": "成核生长"}}, wait_seconds=0
    ) is True
    assert "__CHANNELS_ACCOUNT_IDENTITY_SCAN__" in main.last_evaluate_expression
    assert 'element.classList.contains("finder-nickname")' in main.last_evaluate_expression
    assert "normalize(element.innerText || element.textContent) === expected" in main.last_evaluate_expression


def test_account_identity_rejects_generic_page_mention_without_account_surface() -> None:
    generic_text = _FakeElement(text="成核生长", tag="p")
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/platform",
        selectors={"body *": [generic_text]},
    )
    page = _FakePage([frame])

    assert _wait_for_account_identity(
        page,
        "成核生长",
        {"account_identity": {"exact_text": "成核生长"}},
        wait_seconds=0,
    ) is False
    assert "__CHANNELS_ACCOUNT_IDENTITY_SCAN__" in frame.last_evaluate_expression
    assert "__CHANNELS_VISIBLE_ELEMENT_SCAN__" not in frame.last_evaluate_expression


def test_account_identity_accepts_exact_finder_nickname_in_headless_header() -> None:
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/platform",
        identity_matches=[{
            "tag": "h2",
            "evidence_type": "visible_text",
            "matched_value": "成核生长",
            "region": "semantic_account_surface",
            "semantic_account_surface": True,
            "identity_surface": "finder_nickname",
            "role": "",
            "left": 235,
            "top": 88,
            "width": 212,
            "height": 21,
            "viewport_width": 800,
            "viewport_height": 600,
            "device_pixel_ratio": 1,
        }],
    )

    evidence = _account_identity_evidence(frame, "成核生长")

    assert len(evidence) == 1
    assert evidence[0]["tag"] == "h2"
    assert evidence[0]["identity_surface"] == "finder_nickname"
    assert evidence[0]["region"] == "semantic_account_surface"
    assert evidence[0]["viewport_width"] == 800
    assert evidence[0]["viewport_height"] == 600
    assert "__CHANNELS_ACCOUNT_IDENTITY_SCAN__" in frame.last_evaluate_expression
    assert 'element.classList.contains("finder-nickname")' in frame.last_evaluate_expression


def test_account_identity_rejects_matching_name_outside_account_region() -> None:
    frame = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        identity_matches=[{
            "tag": "p",
            "evidence_type": "visible_text",
            "matched_value": "成核生长",
            "region": "other",
            "semantic_account_surface": False,
        }],
    )
    assert _account_identity_evidence(frame, "成核生长") == []


def test_account_identity_failure_preserves_sanitized_frame_diagnostics(monkeypatch) -> None:
    import wechat_video.channels_uploader as uploader

    frame = _FakeFrame("https://channels.weixin.qq.com/platform")
    page = _FakePage([frame])
    expected = {
        "stage": "account_identity",
        "expected_account_name": "成核生长",
        "login_prompt_detected": False,
        "frames": [{
            "frame_url": frame.url,
            "ready_state": "complete",
            "body_contains_expected_name": True,
            "visible_matching_node_count": 1,
            "visible_matching_nodes": [{
                "tag": "span",
                "evidence_type": "visible_text",
                "matched_value": "成核生长",
                "lower_left": False,
                "semantic_account_surface": False,
            }],
        }],
    }
    monkeypatch.setattr(uploader, "_wait_for_account_identity", lambda *_a, **_k: False)
    monkeypatch.setattr(uploader, "_login_required_hint", lambda _page: False)
    monkeypatch.setattr(uploader, "_account_identity_diagnostics", lambda _page, _name: expected)

    with pytest.raises(UploadBlockedError, match="per-frame identity diagnostics") as caught:
        uploader._ensure_account_identity(
            page, "成核生长", {"account_identity": {"exact_text": "成核生长"}},
            wait_seconds=0,
        )

    assert caught.value.diagnostics == expected
    assert caught.value.diagnostics["frames"][0]["body_contains_expected_name"] is True
    assert "page_body_text" not in caught.value.diagnostics
    assert "input_values" not in caught.value.diagnostics


def test_account_identity_diagnostics_records_frame_state_without_page_text(monkeypatch) -> None:
    import wechat_video.channels_uploader as uploader

    class DiagnosticFrame:
        url = "https://channels.weixin.qq.com/platform"

        def evaluate(self, expression, *args):
            if "document.readyState" in expression:
                return "complete"
            if "__CHANNELS_ACCOUNT_IDENTITY_DIAGNOSTICS__" in expression:
                assert args == ("成核生长",)
                return {
                    "body_contains_expected_name": True,
                    "visible_matching_node_count": 1,
                    "visible_matching_nodes": [{
                        "tag": "span",
                        "evidence_type": "visible_text",
                        "matched_value": "成核生长",
                        "lower_left": False,
                        "semantic_account_surface": False,
                        "rect": {"x": 880, "y": 30, "width": 90, "height": 20},
                    }],
                }
            raise AssertionError("Unexpected diagnostic DOM evaluation")

    class DiagnosticPage:
        url = "https://channels.weixin.qq.com/platform"

        def __init__(self):
            self.frames = [DiagnosticFrame()]
            self.main_frame = self.frames[0]

        def title(self):
            return "视频号助手"

    monkeypatch.setattr(
        uploader, "_account_identity_evidence",
        lambda _frame, _name: [],
    )
    monkeypatch.setattr(uploader, "_login_required_hint", lambda _page: False)

    diagnostic = uploader._account_identity_diagnostics(
        DiagnosticPage(), "成核生长"
    )

    assert diagnostic["stage"] == "account_identity"
    assert diagnostic["page_title"] == "视频号助手"
    assert diagnostic["frames"][0]["ready_state"] == "complete"
    assert diagnostic["frames"][0]["body_contains_expected_name"] is True
    assert diagnostic["frames"][0]["visible_matching_node_count"] == 1
    assert diagnostic["frames"][0]["visible_matching_nodes"][0]["rect"]["x"] == 880
    assert "page_body_text" not in diagnostic["frames"][0]


def test_login_required_hint_requires_explicit_login_prompt() -> None:
    class BodyFrame:
        url = "https://channels.weixin.qq.com/platform/post/create"

        def __init__(self, text):
            self.text = text

        def evaluate(self, expression, *args):
            assert "document.body" in expression
            return self.text

        def locator(self, selector):
            raise AssertionError(
                "Body text must be read through same-frame DOM evaluation, not a Locator."
            )

    class BodyPage:
        def __init__(self, body_text):
            self.frames = [BodyFrame(body_text)]
            self.main_frame = self.frames[0]

    assert _login_required_hint(BodyPage("登录后可查看账号信息")) is False
    assert _login_required_hint(BodyPage("请登录后继续")) is True


def test_live_description_selector_matches_empty_contenteditable_and_spa_wait_is_15_seconds() -> None:
    import yaml

    root = Path(__file__).resolve().parents[1]
    selectors = yaml.safe_load((root / "config" / "selectors.yaml").read_text(encoding="utf-8"))
    config = json.loads(
        (root / "config" / "channels_upload.json").read_text(encoding="utf-8")
    )
    description_selectors = selectors["description_input"]
    assert any("[contenteditable]" in item for item in description_selectors)
    assert not any("[contenteditable='true']" in item for item in description_selectors)
    assert config["ui_ready_timeout_seconds"] == 15
    assert config["draft_list_url"] == (
        "https://channels.weixin.qq.com/platform/post/draftListManager"
    )
    assert config["platform_url"] == "https://channels.weixin.qq.com/platform"
    assert selectors["draft_list_path"] == "/platform/post/draftListManager"
    assert selectors["draft_list_frame_path"] == (
        "/micro/content/post/draftListManager"
    )
    assert selectors["draft_list_nav_parent_selectors"] == [
        ".finder-ui-desktop-menu__sub__wrp"
    ]
    assert selectors["draft_list_nav_entry_selectors"] == [
        ".finder-ui-desktop-sub-menu__item"
    ]
    assert selectors["draft_list_nav_entry_text"] == "草稿箱"
    assert selectors["draft_list_root_selector"] == (
        "div.finder-page.DraftListManager"
    )
    assert selectors["draft_list_body_selector"].endswith(
        "div.post-list-body"
    )
    assert selectors["draft_list_rows_timeout_seconds"] == 15
    assert "draft_row_selectors" not in selectors



def test_inspector_reports_button_label_source_for_aria_only_label() -> None:
    from wechat_video.channels_uploader import _inspect_frame_controls

    frame = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/iframe/post-card.html",
        inspection={
            "ready_state": "complete",
            "counts": {
                "buttons_total": 1,
                "buttons_visible": 1,
                "textboxes_total": 0,
                "textboxes_visible": 0,
                "file_inputs_total": 0,
                "file_inputs_visible": 0,
            },
            "buttons": [{
                "tag": "button",
                "text": "",
                "aria_label": "发表视频",
            }],
            "textboxes": [],
            "file_inputs": [],
        },
    )

    inventory = _inspect_frame_controls(frame, frame.url)

    assert inventory["visible_buttons"] == [{
        "tag": "button",
        "text": "发表视频",
        "aria_label": "发表视频",
        "label_source": "aria_label",
        "frame_url": frame.url,
    }]


def test_read_only_inspector_collects_controls_from_direct_frame_dom_inventory() -> None:
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        inspection={
            "ready_state": "complete",
            "counts": {
                "buttons_total": 4,
                "buttons_visible": 4,
                "textboxes_total": 2,
                "textboxes_visible": 2,
                "file_inputs_total": 1,
                "file_inputs_visible": 1,
            },
            "buttons": [
                {"text": "保存草稿", "aria_label": None},
                {"text": "手机预览", "aria_label": None},
            ],
            "textboxes": [
                {
                    "tag": "input",
                    "placeholder": "填写短标题有机会获得更多流量",
                    "data_placeholder": None,
                    "aria_label": None,
                    "contenteditable": None,
                    "role": None,
                },
                {
                    "tag": "div",
                    "placeholder": None,
                    "data_placeholder": "添加描述",
                    "aria_label": None,
                    "contenteditable": "",
                    "role": None,
                },
            ],
            "file_inputs": [
                {
                    "accept": "video/mp4,video/x-m4v,video/*",
                    "multiple": "multiple",
                    "visible": True,
                }
            ],
        },
    )
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        inspection={
            "ready_state": "complete",
            "counts": {
                "buttons_total": 0,
                "buttons_visible": 0,
                "textboxes_total": 0,
                "textboxes_visible": 0,
                "file_inputs_total": 0,
                "file_inputs_visible": 0,
            },
            "buttons": [],
            "textboxes": [],
            "file_inputs": [],
        },
    )
    page = _FakePage([main, child])

    frames, buttons, textboxes, files, controls_ready = _collect_ui_inventory(
        page, timeout_seconds=0
    )

    assert controls_ready is True
    assert len(frames) == 2
    assert frames[0]["control_counts"]["buttons_visible"] == 4
    assert any(item["text"] == "保存草稿" for item in buttons)
    assert any(item.get("data_placeholder") == "添加描述" for item in textboxes)
    editor = next(item for item in textboxes if item.get("data_placeholder") == "添加描述")
    assert editor["contenteditable"] == ""
    assert files[0]["accept"] == "video/mp4,video/x-m4v,video/*"
    assert files[0]["frame_url"] == "https://channels.weixin.qq.com/platform/post/create"
    assert "querySelectorAll" in main.last_evaluate_expression
    assert "input.value" not in main.last_evaluate_expression



def test_inspector_readiness_aggregates_controls_across_frames() -> None:
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        inspection={
            "ready_state": "complete",
            "counts": {
                "buttons_total": 3,
                "buttons_visible": 3,
                "textboxes_total": 1,
                "textboxes_visible": 1,
                "file_inputs_total": 0,
                "file_inputs_visible": 0,
            },
            "buttons": [{"text": "保存草稿", "aria_label": None}],
            "textboxes": [{
                "tag": "input",
                "placeholder": "填写短标题有机会获得更多流量",
                "data_placeholder": None,
                "aria_label": None,
                "contenteditable": None,
                "role": None,
            }],
            "file_inputs": [],
        },
    )
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        inspection={
            "ready_state": "complete",
            "counts": {
                "buttons_total": 0,
                "buttons_visible": 0,
                "textboxes_total": 1,
                "textboxes_visible": 1,
                "file_inputs_total": 1,
                "file_inputs_visible": 1,
            },
            "buttons": [],
            "textboxes": [{
                "tag": "div",
                "placeholder": None,
                "data_placeholder": "添加描述",
                "aria_label": None,
                "contenteditable": "",
                "role": None,
            }],
            "file_inputs": [{
                "accept": "video/mp4,video/*",
                "multiple": "multiple",
                "visible": True,
            }],
        },
    )

    frames, buttons, textboxes, files, controls_ready = _collect_ui_inventory(
        _FakePage([main, child]), timeout_seconds=0
    )

    assert controls_ready is True
    assert len(frames) == 2
    assert buttons[0]["text"] == "保存草稿"
    assert any(item.get("data_placeholder") == "添加描述" for item in textboxes)
    assert files[0]["accept"] == "video/mp4,video/*"


def test_creator_entry_dom_scan_comment_cannot_terminate_javascript_comment_early() -> None:
    import wechat_video.channels_uploader as uploader

    expression = uploader._DOM_VISIBLE_ELEMENT_SCAN
    # A literal "*/" inside explanatory comment text terminates the JS block
    # comment and makes Frame.evaluate fail before the DOM scan can run.
    assert "data-*/" not in expression
    assert "aria-*/" not in expression
    assert "Class, id, data, aria, href and ancestor attributes" in expression
