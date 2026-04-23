# Open Source Launch Readiness Audit

Date: 2026-04-23

## Purpose

This document lists what Maverick v3 still needs before it can be published as a credible open source project.

It is intentionally strict. The goal is to prevent predictable criticism from experienced open source maintainers, security reviewers, platform engineers, package maintainers, and potential contributors.

This is not a marketing checklist. It is an engineering and governance checklist for making the repository public without looking careless, unsafe, legally ambiguous, or impossible to run.

## References Used

- Local reference: `/tmp/openclaw`
  - OpenClaw is a useful launch benchmark because it is already shaped like a serious public repository.
  - It has root community and legal files: `LICENSE`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `.mailmap`, `.env.example`.
  - It has GitHub community infrastructure: `.github/CODEOWNERS`, issue templates, pull request template, labeler config, Dependabot, CodeQL config, stale workflow, release workflows, install smoke workflow, sandbox smoke workflow, parity gates, and workflow sanity checks.
  - It has reproducibility and supply-chain signals: `pnpm-lock.yaml`, `pnpm-workspace.yaml`, package metadata, Dockerfiles, `docker-compose.yml`, `.detect-secrets.cfg`, `.secrets.baseline`, `.pre-commit-config.yaml`, markdown lint, shell lint, duplicate-code config, and release-oriented CI.
  - Its `README.md`, `CONTRIBUTING.md`, and `SECURITY.md` are written for public readers rather than internal operators.
- GitHub community health conventions:
  - license
  - README
  - contributing guide
  - code of conduct
  - security policy
  - issue and pull request templates
- OpenSSF Scorecard categories:
  - maintained
  - branch protection
  - CI tests
  - dependency update tooling
  - pinned dependencies
  - token permissions
  - security policy
  - fuzzing or equivalent robustness testing where relevant
  - static analysis
  - packaging and release discipline
- SPDX and REUSE conventions:
  - unambiguous root license
  - SPDX license identifiers
  - third-party license inventory
  - generated/vendor artifact clarity

## OpenClaw Benchmark Gap

Maverick does not need to copy OpenClaw's exact structure, but it should meet the same public-repository expectations before launch.

OpenClaw currently sets a higher bar in these concrete areas:

- **Legal clarity:** OpenClaw has a root `LICENSE`; Maverick does not.
- **Public landing:** OpenClaw's README explains the product, installation, quick start, security model, docs map, and source setup; Maverick's README is still closer to an internal scaffold.
- **Contributor path:** OpenClaw has `CONTRIBUTING.md`, issue templates, PR template, `CODEOWNERS`, labeler config, and maintainer-facing workflow conventions; Maverick has none of these at the root.
- **Security intake:** OpenClaw has a public `SECURITY.md` with reporting and trust-model language; Maverick has a security audit but no standard vulnerability intake path.
- **CI credibility:** OpenClaw has many GitHub Actions workflows for CI, CodeQL, install smoke, sandbox smoke, release checks, docs sync, release publishing, stale issue management, and workflow sanity; Maverick currently has no `.github/workflows/`.
- **Supply-chain hygiene:** OpenClaw has Dependabot, lockfiles, secret scanning configuration, pre-commit configuration, lint configs, Dockerfiles, and release workflows; Maverick has scattered app lockfiles but no unified supply-chain story.
- **Local setup:** OpenClaw has `.env.example`, Dockerfiles, and `docker-compose.yml`; Maverick needs a verified clean-clone setup path, environment reference, and demo deployment path.
- **Release maturity:** OpenClaw has `CHANGELOG.md` and release automation; Maverick has inconsistent version metadata and no release policy.
- **Docs posture:** OpenClaw has public docs structure and generated docs conventions; Maverick has strong architecture docs but needs public navigation, glossary, tutorial flow, and operator docs.
- **Repository hygiene:** OpenClaw has lint and duplicate-code config, pre-commit hooks, secret baselines, shell/markdown checks, and package workspace structure; Maverick needs equivalent automation or documented alternatives.

For launch, the practical goal is not "be as large as OpenClaw." The goal is that an experienced reviewer cannot immediately object that Maverick lacks the basic legal, security, setup, CI, and contributor surfaces that OpenClaw already exposes.

## Current Verdict

Maverick v3 is not ready to be published as open source.

The main blockers are:

- no root `LICENSE`
- inconsistent package licensing metadata
- no public contributor workflow
- no security disclosure policy
- no CI
- no reproducible setup path for external users
- public-facing security issues already documented in `SECURITY_AUDIT.md`
- local/private deployment assumptions in docs and configs
- committed build artifacts without a documented policy
- possible private branding and role content that needs legal/product review
- no dependency, SBOM, provenance, or release process
- no clear statement of project scope, maturity, threat model, or production readiness

