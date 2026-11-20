from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .process import run_checked
from .tooling import tool_env


def render_critical_nucleus_scene(
    project_root: Path,
    run_dir: Path,
    scene_spec: dict[str, Any],
    *,
    timeout_seconds: int = 1800,
) -> Path:
    import json

    scene_spec_path = run_dir / "scene_spec.json"
    scene_spec_path.write_text(
        json.dumps(scene_spec, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    media_dir = run_dir / "manim_media"
    media_dir.mkdir(parents=True, exist_ok=True)
    driver = run_dir / "manim_driver.py"
    driver.write_text(
        """
import os
from pathlib import Path
from manim import tempconfig
from wechat_video.scenes.critical_nucleus import CriticalNucleusScene

media_dir = Path(os.environ["WECHAT_VIDEO_MANIM_MEDIA_DIR"])
config = {
    "pixel_width": 1080,
    "pixel_height": 1920,
    "frame_height": 16,
    "frame_width": 9,
    "frame_rate": 30,
    "renderer": "cairo",
    "format": "mp4",
    "media_dir": str(media_dir),
    "background_color": "#081321",
    "write_to_movie": True,
    "disable_caching": True,
    "verbosity": "WARNING",
    "progress_bar": "none",
}
with tempconfig(config):
    scene = CriticalNucleusScene()
    scene.render()

candidates = [
    p for p in media_dir.rglob("CriticalNucleusScene.mp4")
    if "partial_movie_files" not in p.parts
]
if len(candidates) != 1:
    raise RuntimeError(
        "Expected exactly one CriticalNucleusScene.mp4; found: "
        + ", ".join(str(p) for p in candidates)
    )
print("MANIM_OUTPUT=" + str(candidates[0]))
""".lstrip(),
        encoding="utf-8",
    )

    env = tool_env(project_root)
    env["WECHAT_VIDEO_SCENE_SPEC"] = str(scene_spec_path.resolve())
    env["WECHAT_VIDEO_MANIM_MEDIA_DIR"] = str(media_dir.resolve())
    package_src = str((project_root / "src").resolve())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = package_src + (os.pathsep + existing if existing else "")
    result = run_checked(
        [sys.executable, "-X", "utf8", str(driver)],
        cwd=run_dir,
        timeout_seconds=timeout_seconds,
        env=env,
    )
    (run_dir / "manim_render.log").write_text(
        result.stdout + "\n--- STDERR ---\n" + result.stderr,
        encoding="utf-8",
    )
    candidates = [
        p for p in media_dir.rglob("CriticalNucleusScene.mp4")
        if "partial_movie_files" not in p.parts
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "Manim returned success but did not create one unique final scene video."
        )
    output = run_dir / "critical_nucleus_scene.mp4"
    shutil.copy2(candidates[0], output)
    return output
