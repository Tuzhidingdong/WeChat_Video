# Daily Dual-Content Production

**Feature branch:** `feat/daily-literature-and-popularization`  
**Plan:** `TASK_PLAN_V6_DUAL_CONTENT_PIPELINES.md`  
**Authority:** `TASK_PLAN.md` V5 remains frozen and unchanged.

## Two independent entry points

- `Run_Literature_Reading_Draft.bat`: selects the latest eligible article already published on the previous Asia/Shanghai calendar day, creates an evidence-linked Chinese short video, runs technical and source-structure QA, uploads the exact run, and verifies one unpublished draft.
- `Run_Field_Popularization_Draft.bat`: selects one unused human-approved Fact Card with a registered visual strategy, asks the restricted OpenCode planner for a source-constrained narration script, renders it with the existing Slice A engine, runs strict QA, uploads the exact run, and verifies one unpublished draft.
- `Run_Daily_Two_Videos.bat`: executes both jobs sequentially under one cross-process lock. One pipeline failure does not prevent the other from being attempted.

The first two launchers can be started independently. They share a global lock because Manim production and the dedicated Edge/CDP uploader are not safe for concurrent use.

## Automatic WeChat_control literature source

The literature BAT discovers source articles directly from the existing, completed WeChat_control daily-run output. No user-created article package or manual inbox is required.

Configured source settings in `configs/daily_pipelines.json`:

- `literature.upstream_daily_runs_dir`: `../data/daily_runs`, resolved relative to the Video project root.
- `literature.upstream_account_key`: `research_subscription`.
- `literature.expected_public_account_biz_id`: the exact public account `__biz` value used by the official album page.
- `literature.materialized_package_root`: Video-owned cache under `runtime/upstream_article_packages`.

### Unified read-only readiness check

`python -m wechat_video.cli inspect-daily-two-video-readiness [--published-date YYYY-MM-DD]` reports literature, popularization and shared readiness in one JSON, using `READY_FOR_HUMAN_AUTHORIZATION` / `PARTIALLY_READY` / `BLOCKED`. It is strictly read-only: no job record, no article package, no model task, no TTS/Manim/FFmpeg, no Edge, no upload and no input modification. Missing model or Fact Card approval are reported as human-decision blockers, not code defects.

### Independent publication-source evidence

Formal source attribution requires a structured `publication_source_evidence.json` in the matching Video output bundle. It is produced only from a real, read-only visible-browser observation of the official album page: the observed album page URL, the observed link attribute name/raw href, the browser-resolved article URL, the observed `data-msgid`/`data-itemidx`, the observed DOM relation, and an `observed_at` timestamp with timezone. The original href and the final resolved URL are stored separately; the album URL and the article URL are stored separately; the album `data-msgid` is never mixed with the publishing `appmsgid`.

The browser observation is currently triggered explicitly by an operator/Agent using the in-app browser (`/browser`) or the visible Edge window. It is **not** an unattended automatic scrape. Run `record-literature-source-evidence --observation <json>` to validate that observation and atomically add it to the unique matching Video evidence bundle; the command refuses existing targets, ambiguous bundles, and any mismatch of article_id/appmsgid/title/Markdown SHA-256/__biz. The adapter only reads and validates this evidence; it never opens a browser, uses cookies/tokens, or calls private APIs. Passing source-evidence validation does not mean a video or WeChat draft has been accepted.

The adapter scans:

```
E:\Agent\WeChat\data\daily_runs\<date>\research_subscription\<run_id>\
  slot1.md
  slot1.manifest.json
  prepared_articles.json
  review_state.json
  delivery_result.json
  uploaded_assets_manifest.json
```

The three publication-evidence files are **not** expected in the WeChat_control run folder. They are stored in the matching Video production output under `outputs/<article-summary-run>/`:

```
outputs/<article-summary-run>/
  article_summary_manifest.json
  source_record.json
  url_verification_evidence.json
  upload_preflight_report.json
  article_read_count_probe.json
  source/images/...
```

The adapter joins these two locations read-only. It accepts an evidence directory only when its `article_summary_manifest.json` and `source_record.json` both identify the same `article_id`, appmsgid, exact article title and Slot 1 Markdown SHA-256 as the upstream run. The three evidence files are then read from that matched Video output directory. A file in another output folder is never borrowed merely because it happens to contain a plausible timestamp or URL.