The repository can be made publishable, but it needs a dedicated open-source hardening pass before release.

## Release Gate

Do not publish the repository publicly until all P0 items are complete.

Do not announce the project broadly until all P1 items are complete.

P2 items can follow shortly after launch if they are clearly tracked in public issues.

## P0: Must Fix Before Public Repository

### 1. Choose and add the actual open source license

Current state:

- There is no root `LICENSE` file.
- Root `package.json` says `"license": "ISC"`.
- `pyproject.toml` has no license metadata.
- App package files generally omit license metadata and many are marked `"private": true`.
- The repo currently cannot be considered open source in the practical or legal sense until a license is present.

Required work:

- Decide the license:
  - Apache-2.0 if patent grant and corporate use clarity are important.
  - MIT if minimal permissive licensing is preferred.
  - AGPL-3.0 only if network copyleft is explicitly desired and commercially acceptable.
  - Avoid custom licenses unless legal counsel owns the decision.
- Add root `LICENSE`.
- Add `NOTICE` if Apache-2.0 or if attribution obligations require it.
- Add license metadata to `pyproject.toml`.
- Align root `package.json` license with the chosen license.
- Decide whether app packages remain private implementation packages or publishable npm packages.
- If apps remain private, document that `"private": true` means "not published to npm", not "not open source".
- Add SPDX headers or a REUSE-compatible policy.
- Add a third-party license inventory for Python and npm dependencies.

Exit criteria:

- A reviewer can determine the legal permissions within 30 seconds from the repository root.
- `package.json`, `pyproject.toml`, README, and app package metadata do not contradict the root license.

### 2. Remove or clearly quarantine private/local state and generated leftovers

Current state:

- `.codex` is tracked as an empty root file.
- `.maverick/`, `logs/`, `tmp/`, `output/`, and `workspaces/` exist locally.
- `tmp/cleanup-backups/*.sqlite` exists locally.
- `tests/__pycache__/` and `scripts/__pycache__/` exist locally.
- `.maverick/local-state/secrets/` exists locally and is sensitive by design.
- Git status shows many generated frontend dist changes and untracked package files in the current worktree.
- There is a `SECURITY_AUDIT.md` describing sensitive local-state risks.

Required work:

- Ensure no local state, secrets, logs, SQLite backups, runtime transcripts, personal workspace files, or `.codex` artifacts are tracked.
- Remove generated Python cache directories from the working tree.
- Decide whether `workspaces/` should contain only `.gitkeep` placeholders or no committed workspace content at all.
- Add or tighten `.gitignore` for:
  - `.codex`
  - `.maverick/`
  - `.pytest_cache/`
  - `__pycache__/`
  - `*.pyc`
  - `tmp/`
  - `logs/`
  - `output/`
  - local SQLite backups
  - runtime transcripts
  - provider homes
  - local OAuth/token files
- Run a secret scan before publishing:
  - gitleaks or equivalent
  - trufflehog or equivalent
  - GitHub secret scanning after publication
- If any real secret was ever committed, rotate it before publication.

Exit criteria:

- `git ls-files` contains no local state, secrets, personal data, runtime output, test cache, or machine-specific files.
- A fresh clone does not include private workspace data.

### 3. Resolve the security posture before claiming production readiness

Current state:

- `SECURITY_AUDIT.md` says Maverick v3 is not production-safe for sensitive data on an internet-connected host.
- Critical issues include plaintext local secrets, weak runtime token model, missing CSRF protection, same-origin app frontend isolation problems, unauthenticated app event WebSocket, app backends running with platform privileges, and recovery automation risks.

Required work:

- Keep `SECURITY_AUDIT.md` public if the repo is published before all security work is complete.
- Add a clear README badge or warning:
  - "Experimental"
  - "Not production ready"
  - "Do not expose to the public internet with real secrets"
- Create a public security roadmap from `SECURITY_AUDIT.md`.
- Fix or explicitly gate at least the following before any production claim:
  - no plaintext secret store in production
  - no default signing secrets
  - runtime tokens bound to persisted session authority and expiration
  - CSRF protection for cookie-authenticated unsafe methods
  - authenticated app event WebSocket
  - app frontend isolation model
  - sandboxed app backend and lifecycle hook execution
  - restrictive local-state file permissions
  - recovery agent full-access safety policy

Exit criteria:

- Public README and docs do not overstate security.
- Known P0 security issues are either fixed or prominently documented as launch blockers.

