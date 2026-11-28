"""Dedicated Edge/CDP controller for Google Flow.

Reuses the project's verified Edge session ownership logic via a config
override; the existing WeChat Channels profile is never touched.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import channels_uploader as cu

BLOCKED_BROWSER_PROFILE = "BLOCKED_BROWSER_PROFILE"
CONFIG_PATH = "config/micro_visual.json"


class MicroVisualBrowserError(RuntimeError):
    def __init__(self, state: str, message: str):
        super().__init__(message)
        self.state = state


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MicroVisualBrowserError(BLOCKED_BROWSER_PROFILE, f"missing {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MicroVisualBrowserError(
            BLOCKED_BROWSER_PROFILE, f"cannot read {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise MicroVisualBrowserError(BLOCKED_BROWSER_PROFILE, "config must be an object")
    return value


def load_flow_config(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    config = _read_config_file(root / CONFIG_PATH)
    if config.get("schema_version") != 1:
        raise MicroVisualBrowserError(BLOCKED_BROWSER_PROFILE, "unsupported config schema_version")
    for key in (
        "edge_profile_dir", "session_file", "download_root", "flow_url",
        "model", "duration_seconds", "aspect_ratio",
    ):
        if not str(config.get(key) or "").strip():
            raise MicroVisualBrowserError(BLOCKED_BROWSER_PROFILE, f"missing config key: {key}")

    flow_profile = cu._relative_config_path(root, str(config["edge_profile_dir"])).resolve()
    session_file = cu._relative_config_path(root, str(config["session_file"])).resolve()
    download_root = cu._relative_config_path(root, str(config["download_root"])).resolve()
    for label, path in (
        ("edge_profile_dir", flow_profile),
        ("session_file", session_file),
        ("download_root", download_root),
    ):
        if not path.is_relative_to(root):
            raise MicroVisualBrowserError(
                BLOCKED_BROWSER_PROFILE, f"{label} must stay inside the project root"
            )

    upload_config, _ = cu._load_config(root)
    upload_profile = cu._relative_config_path(
        root, str(upload_config["edge_profile_dir"])
    ).resolve()
    if flow_profile == upload_profile:
        raise MicroVisualBrowserError(
            BLOCKED_BROWSER_PROFILE,
            "Flow profile must be isolated from the Channels uploader profile",
        )

    input_root_value = str(config.get("article_summary_input_root") or "").strip()
    input_root = None
    if input_root_value:
        input_root = cu._relative_config_path(root, input_root_value).resolve()
        if not input_root.is_dir():
            raise MicroVisualBrowserError(
                "BLOCKED_BROWSER_PROFILE", f"article summary input root is not a directory: {input_root}"
            )

    uploader_profile_value = str(config.get("uploader_edge_profile_dir") or "").strip()
    uploader_session_value = str(config.get("uploader_session_file") or "").strip()
    uploader_override = None
    if uploader_profile_value and uploader_session_value:
        uploader_override = {
            "edge_profile_dir": uploader_profile_value,
            "session_file": uploader_session_value,
        }

    return {
        **config,
        "_flow_profile": flow_profile,
        "_flow_session_file": session_file,
        "_download_root": download_root,
        "_article_summary_input_root": input_root,
        "_uploader_config_override": uploader_override,
        "_upload_config": upload_config,
    }


def flow_edge_config(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Build an ensure_edge_session config isolated to the Flow profile."""
    base = dict(config["_upload_config"])
    base["edge_profile_dir"] = str(config["edge_profile_dir"])
    base["session_file"] = str(config["session_file"])
    base["create_url"] = str(config["flow_url"])
    base["headless"] = bool(config.get("headless", False))
    return base


def ensure_flow_session(
    project_root: Path, config: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Reuse the verified Edge ownership logic on the dedicated Flow profile."""
    try:
        return cu.ensure_edge_session(
            project_root.resolve(),
            open_url=str(config["flow_url"]),
            headless=bool(config.get("headless", False)),
            config_override=flow_edge_config(project_root, config),
        )
    except cu.UploadBlockedError as exc:
        raise MicroVisualBrowserError(BLOCKED_BROWSER_PROFILE, str(exc)) from exc


def submit_flow_generation(page: Any, config: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Submit exactly one Flow generation request through configured selectors."""
    selectors = config.get("selectors") or {}
    prompt_selector = str(selectors.get("prompt_input") or "")
    generate_selector = str(selectors.get("generate_button") or "")
    if not prompt_selector or not generate_selector:
        raise MicroVisualBrowserError(
            "FAILED", "Flow prompt/generate selectors are not configured"
        )
    page.fill(prompt_selector, prompt)
    page.click(generate_selector)
    return {
        "model": config["model"],
        "duration_seconds": config["duration_seconds"],
        "aspect_ratio": config["aspect_ratio"],
        "submitted_once": True,
    }


class FlowBrowserController:
    """Owns one Playwright/CDP session; never starts video rendering."""

    def __init__(self, websocket_url: str, config: dict[str, Any]):
        self.websocket_url = websocket_url
        self.config = config
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> "FlowBrowserController":
        self._playwright, self._browser, self._context = cu._connect_playwright(
            self.websocket_url
        )
        selector = str((self.config.get("selectors") or {}).get("flow_ready") or "")
        # Reuse an already-open project editor when present. Navigating to the
        # Flow home page opens a landing page without a prompt textbox.
        if selector:
            for page in self._context.pages:
                locator = page.locator(selector)
                if locator.count() and locator.first.is_visible():
                    backdrop = page.locator(".cdk-overlay-backdrop")
                    if backdrop.count():
                        backdrop.last.click(timeout=8000)
                        page.wait_for_timeout(300)
                    self.page = page
                    return self
        # The Flow landing page has no prompt textbox; an existing project editor
        # does. Navigate to the first project page rather than failing on home.
        if selector:
            for page in self._context.pages:
                try:
                    href = page.evaluate(
                        "() => {const a=[...document.querySelectorAll('a')].find("
                        "a=>(a.getAttribute('href')||'').startsWith('/project/')); "
                        "return a?a.getAttribute('href'):null}"
                    )
                except Exception:  # noqa: BLE001 - limited/fake page objects
                    continue
                if href:
                    try:
                        page.goto(
                            str(self.config["flow_url"]).rstrip("/") + href,
                            wait_until="domcontentloaded", timeout=60_000,
                        )
                        page.wait_for_timeout(2_000)
                    except Exception:  # noqa: BLE001 - fall through to home page
                        continue
                    if page.locator(selector).count():
                        self.page = page
                        return self
        self.page = self._context.new_page()
        self.page.goto(
            str(self.config["flow_url"]), wait_until="domcontentloaded", timeout=60_000
        )
        if selector:
            self.page.wait_for_selector(
                selector, timeout=int(self.config.get("ui_ready_timeout_seconds", 30)) * 1000
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._context = self.page = None
