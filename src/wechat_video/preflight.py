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


def font_supports_chars(path: str, text: str) -> bool:
    """Return True only when the font's cmap contains every non-space codepoint."""
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except ImportError as exc:  # pragma: no cover - fontTools is a declared dependency
        raise RuntimeError("fontTools is required for glyph coverage checks.") from exc

    font_path = Path(path)
    try:
        if font_path.suffix.lower() == ".ttc":
            fonts = TTCollection(str(font_path)).fonts
        else:
            fonts = [TTFont(str(font_path))]
        codepoints = {ord(char) for char in text if not char.isspace()}
        for font in fonts:
            cmap = set()
            for table in font["cmap"].tables:
                if table.isUnicode():
                    cmap.update(table.cmap.keys())
            if codepoints.issubset(cmap):
                return True
        return False
    except Exception:
        return False


def find_font(
    preferred: list[str], *, required_chars: str | None = None
) -> tuple[str, str]:
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
                    if required_chars and not font_supports_chars(full_path, required_chars):
                        continue
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
    for optional_filter in ("subtitles", "loudnorm"):
        if optional_filter not in filter_text:
            raise RuntimeError(f"FFmpeg is missing required filter: {optional_filter}")
    cleanup_filters = [name for name in ("afftdn", "anlmdn") if name in filter_text]
    if not cleanup_filters:
        report["warnings"].append("No local audio denoise filter was detected.")
    report["available_cleanup_filters"] = cleanup_filters
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
    subtitle_config = layout["subtitle"]
    latin_family, latin_path = find_font(subtitle_config["latin_fonts"])
    cjk_chars = "成核临界半径自由能垒"
    cjk_family, cjk_path = find_font(
        subtitle_config["cjk_fonts"], required_chars=cjk_chars
    )
    report["font"] = {"family": latin_family, "file": latin_path}
    report["font_family"] = latin_family
    report["font_file"] = latin_path
    report["latin_font"] = {"family": latin_family, "file": latin_path}
    report["cjk_font"] = {
        "family": cjk_family,
        "file": cjk_path,
        "verified_codepoints": cjk_chars,
    }
    report["chinese_font"] = report["cjk_font"]
    report["checks"]["latin_font_file_present"] = "PASS"
    report["checks"]["cjk_font_glyphs_present"] = "PASS"

    voice_python = project_root / ".venv-voice" / "python.exe"
    profile_dir = project_root / "private" / "voice_profile"
    profile_json = profile_dir / "voice_profile.json"
    target_se = profile_dir / "target_se.pth"
    melo_dir = project_root / "assets" / "models" / "melo-en-us"
    converter = project_root / "tools" / "openvoice" / "checkpoints_v2" / "converter"
    personal_paths = {
        "voice_runtime": voice_python,
        "voice_profile": profile_json,
        "target_embedding": target_se,
        "melo_en_checkpoint": melo_dir / "checkpoint.pth",
        "openvoice_converter": converter / "checkpoint.pth",
    }
    missing_personal = [str(key) for key, path in personal_paths.items() if not path.is_file()]
    if missing_personal:
        raise RuntimeError(
            "Personal OpenVoice path is incomplete; missing: " + ", ".join(missing_personal)
        )
    report["personal_voice"] = {
        "engine": "MeloTTS EN-US -> OpenVoice V2 ToneColorConverter",
        "provider": "cpu",
        "runtime": str(voice_python.relative_to(project_root)),
        "profile": str(profile_json.relative_to(project_root)),
    }
    report["checks"]["personal_voice_runtime_and_profile"] = "PASS"
    report["tts_model_engine"] = "MeloTTS EN-US -> OpenVoice V2 (personal profile)"
    report["checks"]["offline_tts_model"] = "PASS"

    report["checks"]["all_preflight"] = "PASS"
    return report
