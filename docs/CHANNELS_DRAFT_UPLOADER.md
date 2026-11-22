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
3. Run Inspect_Channels_UI.bat. The inspector inventories account identity and controls in the platform shell and embedded frames without uploading, filling or saving. During an upload, the automation first opens the stable `/platform` shell and verifies the account. It inspects the exact configured `/micro/content/iframe/post-card.html` frame with `frame.evaluate()` using the same visibility and `innerText || textContent` rules as `channels-inspect`, then binds the unique exact `发表视频` node with `frame.evaluate_handle()` and clicks that `ElementHandle`. It does not use Playwright Locator queries for embedded-frame controls: this CDP session has previously returned zero Locator matches while direct DOM queries in the same frame found the live controls. The click only opens the creator form; it is not the final publication action. The same frame-local DOM scan/ElementHandle interaction path is used for title and description fields, the draft-save control, and the DraftListManager navigation menu. The uploader then inspects every live frame for file-input metadata, includes hidden file inputs (normal for browser upload controls), prefers explicit video MIME/extensions and video-specific labels, and waits up to 15 seconds for the creator control to mount. Image-only inputs are excluded. If the creator-entry button is missing/ambiguous, a frame cannot be inspected, or multiple equally ranked file inputs remain, the upload is blocked rather than clicking an arbitrary control or selecting an arbitrary file input.
4. Generate/select a complete output under outputs/. The uploader requires strict qa_report.json overall_status=PASS, valid channels_draft.json metadata and a complete final.mp4; no approval record is required.
5. Double-click Save_To_Channels_Draft.bat to upload the newest eligible existing output. It verifies the account, snapshots the draft list, uploads one MP4, fills metadata and clicks the draft-save control exactly once.
6. Before every draft-list read, the uploader opens the official `/platform` shell, verifies the configured account, expands the Content Management navigation group by hover, and clicks its visible `草稿箱` entry. It does not deep-link directly to `/platform/post/draftListManager`: a direct navigation was observed to set the child-frame URL without mounting the SPA list DOM. After the navigation click, it still requires the exact child-frame route, one visible `DraftListManager` root, selected `草稿箱 (n)` tab/header with matching counts, and the draft-list body container. The navigation label or URL alone is never accepted as proof. These checks and row reads execute with read-only `document.querySelectorAll()` / DOM inspection inside the target frame itself, avoiding the observed Playwright CDP cross-origin iframe locator failure. When the displayed draft count is positive, the uploader waits up to 15 seconds for readable visible rows and fails closed if none appear. It leaves Edge open at the draft list.

For a single-click Slice A test from generation through draft read-back, double-click Run_And_Save_Slice_A_Draft.bat. It generates a fresh review-sample package, then passes that exact run to the uploader. It cannot fall back to an older output. The sample remains pending scientific review and must be inspected before any manual publication.

Approve_Latest_Run.bat remains available as an optional per-video audit record, but it is not required for draft upload.

## 5. State and recovery

Job records are stored under ignored runtime/upload_jobs/. Relevant states include CREATED, PREPARED, UPLOADING, SAVE_REQUESTED, DRAFT_SAVED, UPLOAD_UNKNOWN, MANUALLY_CONFIRMED_DRAFT, MANUAL_REVIEW_NOT_FOUND and FAILED_BEFORE_SAVE.

For an uncertain outcome, run the read-only command:

.venv\Scripts\python.exe -X utf8 -m wechat_video.cli channels-reconcile --job-id <job-id>

Reconciliation never uploads, never clicks save and never retries. An upload-attempt ID is never reused.

The output directory is the **source run**; upload jobs are separate attempts against
that already-generated media. The first attempt keeps the historical job ID equal
to the output-folder name. If and only if an earlier job is `FAILED_BEFORE_SAVE`,
has no `upload_started_at`, has `save_click_count == 0`, and has no verified draft,
a later, separately user-authorized run of `Save_To_Channels_Draft.bat` creates
a new audit job ID such as `<output-folder>.upload_attempt_02` and reuses the
same QA-passed `final.mp4`. It does not regenerate or copy the video.

This exception does **not** apply merely because a job says
`FAILED_BEFORE_SAVE`: once `upload_started_at` exists, the file-input operation
may have begun, so another attempt is blocked. `UPLOADING`, `PREPARED`,
`SAVE_REQUESTED`, `UPLOAD_UNKNOWN`, confirmed-draft and manual-review states
are never bypassed by allocating a new attempt ID. Resolve uncertain states
through read-only reconciliation/manual review instead.

