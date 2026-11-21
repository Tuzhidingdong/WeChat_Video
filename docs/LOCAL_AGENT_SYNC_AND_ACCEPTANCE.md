# Local Agent — Sync and Acceptance Only

The user has assigned all GitHub code development to the ChatGPT developer. The local Agent's role is limited to synchronizing the developer's commits and performing local acceptance/verification. **Do not implement features, edit source, create commits, push code, redesign architecture or delegate workers.**

## Sync target

- Repository: `Tuzhidingdong/WeChat_Video`
- Branch: `feat/milestone-2-channels-draft-uploader`
- Sync the latest branch head from GitHub by a safe fast-forward.
- Preserve uncommitted local work. Do not reset, force-push or rewrite history.
- Do not touch `main`, PR #2 or `TASK_PLAN.md` V5.
- Do not access, copy, invoke or modify `Tuzhidingdong/WeChat_control`.

## Local acceptance checks

1. Read `docs/CHANNELS_DRAFT_UPLOADER.md`, `STATUS.md` and the existing V5 constraints.
2. Confirm the synchronized commit SHA and branch.
3. Confirm `Setup_Slice_A.bat` detects/installs Playwright, psutil and PyYAML inside the project .venv. Do not install globally.
4. Run `.venv\Scripts\python.exe -X utf8 -m pytest -q` once. Report the complete pass/fail summary.
5. Run the existing project preflight once only if the local runtime is already set up. Do not render another video as part of uploader acceptance.
6. Double-click or invoke `Open_Channels_Session.bat` only to confirm that the dedicated Edge profile launches/reuses safely. If QR login is needed, let the user perform the normal login.
7. Run `Inspect_Channels_UI.bat` after login. Report the visible button names, text-box placeholders and file-input accept types, and whether the exact account name 「成核生长」 was detected. If actual controls differ from `config/selectors.yaml`, report observed differences; do not edit the selector/code yourself.
8. Verify the local profile/session/job/approval paths are ignored by Git and no credentials or browser cookies are present in tracked files.

## Do not perform these actions

- Do not run Slice A production BATs or generate another video.
- Do not approve a Fact Card or video on the user's behalf.
- Do not run `Approve_Latest_Run.bat` or create an approval JSON.
- Do not run `Save_To_Channels_Draft.bat`, upload a video or click any draft-save control.
- Never click Publish, Send, Schedule, delete or overwrite.
- Do not upload any MP4, WAV, screenshot, voice recording, speaker embedding, model or cache to GitHub.
- No coding, no commits, no pushes and no hidden workers.

## Report

Return only:
- synchronized branch and exact SHA;
- dependency/setup check;
- one pytest result;
- preflight result if actually run;
- Edge/CDP status and account identity result;
- sanitized UI control inventory and any selector mismatch;
- confirmation that no approval, upload or publication action occurred.

The developer will implement any required code/selector corrections on GitHub. The user retains final content approval and all publish authority.
