# WeChat Channels Unpublished-Draft Uploader

**Implementation branch:** feat/milestone-2-channels-draft-uploader  
**Authority:** TASK_PLAN.md V5 remains frozen.  
**Target account:** 「成核生长」  
**Publication boundary:** Save an unpublished draft only. No publish, send, schedule, delete or overwrite behavior exists.

## 1. What the implementation does

The uploader is an isolated local module. It attaches Playwright to a dedicated Microsoft Edge profile owned by WeChat_Video and operates the visible official Channels Assistant pages:

- Create page: https://channels.weixin.qq.com/platform/post/create
- Draft list: https://channels.weixin.qq.com/platform/post/list

It does not use WeChat_control, its browser profile, code, BAT files, account data, selectors or automation implementation. It does not call private platform APIs.

Each generated review package carries channels_draft.json. The short title uses the Fact Card's explicit channels_title (6–16 characters); the longer scientific title is preserved. The description is built only from the Fact Card's scientific question and scope. New Fact Cards without a valid short title are blocked instead of silently truncated.

## 2. One-time setup

Run Setup_Slice_A.bat once after syncing this branch. Playwright, psutil and PyYAML are installed inside the project's .venv. The uploader attaches to the installed Microsoft Edge; it does not download a second browser and does not install globally.

## 3. Normal daily authorization

Approve each scientific Fact Card and source record once:

1. Double-click Approve_Fact_Card.bat.
2. Read the scientific question, model scope, claims, conditions, caveats and source list printed by the CLI.
3. Type the exact phrase APPROVE FACT CARD <fact_card_id> only after deciding the topic is scientifically acceptable.

The approval is stored under ignored runtime/topic_approvals/. It binds the exact Fact Card and source-record SHA-256 hashes. The tracked Fact Card remains unchanged. If either source file changes, the old approval becomes invalid and the card must be reviewed again.

This is a one-time topic approval, not a per-video approval. Thereafter, each generated video must independently pass strict technical QA before it can be uploaded as a draft.

## 4. Edge session and draft upload

1. Double-click Open_Channels_Session.bat. It creates or reuses the dedicated Edge profile at runtime/edge-profile, with CDP bound only to 127.0.0.1.
2. Complete the official QR login manually for the intended 「成核生长」 account.
3. Run Inspect_Channels_UI.bat. The inspector waits up to 15 seconds for the signed-in account node and inventories controls separately for the top page and embedded frames without uploading, filling or saving. Verify account identity and live controls; report selector mismatches before any upload. The description editor selector matches an empty-valued contenteditable attribute, as used by the live editor.
4. Generate/select a complete output under outputs/. The uploader requires a valid one-time Fact Card approval, strict qa_report.json overall_status=PASS, valid channels_draft.json metadata and a complete final.mp4.
5. Double-click Save_To_Channels_Draft.bat. It selects the newest eligible output, verifies the account, snapshots the draft list, uploads one MP4, fills metadata and clicks the draft-save control exactly once.
6. The uploader re-reads the draft list and verifies exactly one new row matching the short title and an explicit draft status. It leaves Edge open at the draft list.

A previous --review-sample output is eligible only after the user has approved that exact Fact Card/source pair and the output package passes strict QA. The ordinary non-review production path must also verify the same one-time topic approval.

Approve_Latest_Run.bat remains an optional stricter per-video approval path. It is not required for the daily A-mode flow.

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

GitHub Actions runs portable unit tests, including a frame-split creator-page fixture. Local Windows verification has confirmed the dedicated Edge/CDP lifecycle, the 「成核生长」 account identity, the short-title and file inputs, and the draft-save control. The remaining local Windows checks are to sync this frame-aware fix, rerun the full test suite, and then verify the live description editor and save/preview/list selectors before the first upload.

A passing unit test, UI inventory or toast message is not proof of a real draft. Success means the newly-created unpublished draft has been read back from the actual account's draft list and matched to the job.
