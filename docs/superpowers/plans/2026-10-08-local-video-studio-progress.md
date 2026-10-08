# SDD ledger — plan: docs/superpowers/plans/2026-10-08-local-video-studio.md

Implementation started after user explicitly requested implementation of the plan.

Ruling: work in the supplied workspace — repository has an unborn master branch and
all input/reference/source files are untracked, so a worktree cannot contain the
baseline. Preserve inputs and old outputs; new app uses a separate job directory.
Cost if wrong: a later integration must explicitly add these previously untracked files.

Ruling: use existing Playwright capability for exploration — agent-browser is not
installed and the available MCP browser currently reports a busy profile. Install a
project-local Playwright runtime for the program rather than altering global browsers.
Cost if wrong: browser download adds size to the portable package.

## Implemented and verified (2026-10-08)

### Additional sources and separate exports — completed

- Existing scene script input/edit/save retained. Uploads now append before analysis;
  duplicate original content is skipped. File uploads and imported link photos share
  the 60-photo, 20MB-per-photo, 300MB-total, 300px-minimum-short-side limits.
- Program supports Yeogi domestic listing collection, a unique thumbnail gallery,
  user selection/import, lodging names and provenance in saved jobs/history.
  Shared parser and original-file validation moved to `studio/yeogi.py`; CLI remains usable.
  Browser collection is durable/restartable and shows partial failures.
- Headless public listing fetch returned HTTP 403. Full bundled Chromium in the
  normal visible-browser mode collected 66 image records / 56 unique photos without
  failures. No challenge/login bypass is added. Source browser closes after completion.
- Separate downloads: captioned/narrated final MP4, caption-free silent MP4,
  scene script TXT / timed SRT, and timeline-aligned merged MP3 narration.
  Both video branches share the same frame allocation, crop and motion inputs.
  Entire export set is staged and media fully decoded before publication.
- All 44 tests passed via `scripts/test_studio.py`. Browser feature checks passed
  selection/import, upload append, duplicates, four export cards/five downloads,
  mobile width, no JavaScript errors and legacy file availability. Existing 25-photo
  mixed-motion render and native-1080 rejection checks also passed.
- Windows folder and ZIP rebuilt successfully. Frozen executable passed from an
  unrelated cwd: upload/preview, gallery/import, saved-audio render, all downloads,
  bundled FFmpeg/Codex/Chromium and actual public listing refresh (56 unique photos).
  The earlier portable-startup blocker below is resolved by this fresh verification.
- ZIP CRC/integrity and exclusion of user data/auth inputs passed; packaged UI and
  usage instructions match source. Development server 8766 was restarted after
  confirming no active generation; new collection/import/append routes are verified.
- These additions were verified with saved audio and reference motion only. No new
  paid voice or motion generation was triggered. Account/Drama3 pricing limitations
  in the remaining external verification section still apply to new generation.

- Local FastAPI UI: upload, Codex subscription analysis integration, scene editing,
  shared Pillow caption preview/export, exact quote approval, durable jobs,
  interrupted-request protection, cached rerender and manual voice recovery.
- Paperlogy Bold bundled with OFL. Default caption Y=13 maps to center y=710px
  by screenshot interpretation; it is not a verified VLLO internal coordinate standard.
- FFmpeg export always 1080x1920, 30fps, full bleed. Actual 17-photo render and
  25-photo mixed video/photo render fully decoded. These use saved prior audio and
  a reference video fixture, not newly generated Drama3/AI motion.
- 18 dedicated tests passed, including MCP 2.x two-stream transport regression,
  exact approval, no repeated uncertain paid submission, no paid calls on rerender,
  crop/timing/schema, upload/preview and localhost/CSRF checks. JS syntax passed.
- Browser checks passed on 17 photos and mobile width with no JS error/overflow.
- Windows DPAPI roundtrip and SDK construction passed.
- Read-only live Fish connector checks: upload succeeded, Seedance 2.0 native
  1080p 9:16 4-second image-to-video quote returned 37960 credits with version
  2026-10-07.4. This is one test quote, not a fixed price and not user approval.
- Fresh final reviewer identified stale audio-download matching, bundler browser
  path and interrupted-request editing issues; these were corrected.

## Login error diagnosis and fixes

Drama3 Google security follow-up on 2026-10-09: Google rejected sign-in after the
email entry in the Playwright-launched editor. Google's official support lists
software-controlled browsers among restricted sign-in clients. Authentication now
opens installed Chrome/Edge as an ordinary process without automation or debugging
flags, in a dedicated `fish-manual` profile. The user authenticates manually and
closes that window before Fish automation opens the same browser/profile. Actual
process inspection confirmed neither flag is present. The user confirmed reaching
the Google password screen, which was previously blocked; final Fish authentication
is still user-controlled and has not been verified. All 53 tests, rebuilt package
code/static asset integrity and frozen startup/import/render/download checks pass.

Fish MCP follow-up on 2026-10-09: installed MCP 2.x `CallToolResult` exposes
`structured_content` and `is_error`, while the application still accessed the
1.x camelCase attributes. Reproduced the user's AttributeError using the actual
installed result model, then added both-version access and non-object error
handling. All 51 tests pass. Server 8766 was restarted while no jobs were active;
the actual authenticated workspace query succeeded with one workspace and
`Fish MCP 연결 완료`. This verifies MCP login/workspace retrieval, not paid generation.

Latest Drama3 Google login correction: the program previously opened beta.fish.audio.
An isolated comparison reproduced `origin_mismatch` on beta and reached Google's
account entry screen on fish.audio. Both serve the Drama3 preview editor. Changed
the editor origin to fish.audio while retaining `version=drama-3-preview`, and set
the dedicated context locale to en-US for existing English UI selectors. Credentials
were not entered in diagnostic contexts and no generation was requested.
Regression coverage now totals 45 passing tests. Restarted server 8766 and opened
the updated Drama3 browser successfully. Rebuilt the Windows EXE/ZIP; frozen smoke
checks for startup, preview, collection import, rendering and downloads passed.

The development server was originally launched in a network-restricted sandbox.
OpenAI device login and Fish browser requests were blocked there. Server 8766 was
restarted outside that environment with explicitly approved launch command.
Codex now uses official browser OAuth; the UI exposes the authorization link.
MCP 2.3 transport yields two streams; legacy three-stream unpacking was corrected.
Fish browser opens use a dedicated profile and an async opening lock.
Actual server now reports drama_open=true. Fish MCP is waiting for authorization;
ChatGPT and Fish authenticated completion have not yet been verified.
User has been asked to retry login. Never copy another profile's credentials.

## Remaining external verification and blockers

- Codex real photo analysis requires the user's program-specific ChatGPT login.
- Fish OAuth completion requires the user's browser approval. Existing Codex MCP
  authorization is separate from this program and is not copied.
- Public Drama3 UI has no confirmed pre-generation credit price. Its character
  counter is UTF-8 bytes, not an explicit quote; public code may generate two
  takes for Drama3. Do not invent an exact voice quote or silently use MCP's
  default TTS engine. Current voice quote stops safely when price is absent.
- No paid Drama3 or new AI motion generation has been run during implementation.
  Real generation status/result shapes and end-to-end rendering remain unverified.
- First portable startup smoke failed: legacy global pkg_resources vendor appdirs
  was omitted. Builder now collects pkg_resources and a new build is in progress.
  Rerun scripts/check_frozen_studio.py before treating the ZIP as usable.
- Latest source includes an explicit Fish authorization fallback link; running
  development server needs reload after pending OAuth completes or expires.

The plan is not fully complete. Do not describe the package as fully verified
automatic generation while these integration requirements remain open.