For a job that remains `UPLOAD_UNKNOWN`, inspect the target account's **草稿箱**
manually. The manual-review command only appends the user's attestation to the
local job record; it does not open a browser, change the prior Save click count,
or perform an upload:

```powershell
.venv\Scripts\python.exe -X utf8 -m wechat_video.cli channels-record-manual-review --job-id <job-id> --result draft-found --reviewed-by "<reviewer>" --row-text "<exact row copied from 草稿箱>" --confirmation "CONFIRM CHANNELS DRAFT FOUND <job-id>"
```

For a manual check that did not find the title, use `--result not-found`, supply
a non-empty `--note`, and confirm with
`CONFIRM CHANNELS DRAFT NOT FOUND <job-id>`. This records
`MANUAL_REVIEW_NOT_FOUND` as a time-scoped observation, **not** proof that the
earlier save request was never processed. The same job remains blocked from
another upload. A later manual check may append a new result; only a row that
contains the exact title can be recorded as `MANUALLY_CONFIRMED_DRAFT`.
Manual confirmation is explicitly distinguished from automated
DraftListManager read-back, and neither status verifies mobile-app visibility.

## 6. Browser security and privacy

- Dedicated Edge profile, never the user's ordinary Edge profile.
- CDP restricted to loopback; process identity validated by PID, creation time, executable, command line, profile path, port and browser version.
- If the profile is occupied but CDP cannot be verified, stop instead of launching a second Edge process.
- Cookies stay inside the local Edge profile; no cookies, credentials or tokens are exported.
- runtime/, approvals, Edge profile, job records, recordings, embeddings, WAV/MP4, models and caches remain ignored/untracked.

## 7. Verification boundary

GitHub Actions runs portable unit tests, including a frame-split creator-page fixture. Local Windows verification has confirmed the dedicated Edge/CDP lifecycle, the 「成核生长」 account identity, the short-title and file inputs, and the draft-save control. The new one-click Slice A route and standing-authorization behavior are code changes; they still require local sync and a real Windows run.

A passing unit test, UI inventory or toast message is not proof of a real draft. Success means the newly-created unpublished draft has been read back from the actual account's draft list and matched to the job.


## Headless operation and draft persistence

Automated uploads use the dedicated project Edge profile in `--headless=new`
mode by default (`headless: true` in `config/channels_upload.json`). The
automation does not create visible browser windows or bring upload/draft tabs
to the foreground. The separate manual-login command deliberately opens a
headed window so a QR code can be scanned. A running headed session cannot be
silently converted to headless mode: close only the project-owned Edge window
for this profile manually before an automated run. The automation will never
terminate an existing browser process or start a second process against an
active profile.

After metadata entry, the uploader clicks the unique enabled `保存草稿`
control once. It never retries that click. After a short settle interval, it
opens DraftListManager once to refresh the server-backed list, then polls the
already-mounted list DOM every 3 seconds for up to 90 seconds. It does not
re-navigate or remount the SPA on every poll. Each sample records the captured
time, draft count, matching-row count, route evidence, and any read error in
the ignored job record. Persistence is confirmed only when exactly one new
matching title is read back from the official DraftListManager page. A timeout
or ambiguous match remains `UPLOAD_UNKNOWN`; it never triggers another upload
or Save click. The polling window is configurable through
`draft_verify_timeout_seconds`, `draft_verify_poll_interval_seconds`, and
`draft_verify_initial_settle_seconds` in
`config/channels_upload.json`.

This desktop readback confirms that the web draft record exists; it does not
independently prove that the WeChat mobile client displays it. Check the target
phone after the run rather than treating desktop readback as proof of mobile
visibility.


### SPA parent-shell route compatibility

Some headless Channels sessions may keep the top-level page at the exact
`/platform` shell while the dedicated
`/micro/content/post/draftListManager` child frame hosts the actual draft
manager. The verifier accepts that shell route only when the child-frame path
matches exactly and the unique visible `DraftListManager` root, active
`草稿箱 (n)` tab, matching header count, and draft-list body container all
pass the same DOM checks as the direct route. The ordinary video-management
route and any other parent/child route combination remain rejected.


### DraftListManager SPA navigation

The official management shell must mount the draft-list micro-application through its
left navigation. The automation therefore opens `platform_url`, hovers the
Content Management submenu, clicks the visible `草稿箱` entry, and only then
checks the dedicated child frame. This avoids the observed failure mode where a
direct deep link changed the iframe URL but left its document body empty. The
same navigation helper is used for pre-upload snapshots, post-save readback, and
read-only reconciliation; none of those steps is allowed to infer success from
the route alone.