### 4. Create `SECURITY.md`

Current state:

- There is a detailed `SECURITY_AUDIT.md`.
- There is no standard `SECURITY.md`.

Required work:

- Add `SECURITY.md` with:
  - supported versions
  - vulnerability reporting email or private advisory process
  - expected response timeline
  - what not to report publicly
  - safe harbor language if desired
  - statement about experimental status
  - secret handling expectations for reports
- If GitHub is used, enable private vulnerability reporting.

Exit criteria:

- Researchers know how to report vulnerabilities without opening public issues.

### 5. Add a credible README for external users

Current state:

- `README.md` is a short internal scaffold description.
- It references `local-skills/`, but current product skills now live under `apps/skills/skills/` according to `AGENTS.md`.
- It does not explain what Maverick is in user terms.
- It does not provide a verified fresh-clone setup.
- It does not state maturity, license, security status, architecture overview, or limitations.

Required work:

- Rewrite README for public readers:
  - one-sentence product definition
  - what problem Maverick solves
  - status and maturity
  - screenshot or demo GIF if available
  - supported operating systems
  - prerequisites
  - installation
  - quick start from clean clone
  - how to run tests
  - how to run locally
  - how to create a workspace
  - how to use an agent
  - how apps work
  - how security/isolation works at a high level
  - what is not ready
  - where to find architecture docs
  - where to report issues
  - license
- Remove stale references to `local-skills/`.
- Avoid private deployment URLs as the primary setup path.
- Add "do not use for production secrets yet" if security issues remain.

Exit criteria:

- A developer who has never seen Maverick can understand and run the project without private context.

### 6. Provide a reproducible clean setup path

Current state:

- `pyproject.toml` lists only `uvicorn[standard]`.
- The code likely uses more than that across apps and tests.
- There is no root `requirements.txt`, lockfile, `uv.lock`, Poetry config, or pip-tools output.
- There is no Dockerfile or docker-compose for a full local stack.
- There is no documented MongoDB setup despite README saying MongoDB is the default control-plane persistence backend.
- Many app frontends have independent package files.

Required work:

- Decide supported setup mode:
  - local Python + Node + MongoDB
  - Docker Compose
  - devcontainer
  - all of the above
- Add exact prerequisites:
  - Python version
  - Node version
  - npm version
  - MongoDB or local JSON bootstrap mode
  - bubblewrap requirement for Linux sandboxing
  - Codex CLI requirement if agents need Codex
- Add one verified bootstrap command sequence.
- Add dependency lock strategy:
  - Python lockfile
  - npm lockfiles for every frontend app that is built from source
- Add a script or Makefile:
  - install dependencies
  - run backend
  - run frontend builds
  - run tests
  - clean generated artifacts
- Add sample `.env.example` with safe placeholders.
- Document required environment variables and defaults.

Exit criteria:

- A fresh clone can be installed and booted by following public docs.
- No private machine paths or hidden services are required.

### 7. Establish CI before publishing

Current state:

- No `.github/workflows/` exists.
- Root `package.json` test script fails intentionally.
- There is no automated lint, test, build, security, or docs check.

Required work:

- Add GitHub Actions workflows:
  - Python unit tests
  - Python compileall
  - unused import check
  - app contract validation
  - frontend builds for apps with source
  - frontend tests for apps that have tests
  - clean install smoke test from a fresh clone
  - sandbox smoke test for workspace read/write boundaries
  - CodeQL or equivalent static security analysis
  - secret scan
  - dependency audit
  - markdown/link check
  - license check
  - workflow sanity check for GitHub Actions syntax and permissions
  - release dry-run check
- Use least-privilege GitHub token permissions.
- Cache dependencies safely.
- Fail on uncommitted generated changes if build outputs are committed.
- Add branch protection once hosted.

Exit criteria:

- Every PR gets a meaningful pass/fail signal.
- Main branch cannot silently break fresh-clone setup.

### 8. Decide and document generated artifact policy

Current state:

- Many `apps/*/frontend/dist/` assets are committed.
- Some app packages only verify prebuilt `frontend/dist/index.html`.
- Other apps build from TypeScript/Vite source.
- `.gitignore` ignores `dist/` globally but explicitly unignores `apps/*/frontend/dist/`.

Required work:

- Decide whether committed dist is policy:
  - Option A: commit dist because built-in apps must mount without a frontend build step.
  - Option B: do not commit dist and require build during install/release.
- If committing dist:
  - document why
  - ensure every dist file is reproducible
  - CI must verify source build matches committed dist
  - include source maps policy
  - avoid stale hashed assets
