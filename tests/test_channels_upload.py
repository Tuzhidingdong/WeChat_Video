from __future__ import annotations

import json
from pathlib import Path

import pytest

from wechat_video.channels_metadata import build_channels_metadata, validate_channels_metadata
from wechat_video.channels_uploader import (
    UploadBlockedError,
    _approval_record,
    _matching_draft_entries,
    _validate_run_for_upload,
    _visible_locator,
    _fill_field,
    _draft_save_button,
    _video_file_input,
    _wait_for_account_identity,
    _account_identity_evidence,
    _login_required_hint,
    _collect_ui_inventory,
    approve_run,
)
from wechat_video.topic_approval import (
    TopicApprovalError,
    approve_fact_card,
    verify_fact_card_approval,
)




class _FakeElement:
    def __init__(self, *, text="", attrs=None, tag="div", visible=True, enabled=True):
        self.text = text
        self.attrs = dict(attrs or {})
        self.tag = tag
        self.visible = visible
        self.enabled = enabled
        self.clicked = False

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

    def click(self, timeout=None):
        self.clicked = True

    def evaluate(self, expression):
        if "tagName.toLowerCase()" in expression:
            return self.tag
        if "matches('a,button,[role=button]')" in expression:
            return False
        raise NotImplementedError(expression)


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
    ):
        self.url = url
        self.selectors = dict(selectors or {})
        self.roles = dict(roles or {})
        self.texts = dict(texts or {})
        self.inspection = dict(inspection or {})
        self.identity_matches = list(identity_matches or [])
        self.last_evaluate_expression = ""

    def locator(self, selector):
        return _FakeLocator(self.selectors.get(selector, []))

    def evaluate(self, expression, *args):
        self.last_evaluate_expression = expression
        if "__CHANNELS_ACCOUNT_IDENTITY_SCAN__" in expression:
            return self.identity_matches
        return self.inspection

    def get_by_role(self, role, name=None, exact=None):
        return _FakeLocator(self.roles.get((role, name, exact), []))

    def get_by_text(self, text, exact=None):
        return _FakeLocator(self.texts.get((text, exact), []))


class _FakePage:
    def __init__(self, frames):
        self.frames = list(frames)
        self.main_frame = self.frames[0]
        self.url = "https://channels.weixin.qq.com/platform/post/create"

    def wait_for_timeout(self, milliseconds):
        return None


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


def test_upload_validation_accepts_one_time_topic_approval_without_daily_video_approval(
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

    config = json.loads((tmp_path / "config" / "channels_upload.json").read_text(encoding="utf-8"))
    metadata, qa, approval = _validate_run_for_upload(tmp_path, run_dir, config)
    assert metadata["title"] == "临界半径如何决定成核"
    assert qa["overall_status"] == "PASS"
    assert approval["approval_type"] == "local_hash_bound"
    assert not (tmp_path / "runtime" / "approvals" / f"{run_dir.name}.json").exists()


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
    with pytest.raises(UploadBlockedError, match="differs from the exact approved Fact Card"):
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
    assert approval["approval_type"] == "local_hash_bound"
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
    )
    page = _FakePage([main, child])

    locator = _visible_locator(
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
    )
    page = _FakePage([main, child])

    assert _draft_save_button(
        page, {"draft_save_button_text": ["保存草稿"]}
    ) is save


def test_video_file_input_is_found_in_main_frame_when_form_fields_are_in_iframe() -> None:
    upload = _FakeElement(
        attrs={"accept": "video/mp4,video/x-m4v,video/*", "multiple": "multiple"},
        tag="input",
    )
    main = _FakeFrame(
        "https://channels.weixin.qq.com/platform/post/create",
        selectors={"input[type='file'][accept*='video']": [upload]},
    )
    child = _FakeFrame("https://channels.weixin.qq.com/micro/content/post/create")
    page = _FakePage([main, child])

    assert _video_file_input(
        page,
        {"video_file_input": ["input[type='file'][accept*='video']"]},
    ) is upload


def test_account_identity_waits_and_checks_child_frames() -> None:
    identity = _FakeElement(text="成核生长")
    main = _FakeFrame("https://channels.weixin.qq.com/platform/post/create")
    child = _FakeFrame(
        "https://channels.weixin.qq.com/micro/content/post/create",
        texts={("成核生长", True): [identity]},
    )
    page = _FakePage([main, child])

    assert _wait_for_account_identity(
        page,
        "成核生长",
        {"account_identity": {"exact_text": "成核生长"}},
        wait_seconds=0,
    ) is True


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


def test_login_required_hint_requires_explicit_login_prompt() -> None:
    class BodyFrame:
        url = "https://channels.weixin.qq.com/platform/post/create"

        def __init__(self, text):
            self.text = text

        def locator(self, selector):
            assert selector == "body"
            return _FakeElement(text=self.text)

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