It reads these existing local outputs only. It does not modify WeChat_control, open its browser profile, read its credentials, reuse its CDP session, call private APIs, or repeat the upstream article-discovery/writing/draft workflow.

Before a run is eligible, the adapter verifies:

1. Slot 1 taxonomy is `literature_translation` + `literature_manuscript`.
2. Exact `slot1.md` bytes match both `slot1.manifest.json.output_sha256` and `review_state.json.slots.1.article_sha256`.
3. `prepared_articles.json` contains exactly one matching record, and its full `md_body` (and `raw_markdown`, when present) is byte-identical to `slot1.md`. The H1 must match its title.
4. The delivery appmsgid and `account` or `account_name` field match the configured target account (or its configured account key). The delivery result's `PENDING_PUBLICATION` state is not treated as publication evidence.
5. The matched Video evidence bundle records exactly one canonical `mp.weixin.qq.com/s` article URL. The URL must agree with the matching Video source manifest and, when present, `upload_preflight_report.json.url_provenance` and the read-count probe. The adapter does not require selector names such as `li.album__list-item` or the literal attribute label `data-link` to have been copied into the evidence JSON.
6. The recorded article URL or album endpoint must confirm the configured public-account `__biz`. Album `mid` and item `idx` are read from the observed URL/query or explicit recorded fields when available; conflicting values are rejected. The publishing appmsgid and album mid remain separate identifiers.
7. The matched Video `article_read_count_probe.json` must supply an unambiguous positive `ct` Unix timestamp. That instant is used as the publication time and converted to the configured Asia/Shanghai date. The draft/worker `article.json.published_at`, run date, draft-save time, and album update time are never substituted.

Only after all checks pass does Video create an immutable local package at:

```
runtime/upstream_article_packages/<appmsgid>_0/<run_id>/
  article.json
  article.md
  images.json
  images/                 # only verified, local original assets, when present
```

The Markdown is copied byte-for-byte from `slot1.md`. Original images already copied into the matching Video production output's `image_manifest` are reused first, but only when their files remain inside the configured Video `outputs` root, their recorded SHA-256 matches, they decode successfully, and their caption/context is grounded in the exact upstream Markdown. If no Video-side image is available, the adapter may use validated local files from the upstream `uploaded_assets_manifest.json`. It does not download CDN images or invent captions. The Video cache never overwrites a conflicting existing package.

If an upstream run lacks the verified public URL/time evidence, account binding, taxonomy or SHA chain, it is rejected and reported with a reason. No video is created from an unverified candidate. The planner's explicit model preflight occurs before Video materializes a package; a null model remains a clear planning blocker.

The content planner receives the exact package generated from the selected upstream run. Existing summary validation, Edge-TTS, Manim, FFmpeg, strict QA, and exact-run-directory draft uploader remain the downstream production engine. The fixed on-video CTA remains:

**更多详细解读见【成核生长】同名公众号**

No extended-link field is required.

Before the first production run, the local Agent can verify the actual upstream artifacts without creating any cache package or starting OpenCode/rendering/upload:

```powershell
.venv\Scripts\python.exe -X utf8 -m wechat_video.cli inspect-literature-upstream
```

This command is read-only. It reports eligible/rejected source runs, the exact `published_at` derivation and provenance, source SHA, canonical URL, and verified local-image count. It does not create output directories, materialize an article package, write a job journal, or launch any production tool.

## Popularization source contract

The runner reads only JSON Fact Cards under the configured directory and their matching `sources.json`. A card must either be tracked as `APPROVED` with approver metadata or have a valid hash-bound local topic approval record. `DRAFT_PENDING_USER_REVIEW` and review-sample cards are ineligible.

The runner also requires an editorial angle already present in `pipeline.VISUAL_STRATEGIES`. At this integration baseline, the registered strategies are:
- `critical_radius_growth_perspective`
- `free_energy_barrier_perspective`

