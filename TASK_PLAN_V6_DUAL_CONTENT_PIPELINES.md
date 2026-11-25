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

- Discover existing successful Slot 1 runs directly from the upstream local output `../data/daily_runs/<date>/research_subscription/<run_id>/`, relative to the Video project root. Do not require a user-created article package or manual inbox.
- The configured source account key is `research_subscription`; the target public account is `成核生长` and its verified `__biz` value is configured explicitly.
- Required taxonomy: `literature_translation` + `literature_manuscript` for Slot 1.
- Verify the exact `slot1.md` SHA-256 against `slot1.manifest.json.output_sha256` and `review_state.json.slots.1.article_sha256`; require the full `prepared_articles.json` `md_body` to be byte-identical to the exact Markdown.
- The delivery `appmsgid` and account must match. The upstream draft/worker `published_at`, run date, and draft-save time are not publication evidence.
- Formal publication status/time requires the recorded official album DOM entry `li.album__list-item[data-link]`, matching target-account `__biz`, exact article title, Slot 1 item index, canonical URL provenance, and a positive Unix `ct` from the same run's `article_read_count_probe.json`.
- Convert `ct` to the configured Asia/Shanghai date. Keep the publishing `appmsgid` and album `data-msgid` (mid) as separate namespaces.
- Reject incomplete or ambiguous source evidence with a per-run reason. Do not substitute draft timestamps, guess URLs, or create a video from an unverified candidate.
- After source validation and explicit OpenCode model preflight, materialize a byte-identical Markdown package in Video-owned `runtime/upstream_article_packages/<appmsgid>_0/<run_id>/`; do not modify upstream files or overwrite a conflicting cache entry.
- Copy only verified local, decodable source images with article-grounded context. Do not fabricate captions or fetch unverified images.
- A read-only `inspect-literature-upstream` CLI command reports eligible/rejected source runs and evidence without materializing packages or launching any production step.
- Select the latest eligible article on the previous Asia/Shanghai calendar date; never use a “last 24 hours” window.
- Generate a source-locked `summary.json` using the restricted OpenCode content-planner agent and the automatically materialized package only.
- The final video outro must display: **「更多详细解读见【成核生长】同名公众号」**.
- A previously generated `article_id` is not regenerated automatically.

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

1. The read-only upstream adapter is validated against the real local daily-run sample, including publication URL/time evidence and the exact Markdown hash chain.
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
