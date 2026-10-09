# Composition and 1080p preview implementation ledger

Approved scope: manual order; AI selection across all collected candidates; Korean marketing skill; per-photo motion recommendations; actual 1080p video/audio preview; delta generation; caption/narration separation; reversible media history; Windows package compatibility.

Execution: inline. User explicitly requested implementation; no additional design approvals are needed.

Ruling: work in the shared workspace on a feature branch rather than duplicate the large local runtime/assets into a worktree. This keeps the user's executable and local media paths usable.

Tasks:
- [x] Composition models and media identity/reuse with regression tests.
- [x] Batched recommendation and bundled writing skill.
- [x] Delta generation, revisioned previews and publication.
- [x] Composition/editor/player UI.
- [x] Browser, rendering, recommendation and packaged-runtime checks.

Paid generation requires a quoted amount approved in the app. Automated tests must not purchase media.

Verification:
- `scripts/test_studio.py`: 79/79 passed, including full FFmpeg decode, two-line caption segmentation, last-frame freeze, byte-identical preview/export, uncertain submissions, recovery reservation, candidate upload concurrency and per-asset retry/restore.
- `scripts/check_studio_editor.py`: legacy editing, quote/approval locks and mobile checks passed.
- `scripts/check_composition_preview.py`: actual local motion/audio/caption playback at 1080x1920, sorting, separate caption edits, force/revert, crop correction, AI controls, desktop/mobile, zero paid requests passed.
- `scripts/evaluate_shortform.py --live --cases 10`: 10/10 live Codex photo sets passed structural, complete-sentence and selected unsupported-claim checks after tightening the skill. Independent human marketing score is not claimed.
- `scripts/evaluate_recommendation.py`: full live 17-candidate batch assessment → global five-photo selection/reasons → ordered draft passed after quota reset; zero Fish calls. The earlier subscription limit is reported explicitly by the app.
- `scripts/build_windows.py` and `scripts/check_frozen_studio.py`: refreshed portable EXE, separate working directory, bundled Codex/FFmpeg/Chromium/skill, seven-photo motion editing, preview/export and all downloads passed.
- `scripts/check_studio_package.py`: all packaged studio Python modules match current source bytecode, web/skill resources and guide match, skill/MIT notice included, and ZIP contains no stored jobs, photos, credentials or cookies. Final full suite: 79/79 passed.

Final review: fresh read-only reviewer `/root/final_review`, six Important findings; fix pass completed. No Minor findings were deferred.
- Candidate reads now finish before rereading/rechecking the current job; recovery reserves the job across asynchronous file reads/FFmpeg validation.
- Terminal failed/cancelled motion requests persist terminal state, allowing explicit retry while genuinely uncertain requests remain locked.
- Voice replacement preserves the completed old attempt, invalidates the old export and reserves the operation.
- Arbitrary photo order is accepted; complete scene moves carry their voices, while interleaved moves replace the existing visual slots and retain narration/captions.
- Selected photo and its caption follow the current order after reload.
- The editor exposes per-photo crop controls with an independent crop image and asset-specific invalidation.

Final: Ruling: interleaved photo moves retain existing scene narration/captions and reassign visual slots — this satisfies free order editing and exact selected order; UI/docs explicitly ask the user to check photo/text agreement. Cost if wrong: the user must revise the affected narration and approve only its changed voice.
Final: Ruling: actual Fish billing/idempotency, unresolved remote outcomes and a human marketing rating require external account/user evaluation — implemented quote approval and provider fixtures are verified; no paid generation was purchased. Cost if wrong: provider integration may require a follow-up after an approved real generation.
Final: Ruling: fresh packaging, playback, frozen-frame behavior and byte equality were checked by the parent’s real executable/browser/FFmpeg probes; exhaustive hostile-input fuzzing was outside this feature change, while local-token/host/path guards and invalid batch atomicity remain tested. Cost if wrong: untested hostile combinations could still need security follow-up.
Final: Ruling: excluded user-created five-photo assets/scripts remain untouched; keep this implementation ledger as review evidence in the repository instead of deleting documentation. Cost if wrong: a small documentation file remains.