This intentionally restricts production to the currently implemented scientific scene templates. It does not invent new Fact Cards, approve cards automatically, or pretend a generic renderer exists for an unregistered topic. If no unused approved card with a registered strategy exists, the pipeline returns `SKIPPED_NO_APPROVED_TOPIC`.

The topic history is keyed by Fact Card ID. Once selected for a production attempt, that card is consumed to prevent silent recycling after a failure.

## Content planner and model access

The configured OpenCode executable runs non-interactively with `opencode run --agent daily-content-planner --file ...`. The project agent has all tool permissions denied and is instructed to use only the explicitly attached source files. No web search, arbitrary shell, project browsing, editing, or delegation is part of content planning. OpenCode returns a JSON object; the application validates it before rendering.

An explicit model ID is required in `configs/daily_pipelines.json` (`opencode.model`). A null/empty model blocks planning; the pipeline never silently inherits a potentially different machine-default model. The launcher prints the Agent role, model, project root and attachment count before invoking the planner. The planner timeout and model choice are recorded in daily task reports.

## Shared engine and upload

The literature path reuses Edge-TTS, measured PCM audio timeline, word-boundary metadata, subtitle generation, Manim article scenes, FFmpeg assembly and strict QA. The popularization path reuses the existing Slice A personal-voice production, bilingual subtitles, registered Manim strategy, content-uniqueness gate and strict QA. It additionally enforces a 55–65 second measured PCM programme-duration gate before upload; the base Slice A command's duration warning alone is not treated as a release gate.

Both paths call `upload_run_to_channels(project_root, exact_run_dir)`. They do not use “upload newest output”. The uploader retains its dedicated Edge profile, target account verification, pre-save draft snapshot, single save click, post-save DraftListManager readback and `UPLOAD_UNKNOWN` reconciliation rules.

Only unpublished drafts can be saved. There is no Publish, Send, Schedule, Delete or Overwrite action.

## Daily job records and failure recovery

- Timezone: `Asia/Shanghai`.
- Literature date: previous local calendar day.
- Popularization job date: current local calendar day.
- Lock: `runtime/daily_pipelines/pipeline.lock`.
- Job records: `runtime/daily_pipelines/jobs/YYYY-MM-DD/{literature,popularization}.json`.
- Planner artifacts: `runtime/daily_pipelines/planner/YYYY-MM-DD/<source-id>/`.
- Topic history: `runtime/daily_pipelines/popularization_history.json`.

The runner writes state transitions atomically. An existing job record prevents blind automatic reruns. `UPLOAD_UNKNOWN` remains blocked until read-only reconciliation. A failure in one content type is reported independently and does not suppress the other job.

Aggregate outcomes are explicit:
- `DRAFTS_SAVED`: both pipelines verified new drafts.
- `COMPLETED_WITH_SKIPS`: no hard failure, but one or both pipelines safely skipped due to no eligible source.
- `PARTIAL_OR_BLOCKED`: a failure or upload uncertainty occurred.

## Entry commands

```powershell
.venv\Scripts\python.exe -X utf8 -m wechat_video.cli run-literature-daily
.venv\Scripts\python.exe -X utf8 -m wechat_video.cli run-popularization-daily
.venv\Scripts\python.exe -X utf8 -m wechat_video.cli run-daily-two-videos
```

Use `--published-date YYYY-MM-DD` for an explicitly selected literature publication date and `--local-date YYYY-MM-DD` for a testable popularization job date. Existing job records are never bypassed by a date override.

## Scheduling policy

Do not register a Windows Task Scheduler task until:
1. the upstream adapter has been synced locally and its source-evidence checks have passed against the real daily-run artifact;
2. the local Agent has synced and accepted the exact feature branch SHA;
3. at least one real literature article has been converted to and verified as a draft;
4. at least one human-approved eligible Fact Card has been converted to and verified as a draft;
5. the user has personally inspected both draft videos.

After these gates, a single daily Task Scheduler task may call `Run_Daily_Two_Videos.bat --scheduled`. The launcher skips its interactive pause in scheduled mode. Keep the two independent BAT files available for manual execution and recovery.

## Human acceptance

A machine-verified draft is not user visual acceptance. The user must inspect the two final videos in the 「成核生长」 Channels draft box. No workflow marks the user's visual/audio acceptance complete and no workflow publishes automatically.