- If not committing dist:
  - remove committed dist
  - update app hosting to build or load release artifacts
  - document build requirements
- Ensure package lockfiles exist for all source-built frontend apps.

Exit criteria:

- A contributor understands whether to edit source, dist, or both.
- Reviewers do not see generated churn without explanation.

### 9. Remove private branding and product-specific content that should not be open

Current state:

- Several files reference `versy`, `maverick3.versy.ai`, and personal or company-specific roles.
- App role templates include names such as `piero-linkedin-content-os`, `versy-design-analyst`, and `versy-media-creative-direction`.
- CSS includes `versyBrandTokens.css`.
- Docs include deployment references to `maverick3.versy.ai`.

Required work:

- Decide what brand is being open sourced:
  - Maverick as standalone open source project
  - Versy-branded product source
  - dual project/product branding
- Remove or rename private/person-specific roles unless they are intentionally part of the public demo.
- Remove private deployment hostnames from generic docs or move them to deployment examples.
- Review all docs for internal company language.
- Review all app contracts for publisher names.
- Ensure logo, name, and trademark rights are explicit.
- Add trademark policy if "Maverick" or "Versy" is protected.

Exit criteria:

- Public readers do not feel they are seeing accidental internal company material.
- The repository has a clear brand and trademark position.

### 10. Add contributor governance and community files

Current state:

- No `CONTRIBUTING.md`.
- No `CODE_OF_CONDUCT.md`.
- No `GOVERNANCE.md`.
- No `SUPPORT.md`.
- No issue templates.
- No PR template.

Required work:

- Add `CONTRIBUTING.md`:
  - project status
  - development setup
  - coding standards
  - test expectations
  - documentation expectations
  - architecture decision process
  - how to add apps
  - how to add core features
  - how to report bugs
- Add `CODE_OF_CONDUCT.md`.
- Add `GOVERNANCE.md`:
  - maintainer roles
  - decision authority
  - review policy
  - release authority
  - security embargo authority
- Add `SUPPORT.md`:
  - community support channels
  - what maintainers will not support
  - commercial support if any
- Add `.github/ISSUE_TEMPLATE/`:
  - bug report
  - feature request
  - security notice redirect
  - app compatibility report
  - documentation issue
- Add `.github/pull_request_template.md`.
- Add labels and triage policy.

Exit criteria:

- Contributors know how to participate without private access or Slack context.

## P1: Strongly Recommended Before Announcement

### 11. Create an open source roadmap

Current state:

- `IMPLEMENTATION_TASKLIST.md` exists, but it is internal and phase-heavy.
- It currently appears heavily edited in the worktree and may have lost older phase detail.
- It is not shaped for external contributors.

Required work:

- Create `ROADMAP.md`.
- Separate:
  - done
  - in progress
  - planned
  - not planned
  - help wanted
- Include maturity bands:
  - core runtime
  - workspace isolation
  - app SDK
  - built-in apps
  - security hardening
  - deployment
  - documentation
- Convert internal phase tasks into external milestones.
- Mark security blockers prominently.

Exit criteria:

- External contributors can find meaningful work without reading internal implementation history.

### 12. Add architecture decision records

Current state:

- Architecture docs are detailed, but there is no ADR index.
- Major decisions are embedded in long documents.

Required work:

- Add `docs/adr/`.
- Add ADRs for:
  - workspace root isolation
  - app contract model
  - app source distribution model
  - committed dist policy
  - runtime provider abstraction
  - Codex app-server integration
  - sandbox and bubblewrap dependency
  - secret storage model
  - app frontend isolation model
  - licensing choice
- Use a short stable template:
  - status
  - context
  - decision
  - consequences

Exit criteria:

- New contributors can understand why the repo looks this way.

### 13. Add a threat model document

Current state:

- `SECURITY_AUDIT.md` contains findings, but there is no compact threat model.

Required work:

- Add `docs/security/threat_model.md`.
- Define trust boundaries:
  - browser user
  - workspace user
  - app frontend
  - app backend
  - workspace-local app source
  - store app source
  - runtime agent
  - provider subprocess
  - platform core
  - local host
  - external OAuth providers
- Define attacker capabilities.
- Define non-goals.
- Define accepted risks for experimental releases.

Exit criteria:

- Security reviewers can evaluate the design without reverse-engineering assumptions.

### 14. Add dependency and supply-chain hygiene

Current state:

- Python dependencies are underdeclared.
- npm dependencies are scattered across app packages.
- Some apps have lockfiles; others appear to have package files without lockfiles.
- No SBOM generation exists.
- No Dependabot/Renovate config exists.
- No Scorecard workflow exists.

