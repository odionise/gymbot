# gymbot — Линия силы

- Read README.md and PROJECT_STATUS.md for the current contract and checks. Work in an isolated branch; preserve Telegram authentication, owner checks, recorded facts and unknown values.
- Use synthetic data and an isolated SQLite/PostgreSQL database. Production, webhook, live notifications, publication, PR creation and merging require their separately approved scope.
- Preserve the weight progression formula and phase/reentry RIR policy. Approved stage 2 (02.11.2026) clamps automatic reps to the configured range and makes deload RIR 4 take priority; reentry RIR 2.5 applies only in accumulation. New assignment, stable slot and comparable history are different identities; never merge them by name or ordinal position.
- Check backend tests, TypeScript/Vite build and affected migrations on both SQLite and PostgreSQL. Report actual passes, failures and skipped checks separately.
- The preview API is strictly read-only: authenticate without user registration, use a fresh guarded read transaction, project week decisions in memory and validate existing movement links. Never call workout creation, movement backfill or write-then-rollback from preview. Schema version remains 6; UI integration is a separate task.
- Do not add dependencies, global configuration or additional product features without agreement. Keep temporary tools/data outside Git in an owned temporary directory or ignored `.venv`.

## Visual scope

- Source read on 01.11.2026: `C:/Users/Admin/.codex/visual-style/VISUAL_STYLE.md`, approved version **4.0.0**. Read the complete available source again before visual work in a new session; outside this computer a verified versioned release is required.
- Stages 1–2 preserve gymbot's existing DESIGN.md palette, Roboto typography, density and geometry within the approved non-redesign scope. Source 4.0.0 read again on 02.11.2026. Reuse existing CSS components; no automatic migration to the analytical palette or changes to unrelated screens.
- Changes distinguish settings, replacement, history choice, target/factual RIR, saved recommendation reasons, errors and unknown values with text and existing controls. This connection does not claim that all existing screens conform to the analytical standard.
