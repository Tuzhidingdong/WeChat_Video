# Daily Dual-Content Production

**Feature branch:** `feat/daily-literature-and-popularization`  
**Plan:** `TASK_PLAN_V6_DUAL_CONTENT_PIPELINES.md`  
**Authority:** `TASK_PLAN.md` V5 remains frozen and unchanged.

## Two independent entry points

- `Run_Literature_Reading_Draft.bat`: selects the latest eligible article already published on the previous Asia/Shanghai calendar day, creates an evidence-linked Chinese short video, runs technical and source-structure QA, uploads the exact run, and verifies one unpublished draft.
- `Run_Field_Popularization_Draft.bat`: selects one unused human-approved Fact Card with a registered visual strategy, asks the restricted OpenCode planner for a source-constrained narration script, renders it with the existing Slice A engine, runs strict QA, uploads the exact run, and verifies one unpublished draft.
- `Run_Daily_Two_Videos.bat`: executes both jobs sequentially under one cross-process lock. One pipeline failure does not prevent the other from being attempted.

The first two launchers can be started independently. They share a global lock because Manim production and the dedicated Edge/CDP uploader are not safe for concurrent use.

## Literature article inbox contract

The configured inbox is `configs/daily_pipelines.json` → `literature.article_inbox_dir`. The current default is:

```
runtime/inbox/literature_articles/
  <article_id>/
    article.json
    article.md
    images.json
    images/
      ...
```

The default path is a project-local handoff placeholder until the read-only local audit confirms the real publishing-workflow export location. Set it to the verified read-only/import directory before enabling unattended runs. Do not connect to or reuse the WeChat_control browser profile or private session.

Packages must be complete, published, in the 「成核生长」 account, and carry the existing literature taxonomy:
- `editorial_slot=1`
- `article_type=literature_translation`
- `editorial_pillar_id=literature_manuscript`
- `publication_status=PUBLISHED`

The run selects the latest `published_at` whose timestamp converts to the previous Asia/Shanghai calendar day. It records all candidate IDs and rejection reasons. A missing verified canonical URL does not block a video because the platform's WeChat article link field rejected the source article under its current readership/recent-publication eligibility rule. The original URL, if verified, remains in the local source record only.

The content planner receives article metadata, full text and image manifest as explicit file attachments. It must return 5–8 narration units, exactly one visual beat per unit, 222–235 Chinese Han characters, exact contiguous source excerpts for every claim, and only local image IDs. The existing article-summary validator rechecks source hash, excerpt membership, claim IDs, beat structure and image references before Edge-TTS starts.

The final 1.8-second video outro states:

**更多详细解读见【成核生长】同名公众号**

No WeChat extended-link field is filled.

## Popularization source contract

The runner reads only JSON Fact Cards under the configured directory and their matching `sources.json`. A card must either be tracked as `APPROVED` with approver metadata or have a valid hash-bound local topic approval record. `DRAFT_PENDING_USER_REVIEW` and review-sample cards are ineligible.

The runner also requires an editorial angle already present in `pipeline.VISUAL_STRATEGIES`. At this integration baseline, the registered strategies are:
- `critical_radius_growth_perspective`
- `free_energy_barrier_perspective`

This intentionally restricts production to the currently implemented scientific scene templates. It does not invent new Fact Cards, approve cards automatically, or pretend a generic renderer exists for an unregistered topic. If no unused approved card with a registered strategy exists, the pipeline returns `SKIPPED_NO_APPROVED_TOPIC`.

The topic history is keyed by Fact Card ID. Once selected for a production attempt, that card is consumed to prevent silent recycling after a failure.

## Content planner and model access

The configured OpenCode executable runs non-interactively with `opencode run --agent daily-content-planner --file ...`. The project agent has all tool permissions denied and is instructed to use only the explicitly attached source files. No web search, arbitrary shell, project browsing, editing, or delegation is part of content planning. OpenCode returns a JSON object; the application validates it before rendering.

The default model is the user's currently configured OpenCode model. An explicit model may be set in `configs/daily_pipelines.json`. The planner timeout and model choice are recorded in daily task reports.

## Shared engine and upload

The literature path reuses Edge-TTS, measured PCM audio timeline, word-boundary metadata, subtitle generation, Manim article scenes, FFmpeg assembly and strict QA. The popularization path reuses the existing Slice A personal-voice production, bilingual subtitles, registered Manim strategy, content-uniqueness gate and strict QA.

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
1. the local read-only audit has confirmed the actual article-package handoff directory;
2. the local Agent has synced and accepted the exact feature branch SHA;
3. at least one real literature article has been converted to and verified as a draft;
4. at least one human-approved eligible Fact Card has been converted to and verified as a draft;
5. the user has personally inspected both draft videos.

After these gates, a single daily Task Scheduler task may call `Run_Daily_Two_Videos.bat --scheduled`. The launcher skips its interactive pause in scheduled mode. Keep the two independent BAT files available for manual execution and recovery.

## Human acceptance

A machine-verified draft is not user visual acceptance. The user must inspect the two final videos in the 「成核生长」 Channels draft box. No workflow marks the user's visual/audio acceptance complete and no workflow publishes automatically.
