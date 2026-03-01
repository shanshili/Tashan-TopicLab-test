# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-03-01

### Added

**Backend (Resonnet 0.3.0)**

- Expert share to platform: `POST /topics/{id}/experts/{name}/share` — share topic expert to `libs/experts/topiclab_shared/`
- Moderator mode share to platform: `POST /topics/{id}/moderator-mode/share` — share custom mode to `libs/moderator_modes/topiclab_shared/`
- Topic-level moderator config: `skill_list`, `mcp_server_ids`, `model` persisted per topic
- Discussion params: `skill_list`, `mcp_server_ids`, `allowed_tools` in start-discussion request

**Frontend**

- Expert card portal menu: edit/share actions on expert cards; 「共享」shares to platform library
- Moderator mode share: 「共享到讨论方式库」dialog in TopicConfigTabs/ModeratorModeConfig; `mode_id`, `name`, `description` input
- AI discussion tab UX: rename to 「AI讨论」; shortcut button; expanded description; hide when started; nudge animation
- `topicExpertsApi.share()`, `moderatorModesApi.share()`; refetch experts list after share

**Docs**

- `docs/share-flow-sequence.md` — expert share and moderator mode share sequence diagrams
- `docs/deploy.md` — `.env.deploy.example`, nginx config, deploy workflow

### Fixed

- **Backend**: Expert share no longer returns 500 when `topiclab_shared/meta.json` does not exist (first share)
- TopNav mobile width and overflow on small viewports
- UI validation messages and input constraints

### Changed

- ExpertList/ExpertSelector: `onShare` callback; refetch after share
- ExpertGrid: show share action for non-preset experts (`source !== 'preset'`)

## [1.1.0] - 2026-02-21

### Added

**Backend (Resonnet)**

- Libs meta TTL cache with `LIBS_CACHE_TTL_SECONDS`; cache stampede protection
- `POST /libs/invalidate-cache` for hot-reload
- Search param `q` on skills/mcp/moderator-modes list endpoints
- `GET /experts/{name}/content`; `GET /experts?fields=minimal` for faster list

**Frontend**

- Mobile responsiveness: TopNav hamburger menu on small screens; responsive padding (`px-4 sm:px-6`); `viewport-fit=cover` and `safe-area-inset-*` for notched devices; TopicDetail mobile TOC; TabPanel horizontal scroll; touch target optimization (44px for reply buttons)
- `MobileSourceCategoryToc`: two-level mobile directory (source → category); source row selects, category row navigates; scroll fade hint; labels "来源" / "分类" for hierarchy
- Library grids (Expert, Skill, MCP, ModeratorMode): single-column layout on mobile; full-width cards; selected chips panel `max-h-28` with overflow scroll in embed mode; compact chip bubbles on mobile
- TopicDetail/TopicList: title and status badge on same line on all breakpoints
- TopicList: hide body paragraph when topic has no body content
- TOC alignment fix: `self-start` and `items-start` to prevent sidebar stretch; `min-w-0 overflow-x-hidden` to avoid overlap
- `libsApi.invalidateCache()`; 「刷新库」button on SkillLibrary
- `expertsApi.list(params?)`, `expertsApi.getContent(name)`; `q` param on list APIs
- ExpertList, ExpertSelector: fetch content on demand when opening detail

**Docs**

- `docs/LIBS_API_TESTS_AND_FRONTEND.md` — test coverage, frontend API usage
- `docs/LIBS_SEARCH_PERFORMANCE_AND_API_UNIFICATION.md` — performance & API unification

### Changed

- Backend README: API overview, env vars (`LIBS_CACHE_TTL_SECONDS`)
- ExpertList/ExpertSelector: no longer rely on list's skill_content; use getContent on open
- TopicList: show discussion mode and creation date
- Topic config (skills, MCP, model): persist across page reloads

## [1.0.0] - 2026-02-20

Public release.

### Added

- **Docs for open source**: Technical report in `docs/TECHNICAL_REPORT.md`; open-source README with project overview, quick start, doc index
- **Tashan logo** and explicit backend link to [Resonnet](https://github.com/TashanGKD/Resonnet)
- **English docs**: `README.en.md`, `docs/*`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`
- **Docs cleanup**: Removed obsolete design docs; merged unimplemented plans into `docs/FUTURE_PLAN.md`
- **Code contribution skill**: `.cursor/skills/code-contribution/SKILL.md` (commit convention, testing, file layout)
- **CI workflow**: `.github/workflows/ci.yml` — diff-based jobs (frontend build, backend unit/integration, Docker build), pipeline layers
