# Daily Dual-Content Video Production — Version 6 Addendum

**Status:** Authorized product-scope addendum; implementation proceeds on `feat/daily-literature-and-popularization`.

**Authority relationship:** `TASK_PLAN.md` V5 remains frozen and unchanged. This document records the user's later explicit product requirements. It does not mark any V5 milestone exit condition as accepted and does not authorize publication.

## 1. Product goal

Produce two distinct WeChat Channels review drafts each day for the account 「成核生长」:

1. **Literature reading:** select one already-published article from the previous Asia/Shanghai calendar day where the upstream metadata identifies the 「文献精读」 column; generate an evidence-grounded one-minute Chinese article explainer.
2. **Related-field popularization:** select one unused, human-approved Fact Card from the local Verified Topic Pool; generate a source-constrained science-popularization video using the registered visual strategy.

Both pipelines save unpublished drafts. The user inspects both finished videos in the Channels draft box and performs any final publication manually.

## 2. Required entry points

- `Run_Literature_Reading_Draft.bat` — independently runs the previous-day literature article pipeline.
- `Run_Field_Popularization_Draft.bat` — independently runs the approved-topic popularization pipeline.
- `Run_Daily_Two_Videos.bat` — optional sequential dispatcher intended for one daily Windows Task Scheduler trigger. It invokes both independent workflows without parallel Edge automation.

The BAT files are thin launchers. They must not duplicate rendering, QA, or uploader logic.

## 3. Shared production engine

Reuse the existing project-local environment, approved source/claim validation, TTS, measured audio timeline, Manim renderer, FFmpeg assembly, strict QA, dedicated Edge/CDP profile, account identity check, single-save behavior, upload job records, and DraftListManager readback.

The two content types keep separate:
- source selection and eligibility rules;
- prompts and content schemas;
- output metadata and outro rules;
- per-day idempotency keys and history;
- reports and failure states.

A single cross-process production/upload lock serializes operations that share Manim resources and the one dedicated Edge profile. The combined dispatcher executes the two pipelines sequentially.

## 4. Literature reading contract

- Consume only complete, already-published local article packages exported by the upstream publishing workflow.
- Required taxonomy: account 「成核生长」, `editorial_slot=1`, `article_type=literature_translation`, `editorial_pillar_id=literature_manuscript`, `publication_status=PUBLISHED`.
- Select from the previous Asia/Shanghai calendar date, not “last 24 hours”.
- When multiple candidates exist, choose deterministically by latest `published_at`; record all candidates and the selection reason.
- Never invent a source URL. Video production does not require the WeChat extended-link feature.
- Generate a source-locked `summary.json` using the restricted OpenCode content-planner agent and attached article package only.
- The final video outro must display: **「更多详细解读见【成核生长】同名公众号」**.
- A missing or incomplete article package causes a safe skip/block, not a guessed summary.
- A previously generated `article_id` is not regenerated automatically.

The local article inbox path is configured in `configs/daily_pipelines.json`. The exact upstream export path must be confirmed from the read-only local audit before unattended scheduling.

## 5. Popularization contract

- Select only Fact Cards with a valid explicit approval record and complete source records.
- Pending/review-sample cards are never eligible.
- The content planner may create a new script from the approved Fact Card, but it may not add claims.
- The selected card's `editorial_angle_id` must have a registered visual strategy.
- Claim links, script schema, content uniqueness, strict media QA, and source metadata are mandatory.
- Each `fact_card_id` is used at most once by the daily pool unless a human explicitly resets its history.
- Empty eligible pool produces a visible skip; no pending card is promoted automatically.

## 6. Scheduling and idempotency

- All date comparisons use the configured `Asia/Shanghai` timezone.
- Stable job keys are `local-date + content-type + source-id`.
- A cross-process OS file lock prevents concurrent jobs from manipulating the same Edge profile or production resources.
- Each job writes an atomic state record and a run manifest.
- Completed, failed-after-side-effect, uncertain-upload, and duplicate states are never blindly rerun.
- Upload always passes the exact generated `run_dir` to the shared uploader; “newest output” selection is not used by the daily workflows.
- The dispatcher continues to the second content type if the first fails, and reports both independently.
- `UPLOAD_UNKNOWN` is reconciled read-only. It never causes an automatic second upload.

## 7. Draft-only policy

Only a complete output with strict technical QA PASS and the content-specific evidence gate may be uploaded.

The only permitted terminal upload state is a verified unpublished draft. The uploader must read the actual DraftListManager and confirm one new matching row. No Publish, Send, Schedule, Delete, or Overwrite action is allowed.

## 8. Quality policy

Preserve the currently accepted visual quality baseline while adding the literature outro. Subsequent visual improvements are separate work and must be justified by measured/user-observed defects; do not redesign the engine as part of dual-pipeline integration.

## 9. Acceptance gates

1. Read-only local audit identifies the actual upstream article-package handoff path and local runtime constraints.
2. Portable unit/contract tests pass on GitHub Actions.
3. Local Windows Agent syncs the exact approved feature-branch SHA and runs the bounded local validation suite.
4. A real literature article produces one strict-QA-PASS MP4 with the requested outro and is saved as one verified unpublished draft.
5. An approved popularization Fact Card produces one strict-QA-PASS MP4 and is saved as one verified unpublished draft.
6. The user personally inspects both draft videos. No automated step marks user visual/audio acceptance complete.
7. Only after user review is the Windows daily schedule registered and enabled.

## 10. Explicit non-goals

- Do not modify `WeChat_control` in this repository task.
- Do not publish or schedule videos on WeChat Channels.
- Do not scrape or invent unavailable source information.
- Do not approve Fact Cards on the user's behalf.
- Do not add a new visual template library or broad visual redesign in this integration.
- Do not modify frozen `TASK_PLAN.md` V5.


### Explicit model configuration

The daily content-planner must use an explicitly named OpenCode model. An empty `opencode.model` value blocks content planning and prevents the pipeline from silently inheriting a local default model.
