"""Single-line, BAT-safe business-status readback for the third BAT.

Prints one line (no embedded quotes/newlines) so CMD can read it with SET /P.
Never treats BAT exit code 0 or success=false alone as success/failure.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .micro_visual_status import INVALID_STATE_MESSAGE, read_state_message


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(INVALID_STATE_MESSAGE.replace("\n", " "))
        return 2
    path = Path(args[0])
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        print(INVALID_STATE_MESSAGE.replace("\n", " "))
        return 2
    if not isinstance(data, dict) or not str(data.get("run_id") or "").strip() \
            or not str(data.get("state") or "").strip():
        print(INVALID_STATE_MESSAGE.replace("\n", " "))
        return 2
    expected = os.environ.get("MICRO_VISUAL_EXPECTED_RUN_ID", "").strip()
    if expected and str(data.get("run_id")) != expected:
        print("[STOP] run_id 与本次运行不一致；不要将 exit code 视为成功。")
        return 2
    message = " ".join(read_state_message(path).split())
    state = str(data.get("state"))
    run_id = str(data.get("run_id"))
    exit_code = data.get("exit_code")
    print(f"[{state}] run_id={run_id} exit_code={exit_code} {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
