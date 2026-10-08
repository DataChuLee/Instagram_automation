# Local accommodation video studio implementation plan

Goal: photos -> Codex subscription analysis -> Fish credit estimate and approval ->
Seedance 2.0 1080p motion + 일반여성2 Drama3 -> automatic captioned 1080x1920 MP4.

Architecture: FastAPI local UI, durable per-job JSON, Codex CLI read-only structured
analysis, MCP Python OAuth client, Playwright persistent-profile Drama3 browser,
Pillow captions and FFmpeg compositor, PyInstaller Windows directory distribution.

Global constraints: no developer API keys; bind loopback only; explicit credit quote
before generation; never quietly replace Drama3 or 1080p; cache generation IDs before
polling; render-only edits never call generation; preserve original reference outputs.

Tasks:
- [x] Core types, full-bleed crop and caption preset; timing and cache validation tests.
- [ ] Subscription Codex analysis and Fish OAuth/MCP generation with persistent jobs.
- [ ] Drama3 browser selection, readiness and generation; no silent default engine.
- [x] Mixed image/video FFmpeg render and verification for variable photo counts.
- [ ] Local upload/quote/approve/render UI with caption preview and connection setup.
- [ ] Windows package, documentation, meaningful tests, browser and decode verification.

Review focus: reapproval on quote changes; interrupted submissions must not spend twice;
caption preview must match exported frames; packaged resources independent of cwd;
web login expiry must be actionable without discarding generated assets.