Required work:

- Inventory Python imports and declare all runtime/test dependencies.
- Add a Python lockfile.
- Ensure every npm package has a lockfile or is intentionally not source-built.
- Add Dependabot or Renovate.
- Add `npm audit` or a more reliable audit gate.
- Add `pip-audit` or equivalent.
- Add secret-scanning configuration:
  - gitleaks, detect-secrets, or equivalent
  - documented baseline policy
  - no committed baseline entries that mask real secrets
- Add pre-commit hooks for fast local checks.
- Add SBOM generation:
  - CycloneDX or SPDX
  - Python and npm components
- Add provenance for releases:
  - signed tags
  - artifact checksums
  - SLSA-style provenance if feasible

Exit criteria:

- Consumers can evaluate dependency risk and reproduce releases.

### 15. Add release process and versioning policy

Current state:

- Root `package.json` version is `1.0.0`.
- `pyproject.toml` version is `0.1.0`.
- App package versions vary.
- No changelog exists.
- No release tags or release notes policy is documented.

Required work:

- Decide semantic versioning policy.
- Align version metadata across Python, root package, and app packages.
- Add `CHANGELOG.md`.
- Add release checklist:
  - tests
  - frontend builds
  - security scan
  - dependency audit
  - docs update
  - migration notes
  - tag
  - artifact checksums
- Decide whether built-in apps version independently or with core.
- Add migration policy for workspace/app data.

Exit criteria:

- A user can tell what changed and whether an upgrade is safe.

### 16. Add public deployment documentation

Current state:

- Systemd and nginx files exist under `scripts/deploy/`.
- They reference current hosted deployment assumptions.
- There is no general deployment guide.

Required work:

- Add `docs/deployment/`.
- Document:
  - local development
  - single-machine demo
  - production warning
  - systemd deployment
  - nginx reverse proxy
  - TLS
  - environment variables
  - data directories
  - backup/restore
  - log rotation
  - secret backend
  - sandbox requirements
  - hardening checklist
- Separate demo deployment from production deployment.
- Do not use private hostnames as defaults.

Exit criteria:

- Operators can run a demo without exposing themselves to known production risks.

### 17. Clarify runtime provider requirements

Current state:

- Maverick currently uses Codex as the concrete provider backend.
- Docs say provider-agnostic, but setup does not clearly explain what is required to run agents.
- Codex-specific sandbox behavior is actively evolving.

Required work:

- Document Codex CLI requirement:
  - installation
  - authentication
  - supported versions
  - sandbox behavior
  - how `rg` is made available
  - known limitations
- Document what works without Codex.
- Document future provider extension points.
- Add provider health check docs.

Exit criteria:

- A user understands whether agents will work on their machine before they install.

### 18. Add database and persistence documentation

Current state:

- Docs mention MongoDB and local JSON bootstrap persistence.
- It is unclear which mode external users should use.
- Security audit says local JSON is not production safe.

Required work:

- Document persistence modes:
  - local JSON bootstrap
  - MongoDB
  - future adapters
- Document exact state locations.
- Document backup and restore.
- Document data retention.
- Document how to reset local state.
- Document how to migrate workspace data.
- Document file permissions.

Exit criteria:

- Users do not accidentally store secrets or business data in unsafe locations.

### 19. Add API documentation

Current state:

- Core API routes exist but no public API reference was found.
- App backend actions are contract-driven but not exposed as public docs.

Required work:

- Add OpenAPI generation or manual API docs.
- Document auth model.
- Document workspace APIs.
- Document app hosting APIs.
- Document runtime APIs.
- Document app backend call pattern.
- Document error format.
- Document WebSocket protocols.

Exit criteria:

- Integrators can build clients without reading source.

### 20. Add app developer documentation polish

Current state:

- `docs/app-sdk/` exists and is promising.
- The SDK docs need to be verified against a fresh clone.
- Some app creation docs may depend on live Maverick runtime behavior.

Required work:

- Run every SDK tutorial from scratch.
- Add screenshots or expected command output.
- Add "common failures" section.
- Add app contract examples.
- Add how to test app hooks, CLI, MCP, and frontend.
- Add app publishing/forking guidance.
- Add security rules for app authors.

Exit criteria:

- A third-party developer can create an app without maintainer help.

## P2: Quality Bar for a Serious Public Project

### 21. Add static analysis and formatting

Current state:

- There is a custom unused import checker.
- No standard Python formatter/linter config was found.
- No TypeScript lint config was found.

Required work:

