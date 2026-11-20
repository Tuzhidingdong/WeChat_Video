from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model_setup import download_model
from .pipeline import run_slice_a
from .preflight import run_preflight


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    root = _project_root()
    parser = argparse.ArgumentParser(
        prog="wechat-video",
        description="WeChat science animation — Milestone 1 Slice A local proof",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="Check the local rendering and TTS environment.")
    preflight.add_argument("--project-root", type=Path, default=root)
    preflight.add_argument("--allow-missing-model", action="store_true")

    model = sub.add_parser("download-model", help="Download the official sherpa-onnx MeloTTS zh_en model.")
    model.add_argument("--project-root", type=Path, default=root)

    run = sub.add_parser("run-slice-a", help="Create one local critical-nucleus sample MP4.")
    run.add_argument("--project-root", type=Path, default=root)
    run.add_argument(
        "--fact-card",
        type=Path,
        default=root / "fact_cards" / "critical_nucleus_free_energy_candidate.json",
    )
    run.add_argument(
        "--script",
        type=Path,
        default=root / "content" / "sample_script.json",
    )
    run.add_argument("--output-root", type=Path, default=Path("outputs"))
    run.add_argument(
        "--review-sample",
        action="store_true",
        help="Allow a pending Fact Card for a local review sample; output remains not-for-publication.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = run_preflight(
                args.project_root.resolve(),
                require_tts_model=not args.allow_missing_model,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "download-model":
            model_path = download_model(args.project_root.resolve())
            print(f"Local offline TTS model ready: {model_path}")
            return 0
        if args.command == "run-slice-a":
            run_dir = run_slice_a(
                args.project_root,
                card_path=args.fact_card,
                script_path=args.script,
                output_root=args.output_root,
                allow_pending_review=args.review_sample,
            )
            print(f"\nSlice A review package: {run_dir}")
            print(f"Video: {run_dir / 'final.mp4'}")
            print(f"Report: {run_dir / 'qa_report.json'}")
            return 0
        return 2
    except Exception as exc:
        print(f"\nSLICE A FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
