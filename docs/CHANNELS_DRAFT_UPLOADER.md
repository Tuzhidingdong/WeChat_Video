# WeChat Channels Unpublished-Draft Uploader

**Implementation branch:** `feat/milestone-2-channels-draft-uploader`  
**Authority:** `TASK_PLAN.md` V5 remains frozen.  
**Target account:** 「成核生长」  
**Publication boundary:** Save an unpublished draft only. No publish, send, schedule, delete or overwrite behavior exists.

## 1. What the implementation does

The uploader is an isolated local module. It attaches Playwright to a dedicated Microsoft Edge profile owned by WeChat_Video and operates the visible official Channels Assistant pages:

- Create page: `https://channels.weixin.qq.com/platform/post/create`
- Draft list: `https://channels.weixin.qq.com/platform/post/list`

It does not use WeChat_Control, its browser profile, code, BAT files, account data, selectors or automation implementation. It does not call private platform APIs.

The generated review package carries `channels_draft.json`. The short title uses the Fact Card's explicit `channels_title` (6–16 characters); the longer scientific Fact Card title remains unchanged. The description is built only from the Fact Card's scientific question and scope. It does not add scientific claims. New Fact Cards with no valid short title are blocked rather than silently truncated.

## 2. One-time local setup

The project setup now installs these additional project-local packages:

- Playwright Python client
- psutil for Windows process/listener identity checks
- PyYAML for the selector configuration

No Playwright-managed Chromium download is required: the code connects to the installed Microsoft Edge executable. No global Python packages are installed.

Run `Setup_Slice_A.bat` once after syncing this branch. It reuses the repository's existing .venv and installs the missing upload dependencies from `requirements-slice-a.txt`.

## 3. Local operation

1. Double-click `Open_Channels_Session.bat`. It creates or reuses the dedicated ignored profile at `runtime/edge-profile`, starts Edge with CDP bound only to 127.0.0.1 and opens the official create page.
2. Sign in by the normal official QR/login flow in that Edge window. Do not copy cookies or session files.
3. Double-click `Inspect_Channels_UI.bat`. It outputs a sanitized list of visible buttons, text boxes and file-input accept types. It performs no upload/save action. If the actual UI differs, update only `config/selectors.yaml` based on that observed interface.
4. Generate a local video as usual. The production pipeline writes `channels_draft.json` next to `final.mp4`.
5. Watch the complete MP4 and review the Fact Card, source record and generated draft title/description. Double-click `Approve_Latest_Run.bat`; the CLI prints the claims and metadata and requires the exact phrase `APPROVE <fact_card_id>`. This creates a local approval record bound by SHA-256 to the exact MP4, Fact Card, source record, QA report and metadata file.
6. Double-click `Save_To_Channels_Draft.bat`. It selects the newest explicitly approved run, verifies strict QA PASS and unchanged artifact hashes, verifies the expected account, snapshots the draft list, uploads one MP4, fills metadata and clicks the draft-save control exactly once.
7. The uploader re-reads the draft list and requires exactly one new row matching the title and an explicit draft status. It writes a local job report under ignored `runtime/upload_jobs/` and leaves Edge open at the draft list.

The existing `--review-sample` path remains a review-only path. A QA PASS by itself does not authorize uploading. Both Fact Card and video approval are required.

## 4. State and recovery

Job records live under ignored `runtime/upload_jobs/`. The relevant states are:

- `CREATED`, `PREPARED`, `UPLOADING`
- `SAVE_REQUESTED` immediately before the one permitted save click
- `DRAFT_SAVED` only after a new draft row is read back
- `UPLOAD_UNKNOWN` when the save outcome cannot be proven
- `FAILED_BEFORE_SAVE` when the operation stopped before save was requested

For `SAVE_REQUESTED` or `UPLOAD_UNKNOWN`, run:

```text
.venv\Scripts\python.exe -X utf8 -m wechat_video.cli channels-reconcile --job-id <output-folder-name>
```

Reconciliation is read-only. It never uploads, clicks save, retries the previous request or publishes. If the list cannot prove a unique new unpublished draft, the state remains uncertain and requires manual inspection.

The same job ID cannot be uploaded twice. A job already recorded as `DRAFT_SAVED`, `SAVE_REQUESTED`, `UPLOAD_UNKNOWN`, `UPLOADING` or `PREPARED` is blocked from another upload attempt.

## 5. Browser security and privacy

- The dedicated Edge profile is not the user's normal Edge profile.
- CDP is explicitly bound to `127.0.0.1`; the process owning its port is checked against PID, creation time, executable, command line and profile directory.
- If the profile is occupied but its CDP endpoint cannot be verified, the program stops instead of launching another Edge instance.
- Browser cookies remain inside Edge's local profile. They are not exported, parsed or copied into project files.
- The session registry stores only process/profile/port/version metadata; no cookie, token or password.
- The Edge process and persistent context are not closed when the Python command exits.
- `runtime/` is ignored by Git. Never commit the Edge profile, approval records, job logs, screenshots, videos, WAVs, voice recordings, speaker embeddings or model caches.

## 6. Verification boundary

Unit tests cover deterministic metadata, explicit approval, artifact hash binding and draft-list matching. They do not simulate a real Channels website.

The following require local verification on the user's Windows machine:
- Edge executable discovery and persistent CDP process identity;
- manual account login and exact account name 「成核生长」;
- current UI selectors for the create and draft-list pages;
- actual file upload and preview readiness;
- single save click and draft-list readback;
- Edge remaining open after the CLI exits.

Do not report a successful upload from a unit test, selector inspection, toast message or save-button click. Success means the newly-created unpublished draft row has been read back and matched against the pre-upload snapshot.