- Add Ruff or equivalent.
- Add Black or decide Ruff formatting.
- Add mypy or pyright if type checking is realistic.
- Add ESLint for frontend packages.
- Add Prettier or explicit formatting rules.
- Add `editorconfig`.
- Add pre-commit hooks.
- Add markdown lint.
- Add shell lint for deploy/setup scripts.
- Add duplicate-code detection if app packages continue to share large frontend/backend patterns.

Exit criteria:

- Style disagreements are automated, not debated in PRs.

### 22. Add test taxonomy and coverage reporting

Current state:

- Many unit tests exist.
- No coverage report or test matrix is documented.
- Some tests likely require local service assumptions.

Required work:

- Document test groups:
  - unit
  - integration
  - browser/frontend
  - sandbox
  - app contract
  - security
  - e2e
- Add coverage reporting for Python.
- Add coverage reporting for frontend packages that have tests.
- Mark tests that require:
  - bubblewrap
  - Codex
  - MongoDB
  - network
  - systemd
- Add smoke tests for fresh install.

Exit criteria:

- Contributors know which tests to run for their change.

### 23. Add browser and accessibility checks

Current state:

- Frontend apps exist.
- No Playwright/Cypress/a11y workflow was found.

Required work:

- Add browser smoke tests for:
  - login
  - workspace switch
  - app mounting
  - chat send
  - app store listing
  - developer kit app creation
- Add accessibility checks:
  - keyboard navigation
  - labels
  - color contrast
  - focus states
  - reduced motion
- Add screenshot regression checks for core shell.

Exit criteria:

- Public users do not immediately hit broken UI paths.

### 24. Add documentation quality checks

Current state:

- Docs are extensive but not organized as public docs.
- No link checker or docs build exists.

Required work:

- Add docs index.
- Add markdown lint.
- Add link checker.
- Add docs site if desired:
  - MkDocs
  - Docusaurus
  - VitePress
- Add diagrams where architecture is complex.
- Add glossary:
  - workspace
  - app
  - app contract
  - runtime
  - provider
  - agent
  - skill
  - widget
  - MCP
  - CLI surface

Exit criteria:

- New readers can navigate docs without reading every architecture file.

### 25. Add examples and demo data

Current state:

- Built-in apps exist.
- Workspaces may contain local development/demo data, but public-safe examples are not curated.

Required work:

- Add `examples/`.
- Add a minimal demo workspace seed with fake data only.
- Add example app built with SDK.
- Add example agent definition.
- Add example skill.
- Add example export/import flow.
- Add screenshots.
- Add demo reset command.

Exit criteria:

- Users can see value quickly without connecting real accounts or secrets.

### 26. Add public issue roadmap labels

Required labels:

- `good first issue`
- `help wanted`
- `security`
- `docs`
- `frontend`
- `backend`
- `runtime`
- `apps`
- `app-sdk`
- `workspace-isolation`
- `needs reproduction`
- `breaking change`
- `blocked`

Exit criteria:

- Maintainers can triage public traffic consistently.

## Security-Specific Launch Checklist

### Authentication and sessions

- Remove all default admin credentials from production paths.
- Require explicit admin bootstrap flow.
- Document local demo credentials only in demo docs.
- Add password policy.
- Add session expiration.
- Add session revocation.
- Add secure cookie settings:
  - `HttpOnly`
  - `Secure`
  - `SameSite`
  - path scoping
- Add CSRF protection.
- Add login rate limiting.
- Add audit log for login and admin actions.

### Runtime and agent isolation

- Keep non-default workspaces sandbox-only.
- Verify read and write boundaries in CI if bubblewrap is available.
- Fail closed if sandbox cannot initialize.
- Document default workspace full-access risk.
- Add runtime token expiration and revocation.
- Bind runtime token to persisted runtime session.
- Do not trust runtime-provided `effective_mode`.
- Add tests for forged runtime tokens.
- Add tests for runtime attempts to read:
  - repo root
  - `.maverick`
  - `apps/`
  - `core/`
  - another workspace
  - operator home

### App isolation

- Run app backends and hooks in a sandbox.
- Do not allow workspace-local app code to import platform internals by default.
- Define trusted built-in app profile versus untrusted workspace app profile.
- Add app frontend sandboxing or per-app origin isolation.
- Add CSP.
- Add postMessage origin checks.
- Add widget context token expiration and audience binding.

### Secrets

- Do not store raw secrets in local JSON for production.
- Add external secret backend or encrypted local backend.
- Rotate any real secrets used during development.
- Add redaction for logs, runtime events, app responses, and frontend payloads.
- Add tests that secrets do not appear in:
  - HTTP responses
  - runtime events
  - exported workspace archives
  - app-owned data
  - logs

