from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .process import ExternalProcessError, run_checked
from .tooling import resolve_command, tool_env


FONT_FILE_HINTS = {
    "Arial": ("arial.ttf", "arialbd.ttf"),
    "Segoe UI": ("segoeui.ttf", "seguisb.ttf"),
    "Aptos": ("aptos.ttf", "aptosb.ttf"),
    "Microsoft YaHei": ("msyh.ttc", "msyh.ttf", "msyhbd.ttc"),
    "SimHei": ("simhei.ttf",),
    "Noto Sans CJK SC": ("NotoSansCJK", "NotoSansSC"),
    "Source Han Sans SC": ("SourceHanSansSC", "SourceHanSansCN"),
}


def _font_dirs() -> list[Path]:
    dirs: list[Path] = []
    windir = os.environ.get("WINDIR")
    local = os.environ.get("LOCALAPPDATA")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    if platform.system() != "Windows":
        dirs.extend(
            [
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                Path.home() / ".fonts",
                Path.home() / ".local" / "share" / "fonts",
            ]
        )
    return [p for p in dirs if p.exists()]


def find_font(preferred: list[str]) -> tuple[str, str]:
    directories = _font_dirs()
    font_files = [
        path
        for root in directories
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".ttf", ".ttc", ".otf"}
    ]
    lowered = [(p.name.lower(), str(p)) for p in font_files]

    for family in preferred:
        hints = FONT_FILE_HINTS.get(family, (family.replace(" ", "").lower(),))
        for hint in hints:
            hint = hint.lower()
            for name, full_path in lowered:
                if hint in name:
                    return family, full_path

    if platform.system() != "Windows" and shutil.which("fc-match"):
        for family in preferred:
            probe = subprocess.run(
                ["fc-match", "-f", "%{file}", family],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                shell=False,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                return family, probe.stdout.strip()
    raise RuntimeError(
        "No preferred font was found. Check the layout profile's preferred_fonts list."
    )


find_chinese_font = find_font  # backwards-compatible alias for legacy callers


def _latex_smoke_test(latex: str, dvisvgm: str, root: Path) -> dict[str, Any]:
    tex_source = (
        r"\documentclass[preview]{standalone}" "\n"
        r"\usepackage{amsmath}" "\n"
        r"\begin{document}" "\n"
        r"$\Delta G^*=\frac{16\pi\gamma^3}{3\Delta g_v^2}$" "\n"
        r"\end{document}" "\n"
    )
    with tempfile.TemporaryDirectory(prefix="wechat_video_latex_") as folder:
        work = Path(folder)
        (work / "smoke.tex").write_text(tex_source, encoding="utf-8")
        tex = run_checked(
            [latex, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "smoke.tex"],
            cwd=work,
            timeout_seconds=90,
            env=tool_env(root),
        )
        dvi = work / "smoke.dvi"
        if not dvi.exists():
            raise RuntimeError("LaTeX 命令退出成功，但没有生成 smoke.dvi。")
        svg = run_checked(
            [dvisvgm, "--no-fonts", "--output=smoke.svg", "smoke.dvi"],
            cwd=work,
            timeout_seconds=90,
            env=tool_env(root),
        )
        if not (work / "smoke.svg").exists():
            raise RuntimeError("dvisvgm 命令退出成功，但没有生成 smoke.svg。")
        return {
            "latex_smoke_test": "PASS",
            "dvisvgm_smoke_test": "PASS",
            "latex_output_tail": tex.stdout[-800:],
            "dvisvgm_output_tail": svg.stdout[-400:],
        }


def run_preflight(
    project_root: Path,
    *,
    require_tts_model: bool = True,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "venv_active": sys.prefix != sys.base_prefix,
        "checks": {},
        "warnings": [],
    }
    if not report["venv_active"]:
        raise RuntimeError(
            "当前 Python 不在项目专用 .venv 中。请先运行 Setup_Slice_A.bat；"
            "不要使用或修改全局 Python。"
        )
    if not ((3, 11) <= sys.version_info[:2] < (3, 13)):
        raise RuntimeError("Slice A 需要 Python 3.11、3.12 或 3.13。")

    try:
        import manim
        import sherpa_onnx
        import soundfile  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(f"Python 依赖未安装完整：{exc}") from exc

    report["checks"]["python_environment"] = "PASS"
    report["manim_version"] = getattr(manim, "__version__", "unknown")
    try:
        report["sherpa_onnx_version"] = importlib.metadata.version("sherpa-onnx")
    except importlib.metadata.PackageNotFoundError:
        report["sherpa_onnx_version"] = "unknown"

    required_tools = {}
    for command in ("ffmpeg", "ffprobe", "latex", "dvisvgm"):
        try:
            required_tools[command] = resolve_command(command, project_root)
        except RuntimeError as exc:
            raise RuntimeError(
                f"未找到 {command}。请检查项目内工具与 config/tools.local.json。"
            ) from exc
    report["tools"] = required_tools

    ffmpeg_environment = tool_env(project_root)
    ffmpeg_version = run_checked(
        [required_tools["ffmpeg"], "-version"],
        timeout_seconds=20,
        env=ffmpeg_environment,
    ).stdout.splitlines()[0]
    ffprobe_version = run_checked(
        [required_tools["ffprobe"], "-version"],
        timeout_seconds=20,
        env=ffmpeg_environment,
    ).stdout.splitlines()[0]
    filter_result = run_checked(
        [required_tools["ffmpeg"], "-hide_banner", "-filters"],
        timeout_seconds=30,
        env=ffmpeg_environment,
    )
    filter_text = filter_result.stdout + "\n" + filter_result.stderr
    if "subtitles" not in filter_text or "loudnorm" not in filter_text:
        raise RuntimeError(
            "当前 FFmpeg 缺少 subtitles/libass 或 loudnorm filter；请更换包含 libass 的构建。"
        )
    report["ffmpeg_version"] = ffmpeg_version
    report["ffprobe_version"] = ffprobe_version
    report["checks"]["ffmpeg_ffprobe_libass_loudnorm"] = "PASS"

    latex_report = _latex_smoke_test(
        required_tools["latex"], required_tools["dvisvgm"], project_root
    )
    report.update(latex_report)
    report["checks"]["latex_noninteractive_smoke"] = "PASS"

    layout = json.loads(
        (project_root / "configs" / "layout.json").read_text(encoding="utf-8")
    )
    preferred = layout["subtitle"]["preferred_fonts"]
    family, font_path = find_font(preferred)
    report["font"] = {"family": family, "file": font_path}
    report["font_family"] = family
    report["font_file"] = font_path
    report["chinese_font"] = {"family": family, "file": font_path}
    report["checks"]["font_file_present"] = "PASS"
    report["checks"]["chinese_font_file_present"] = "PASS"

    from .model_setup import _model_dir_valid
    from .tooling import model_root as configured_model_root

    model_dir = configured_model_root(project_root)
    ready = _model_dir_valid(model_dir)
    if require_tts_model and not ready:
        raise RuntimeError(
            f"Offline TTS model is incomplete at {model_dir}. "
            "Run Setup_Slice_A.bat once to download the English Piper voice."
        )
    report["tts_model_root"] = str(model_dir)
    report["tts_model_engine"] = "sherpa-onnx Piper VITS (en-US)"
    report["checks"]["offline_tts_model"] = "PASS" if ready else "NOT_READY"
    if not ready:
        report["warnings"].append("The English Piper offline TTS model is not ready.")

    report["checks"]["all_preflight"] = "PASS"
    return report
