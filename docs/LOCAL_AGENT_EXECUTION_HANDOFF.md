# Local Agent Execution Handoff — WeChat_Video

**Date:** 2026-11-21  
**Repository:** Tuzhidingdong/WeChat_Video  
**Working branch:** `feat/slice-a-english-visual-refinement`  
**Expected starting head:** `ca865b7039c83893316672201fe754f3597f4e8b` or a fast-forward descendant  
**PR:** #2 — keep Open and Draft  
**Authority:** `TASK_PLAN.md` V5 is frozen and remains the sole product/acceptance authority.

This handoff translates the user's current goal into the existing V5 execution order. The desired end result is one quality-approved video saved as an unpublished draft in the user's WeChat Channels account 「成核生长」, followed by the V5 daily workflow. Do not bypass the milestone gates to reach the uploader early.

## 0. Sync and protect the repository

1. Fetch the latest GitHub state and confirm the current branch head before editing.
2. Work only on `feat/slice-a-english-visual-refinement` for the remaining Slice A finalization. Do not reset, rebase destructively, force-push, or overwrite uncommitted local work.
3. Keep PR #2 Open/Draft. Do not merge it and do not update `main`.
4. Do not edit `TASK_PLAN.md` V5.
5. Do not access, copy, invoke, depend on, or modify `Tuzhidingdong/WeChat_control`, including its code, BAT files, browser profile, sessions, configuration, skills, agents, or selectors.

## 1. Finish Slice A once — use the existing V3 contract

Read and implement `docs/SLICE_A_FINAL_REFINEMENT_V3.md`. Preserve the accepted visual work. Do not redesign the sample or add unrelated polish.

The bounded V3 work is:
- confirm the source subtitle cue for volume is `r³`, while the separate area cue remains `r²`;
- correct the initial free-energy marker rise from the curve origin to the critical peak and hold it there;
- make “Direction” the dominant positive concept and show “Speed” as the secondary excluded concept, with a visible strike-through on the clock;
- show 3–4 orange particles inside the left hook ring at frame zero, contracting/fading from 0–2 s, and 3–4 cyan particles growing/moving outward on the right from 2–4 s; keep both rings visible;
- perform only the V3 same-text local audio A/B and retain the more natural result. No cloud TTS, new model, new paid service, source separation, or continuous room-tone bed.

### Bounded validation

- Run the narrow targeted regression tests once.
- Run `pytest -q` once.
- Run project preflight once.
- Generate at most one complete local review render using the Python CLI with `--review-sample`, as specified in V3. Do not run production BAT files.
- Inspect the exact V3 timestamps and the final QA report. Do not start a render/test loop. A second full render is not authorized unless the first exposes a concrete mandatory defect and the reason is reported first.
- Keep recordings, speaker embeddings, WAV/MP4, screenshots, extracted frames, model files, caches, logs containing private paths, and machine-local config out of Git.

Do not change the Fact Card approval status or represent a review sample as publishable. The current candidate Fact Card is `DRAFT_PENDING_USER_REVIEW`; this is a real upload blocker until the user explicitly approves it.

**Stop condition:** update the source/tests and sanitized technical status, push normally, and provide the user the review-package path plus concise evidence. The user performs the final sample/Fact Card acceptance. Do not start Slice B or upload anything before that acceptance.

## 2. Slice B — only after Slice A acceptance

Follow the frozen V5 AC-26 through AC-57. Implement the remaining four registered scene families (particle assembly/crystal lattice; heterogeneous nucleation/interface; crystal-growth front/growth steps; dendritic growth/morphology), the shared camera-aware safe-zone system, deterministic global frame budgeting/trimming, and the associated QA.

Create complete review packages for the three V5 representative topics:
1. nucleation;
2. crystal growth;
3. ice/crystal morphology.

All scripts and claims must be linked to approved Fact Cards and their source records. A model may select registered templates and parameters; it must not generate unrestricted executable Manim code. Flow stays optional and must not define scientific trajectories, lattice geometry, quantitative curves, or mechanisms.

Run the V5 Slice B test list once in a focused manner. The user must inspect and accept all three videos on a mobile screen. Do not enter Milestone 2 before this exit condition is met.

## 3. Milestone 2 — independent unpublished-draft uploader, after Slice B acceptance

Implement V5 AC-58 through AC-87 in this repository only.

Required design:
- dedicated non-default Edge user-data directory belonging to WeChat_Video;
- persistent detached Edge process with loopback-only CDP;
- strict process identity validation (executable, PID, process creation time, command line, user-data directory, port, version);
- atomic, non-secret session metadata at `runtime/edge_session.json`;
- reuse a valid existing Edge/CDP session; never start a second Edge against an occupied profile;
- Playwright connects to the existing persistent context, preserves old review tabs, opens a new job tab, then disconnects without closing the context or Edge;
- semantic locators first; selectors live in `config/selectors.yaml`;
- verify account identity is 「成核生长」, login state, selected MP4, upload completion, preview readiness, metadata and enabled draft-save control;
- take a pre-upload draft-list snapshot; click save exactly once; use bounded polling and reconcile the newly-created unpublished draft against the snapshot;
- uncertain save outcome becomes `UPLOAD_UNKNOWN`; never blindly retry and never submit the same job twice;
- leave Edge open at the new draft/review interface.

Never store cookies, tokens, passwords, or authentication secrets in files or logs. Never attach to the user's ordinary Edge profile. CDP must never be exposed beyond loopback.

### Absolute publication boundary

The automation may save an unpublished draft only. It must never click Publish, Send, final confirmation, schedule publication, delete/overwrite an unrelated draft, or bypass manual review. Never upload a pending/unapproved Fact Card sample.

For the first live upload test, use one user-approved, QA-passed video. The local test must verify the actual new entry in the account's draft list, not merely a button click or toast. Keep evidence sanitized; do not upload local media or screenshots to GitHub. The user performs the final visual review in the still-open Edge draft/review tab.

## 4. Milestone 3 — daily A-mode workflow, only after Milestone 2 acceptance

After the user verifies the real unpublished test draft, implement V5 AC-88 onward:
- `Run_Daily_Video.bat` as the single user entry point;
- Python-owned Windows kernel mutex, recovery audit, disk checks and job state machine;
- human-approved local Verified Topic Pool; select exactly one unused approved topic per day;
- bounded OpenCode Go calls and strict structured output validation;
- local TTS/Manim/FFmpeg, full QA, persistent Edge reuse and verified draft upload;
- idempotent task state, duplicate prevention, `UPLOAD_UNKNOWN` reconciliation and a daily report.

No topic may enter the Verified Topic Pool without explicit human approval. An empty queue must stop safely. Daily automation saves drafts only; the user remains the only publisher.

## 5. Final report format

Report only evidence-backed outcomes:
- branch, starting/final commit SHA, PR state and URL;
- exact files changed;
- acceptance criteria completed vs blocked;
- commands/checks actually run and results (never claim a Windows check that was not executed on Windows);
- for each local video: output path, duration, QA result, Fact Card approval status;
- for the first upload test: account identity check, pre/post draft reconciliation, verified draft title/time/platform identifier if visible, final Edge state;
- explicit confirmation that no Publish/Send action occurred.

Do not claim that a video is in the draft box until the draft list has been read back and the new entry is matched to the job.