### Network and deployment

- Remove private deployment hostnames from default configs.
- Add TLS documentation.
- Add security headers:
  - CSP
  - HSTS
  - X-Content-Type-Options
  - Referrer-Policy
  - Permissions-Policy
  - frame controls
- Add reverse proxy hardening.
- Add upload limits.
- Add request body limits.
- Add WebSocket auth checks.
- Add CORS policy.

### Supply chain

- Add lockfiles.
- Add dependency update bot.
- Add vulnerability scans.
- Add SBOM.
- Add signed releases.
- Add branch protection.
- Add least-privilege workflow permissions.
- Pin GitHub Actions by SHA if high assurance is desired.

## Legal and Licensing Checklist

### Repository license

- Add root license.
- Add SPDX license metadata.
- Add license field to Python metadata.
- Align npm metadata.
- Add copyright owner.
- Decide if contributors license under inbound=outbound.
- Decide whether CLA or DCO is required.

### Third-party dependencies

- Generate dependency license report.
- Review Python dependencies.
- Review npm dependencies.
- Review committed generated bundles for included third-party notices.
- Review assets:
  - logos
  - icons
  - fonts
  - images
  - screenshots
- Review role and skill content for copied proprietary prompts or private client material.

### Trademark and naming

- Decide who owns "Maverick".
- Decide whether "Versy" appears in the open source project.
- Add trademark notice if needed.
- Document allowed use of logos and names.

### AI-generated content

- Decide policy for AI-generated code and docs.
- Document contributor certification if needed.
- Add provenance expectation for large generated assets.

## Repository Hygiene Checklist

### Root files to add

- `LICENSE`
- `NOTICE` if needed
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `SUPPORT.md`
- `GOVERNANCE.md`
- `CHANGELOG.md`
- `ROADMAP.md`
- `.editorconfig`
- `.env.example`
- `.github/pull_request_template.md`
- `.github/ISSUE_TEMPLATE/*.md`
- `.github/workflows/*.yml`
- `.github/dependabot.yml` or Renovate config
- `.mailmap`
- `.pre-commit-config.yaml`
- `.detect-secrets.cfg` or equivalent scanner config
- `.markdownlint-cli2.jsonc` or equivalent markdown lint config
- `.shellcheckrc` if shell scripts remain part of setup/deploy
- duplicate-code config if generated or copied frontend code becomes hard to review

### Root files to review

- `README.md`
- `AGENTS.md`
- `IMPLEMENTATION_TASKLIST.md`
- `SECURITY_AUDIT.md`
- `package.json`
- `pyproject.toml`
- `.gitignore`

### Files and directories to remove before public release

- `.codex` unless there is a documented reason to keep it
- local `.maverick/`
- local `logs/`
- local `tmp/`
- local `output/`
- Python `__pycache__/`
- local SQLite backup files
- any committed workspace data
- any private deployment state

### Git history concerns

- If secrets were ever committed, rotating secrets is mandatory.
- If private client data was ever committed, decide whether history rewrite is required before publication.
- If generated binaries or large assets are in history, decide whether to keep, Git LFS, or purge.
- If the repo has internal commit messages, review before making public.

## Packaging Checklist

### Python

- Add complete dependency list.
- Add optional dependency groups:
  - `dev`
  - `test`
  - `docs`
  - `security`
- Add package classifiers.
- Add license metadata.
- Add Python version matrix.
- Add console script docs.
- Decide whether `core/` is installable package or source-run only.

### Node/frontends

- Decide monorepo package manager:
  - npm workspaces
  - pnpm
  - yarn
  - current independent packages
- Add root scripts for common tasks.
- Ensure all apps with source have lockfiles.
- Ensure all built-in app builds are reproducible.
- Decide publish/private metadata.

### Containers

- Add Dockerfile for demo.
- Add Docker Compose for local stack if using MongoDB.
- Add non-root container user.
- Add healthcheck.
- Add volume docs.
- Add production warning if container is demo-only.

## Documentation Checklist

### User docs

- What is Maverick?
- Why use it?
- Current status.
- Supported platforms.
- Quick start.
- Screenshots.
- Demo walkthrough.
- Common errors.
- FAQ.

### Operator docs

- Installation.
- Configuration.
- Environment variables.
- Persistence.
- Backup and restore.
- Upgrade.
- Security hardening.
- Observability.
- Logs.
- Disaster recovery.

### Developer docs

- Architecture overview.
- App contract model.
- App SDK.
- Runtime provider model.
- Workspace isolation.
- Testing.
- Contribution flow.
- Release flow.

### API docs

