# WeChat Channels Unpublished-Draft Uploader

**Implementation branch:** feat/milestone-2-channels-draft-uploader  
**Authority:** TASK_PLAN.md V5 remains frozen.  
**Target account:** 「成核生长」  
**Publication boundary:** Save an unpublished draft only. No publish, send, schedule, delete or overwrite behavior exists.

## 1. What the implementation does

The uploader is an isolated local module. It attaches Playwright to a dedicated Microsoft Edge profile owned by WeChat_Video and operates the visible official Channels Assistant pages:

- Create page: https://channels.weixin.qq.com/platform/post/create
- Draft manager: https://channels.weixin.qq.com/platform/post/draftListManager

The normal `/platform/post/list` route is the video-management page, not the draft list. The uploader must not infer the current view from the persistent left-navigation text "草稿箱".

It does not use WeChat_control, its browser profile, code, BAT files, account data, selectors or automation implementation. It does not call private platform APIs.

Each generated review package carries channels_draft.json. The short title uses the Fact Card's explicit channels_title (6–16 characters); the longer scientific title is preserved. The description is built only from the Fact Card's scientific question and scope. New Fact Cards without a valid short title are blocked instead of silently truncated.

## 2. One-time setup

Run Setup_Slice_A.bat once after syncing this branch. Playwright, psutil and PyYAML are installed inside the project's .venv. The uploader attaches to the installed Microsoft Edge; it does not download a second browser and does not install globally.

## 3. Standing draft-only authorization

The user has granted standing authorization for this project to upload strict-QA-PASS outputs as **unpublished drafts** without a per-video or Fact Card approval prompt. This is not authorization to publish, send, schedule, delete or overwrite.

Approve_Fact_Card.bat remains available for the separate decision to admit a Fact Card into the human-approved Verified Topic Pool. That approval is not required for the draft-only review workflow.

## 4. Edge session and draft upload

1. Double-click Open_Channels_Session.bat. It creates or reuses the dedicated Edge profile at runtime/edge-profile, with CDP bound only to 127.0.0.1.
2. Complete the official QR login manually for the intended 「成核生长」 account.
3. Run Inspect_Channels_UI.bat. The inspector inventories account identity and controls in the top page and embedded frames without uploading, filling or saving.
4. Generate/select a complete output under outputs/. The uploader requires strict qa_report.json overall_status=PASS, valid channels_draft.json metadata and a complete final.mp4; no approval record is required.
5. Double-click Save_To_Channels_Draft.bat to upload the newest eligible existing output. It verifies the account, snapshots the draft list, uploads one MP4, fills metadata and clicks the draft-save control exactly once.
6. The uploader re-reads the dedicated DraftListManager view and verifies exactly one new title match inside its confirmed draft-list container. The view is accepted only when the page route, child-frame route, `DraftListManager` root, selected `草稿箱 (n)` tab/header, and draft-list body container agree. The visible left-navigation label alone is never accepted as proof. These checks and row reads execute with read-only `document.querySelectorAll()` / DOM inspection inside the target frame itself, avoiding the observed Playwright CDP cross-origin iframe locator failure. When the displayed draft count is positive, the uploader waits up to 15 seconds for readable visible rows and fails closed if none appear. It leaves Edge open at the draft list.

For a single-click Slice A test from generation through draft read-back, double-click Run_And_Save_Slice_A_Draft.bat. It generates a fresh review-sample package, then passes that exact run to the uploader. It cannot fall back to an older output. The sample remains pending scientific review and must be inspected before any manual publication.

Approve_Latest_Run.bat remains available as an optional per-video audit record, but it is not required for draft upload.

## 5. State and recovery

Job records are stored under ignored runtime/upload_jobs/. Relevant states include CREATED, PREPARED, UPLOADING, SAVE_REQUESTED, DRAFT_SAVED, UPLOAD_UNKNOWN and FAILED_BEFORE_SAVE.

For an uncertain outcome, run the read-only command:

.venv\Scripts\python.exe -X utf8 -m wechat_video.cli channels-reconcile --job-id <output-folder-name>

Reconciliation never uploads, never clicks save and never retries. The same job ID cannot be uploaded twice.

## 6. Browser security and privacy

- Dedicated Edge profile, never the user's ordinary Edge profile.
- CDP restricted to loopback; process identity validated by PID, creation time, executable, command line, profile path, port and browser version.
- If the profile is occupied but CDP cannot be verified, stop instead of launching a second Edge process.
- Cookies stay inside the local Edge profile; no cookies, credentials or tokens are exported.
- runtime/, approvals, Edge profile, job records, recordings, embeddings, WAV/MP4, models and caches remain ignored/untracked.

## 7. Verification boundary

GitHub Actions runs portable unit tests, including a frame-split creator-page fixture. Local Windows verification has confirmed the dedicated Edge/CDP lifecycle, the 「成核生长」 account identity, the short-title and file inputs, and the draft-save control. The new one-click Slice A route and standing-authorization behavior are code changes; they still require local sync and a real Windows run.

A passing unit test, UI inventory or toast message is not proof of a real draft. Success means the newly-created unpublished draft has been read back from the actual account's draft list and matched to the job.