- HTTP APIs.
- WebSocket APIs.
- CLI.
- MCP tools.
- App backend action contract.
- Error model.

## Product and Positioning Checklist

### Scope statement

Maverick needs a concise public scope statement. Suggested shape:

> Maverick is a workspace-isolated AI operating environment for building, running, and extending agent-powered apps.

Then clarify:

- It is not a generic chatbot wrapper.
- It is not a hosted SaaS by default.
- It is not production-safe for untrusted apps until the security roadmap is complete.
- It is a clean v3 rebuild, not a v2 compatibility layer.

### Audience statement

Define primary audience:

- agent platform builders
- developers building workspace apps
- teams experimenting with local AI operating systems
- security-conscious users only after hardening is complete

### Non-goals

Document:

- no v2 compatibility guarantee
- no production multi-tenant guarantee yet
- no guarantee that untrusted third-party apps are safe yet
- no cloud service included by default
- no support promise outside documented channels

## Criticism Preemption Checklist

These are predictable criticisms from experienced open source reviewers.

### "There is no license, so this is not open source."

Fix:

- Add root license before publication.

### "The README does not tell me how to run it."

Fix:

- Add verified fresh-clone quick start.

### "The security audit says it is unsafe."

Fix:

- Keep the warning visible.
- Do not claim production readiness.
- Publish a security roadmap.

### "Why are built assets committed?"

Fix:

- Document generated artifact policy.
- Add CI reproducibility check.

### "Why are packages private?"

Fix:

- Explain that apps are not npm-published packages, or remove `private` where appropriate.

### "Where is CI?"

Fix:

- Add workflows before public launch.

### "Where do I report vulnerabilities?"

Fix:

- Add `SECURITY.md`.

### "This looks like a company internal repo."

Fix:

- Remove private names, hostnames, and role content.
- Clarify branding.

### "This is impossible to review because docs are huge."

Fix:

- Add docs index, glossary, and ADRs.

### "The dependency story is unsafe."

Fix:

- Add lockfiles, audits, SBOM, update bot.

### "The app sandbox model is not ready."

Fix:

- Document current trust boundary honestly.
- Prioritize app backend/hook sandboxing.

### "The project has no governance."

Fix:

- Add governance and contribution docs.

## Suggested Work Breakdown

### Sprint 1: Legal and repository hygiene

- Choose license.
- Add root community files.
- Remove private/local artifacts.
- Refresh README.
- Add `.env.example`.
- Add root setup docs.

### Sprint 2: CI and reproducibility

- Add Python CI.
- Add frontend CI.
- Add app contract validation.
- Add dependency audits.
- Add generated dist policy check.

### Sprint 3: Security posture

- Convert `SECURITY_AUDIT.md` into public security roadmap.
- Add `SECURITY.md`.
- Fix default secrets.
- Fix runtime token authority checks.
- Add CSRF protection.
- Authenticate app event WebSocket.

### Sprint 4: Public docs and examples

- Add docs index.
- Add quick start.
- Add app SDK tutorial.
- Add example app.
- Add screenshots.
- Add glossary.

### Sprint 5: Release process

- Add changelog.
- Add release checklist.
- Add version policy.
- Add SBOM.
- Add signed release process.

## Minimum Public Launch Definition

Maverick can be made public as an experimental open source project when all of the following are true:

- Root `LICENSE` exists and metadata is aligned.
- `README.md` has a verified fresh-clone quick start.
- `SECURITY.md` exists.
- Known production-unsafety is clearly disclosed.
- No secrets, local state, or private data are tracked.
- CI runs unit tests and basic builds.
- Dependency install path is documented and reproducible.
- Branding/private content has been reviewed.
- Issue and PR templates exist.
- A roadmap tells contributors what help is useful.

Maverick can be announced more broadly only when:

- P0 security issues are either fixed or very clearly scoped out of the release.
- CI covers core runtime, app contracts, and primary frontends.
- Generated artifact policy is enforced.
- Dependency audit and update workflow exist.
- Contribution workflow is documented.
- A demo path works from a clean clone.

## Open Questions

- Which license should Maverick use?
- Is the public project named Maverick, Versy Maverick, or something else?
- Are built-in apps part of the same open source license?
- Are app role templates intended to be public?
- Should committed frontend dist remain part of source control?
- Is the first public release source-only, demo-only, or operator-installable?
- Will there be a hosted SaaS counterpart, and if so how is it branded?
- Will contributors need a CLA, DCO, or neither?
- What security issues must be fixed before any public demo?
- Should `SECURITY_AUDIT.md` remain public as-is or be converted into a security roadmap plus detailed internal tracker?
