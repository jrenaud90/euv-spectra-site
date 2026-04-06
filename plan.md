# Pegasus Remediation Plan

Date: 2026-04-06

Purpose: convert the major issues from [report.md](report.md) into an implementation plan that can be executed in stages without destabilizing the deployed app.

## Priority Order

1. Stabilize application bootstrap and session behavior.
2. Remove security-sensitive configuration from source.
3. Make error handling and logging production-safe.
4. Reduce latency and fragility in external catalog lookups.
5. Remove production/test coupling and API inconsistencies.
6. Add test coverage before larger refactors.

## Phase 1: Bootstrap And Session Consistency

Goal: make Pegasus run through one clearly defined Flask initialization path with one consistent session model.

Todo:

- [x] Choose a single runtime bootstrap path and document it.
- [x] Merge `app.py`, `euv_spectra_app/extensions.py`, and `euv_spectra_app/__init__.py` into one coherent app initialization strategy.
- [x] Remove dead or duplicate app construction code.
- [x] Ensure `SECRET_KEY`, proxy handling, cache, mail, Mongo, and blueprints are all initialized in the supported runtime path.
- [x] Either initialize `Flask-Session` in the real runtime path or remove the unused server-side session config.
- [x] Audit all `session[...]` usage and reduce stored payload size where practical.
- [x] Verify the modal flow and results flow still work across multiple requests.

Exit criteria:

- Only one supported Flask app bootstrap path remains.
- Session behavior matches the actual configuration.
- No route relies on the unused bootstrap path.

## Phase 2: Security And Secret Hygiene

Goal: remove embedded secrets from source and reduce accidental exposure.

Todo:

- [x] Remove hardcoded Flask Monitoring Dashboard credentials and token from `euv_spectra_app/config.cfg`.
- [x] Move dashboard auth settings to environment variables, or disable the dashboard in production.
- [ ] Rotate any credentials that were checked into source.
- [x] Confirm `.env.example` reflects the supported production configuration without exposing live values.
- [x] Review admin auth configuration and document the expected deployment method for the public key.
- [x] Review whether any other static config files contain secrets, tokens, or example values that look real.

Exit criteria:

- No live secrets remain in repository-tracked Pegasus files.
- Dashboard auth is either safely configured or explicitly disabled.

## Phase 3: Error Handling And Logging

Goal: make failures explicit, typed, and observable without leaking internal details.

Todo:

- [x] Replace broad `except:` and `except Exception` blocks in critical request paths with narrower exception handling.
- [x] Replace string-based error returns with explicit exceptions or structured result objects in the main lookup/model-selection flow.
- [x] Introduce a small application error model for catalog lookup, conversion, and database selection failures.
- [x] Replace `print()` debugging with structured logging using Python `logging` in the request flow.
- [x] Remove or downgrade logs that dump full object state, flux values, or internal stack details during normal requests.
- [x] Standardize user-facing error messages so internal details are not exposed in redirects or rendered pages.

Exit criteria:

- Critical helpers no longer use string-returned error states.
- Logs are leveled and production-appropriate.
- User-visible errors are stable and non-internal.

## Phase 4: External Lookup Performance And Reliability

Goal: reduce request latency and limit dependence on slow third-party services.

Todo:

- [x] Remove the per-request full NEA hostname fetch used for input normalization.
- [x] Cache or memoize high-value external lookups where repeated searches are common.
- [x] Add explicit timeouts and fallback handling around SIMBAD, NEA, and MAST calls.
- [x] Review whether retries should exist for transient external failures.
- [x] Separate external lookup orchestration from route/controller logic.
- [x] Measure the before/after latency of the common name-search flow.

Measured sample:

- Before health-check caching: one `GJ 338 B` lookup completed in about `16.369s` in the running container.
- After hostname caching, retry helpers, and cached health checks: two back-to-back `GJ 338 B` lookups completed in about `7.112s` and `8.516s`.

Exit criteria:

- Search requests no longer perform obviously unnecessary remote pre-queries.
- External service failures degrade more gracefully.

## Phase 5: Code Consolidation And Product Cleanup

Goal: reduce duplication and remove production behavior that depends on test or legacy code.

Todo:

- [ ] Consolidate overlapping astronomy-query logic between `models.py` and `helpers_astroquery.py`.
- [ ] Use `models.py` as the canonical astronomy-query path and retire the overlapping runtime path in `helpers_astroquery.py`.
- [ ] Decide which implementation path is canonical and retire the other.
- [ ] Remove legacy “Old” classes once behavior is preserved elsewhere.
- [ ] Remove test FITS asset wiring from the production `/results` flow.
- [ ] Move debug-only or fixture-only behavior behind an explicit development flag if it must remain.
- [ ] Remove or fully gate the current test-FITS fallback so production results only show real assets.
- [ ] Extract repeated flux conversion and error-propagation logic into shared functions.
- [ ] Clean up `st_logg` parsing and suppress the NEA `DexUnit` warning in the canonical lookup path.

Exit criteria:

- One authoritative query pipeline remains.
- Test fixtures are not coupled to live request handling.
- Shared calculations are implemented once.

## Phase 6: API Consistency And Validation

Goal: make the API predictable for callers and safer to evolve.

Todo:

- [ ] Define a consistent response format for success and error cases.
- [ ] Add centralized validation for numeric inputs, coordinates, star names, and enum-like flags.
- [ ] Review all API endpoints for type conversion done inline inside route bodies.
- [ ] Normalize JSON responses so endpoints do not mix plain strings and structured objects.
- [ ] Document endpoint behavior and expected inputs.

Exit criteria:

- API routes follow a consistent validation and response pattern.
- Invalid inputs fail early and clearly.

## Phase 7: Tests And Regression Protection

Goal: make refactoring safe enough to complete the earlier phases confidently.

Todo:

- [ ] Add unit tests for flux conversion and error propagation.
- [ ] Add tests for subtype selection and model filtering logic.
- [ ] Add tests for session-backed modal and results flow.
- [ ] Add tests for admin upload/delete validation paths.
- [ ] Add tests or fixtures for external lookup failure handling.
- [ ] Add at least one smoke test covering the main search workflow.

Exit criteria:

- Critical astronomy logic has automated regression coverage.
- Refactors in phases 1 through 6 can be validated without relying only on manual testing.

## Suggested Execution Strategy

- Start with Phases 1 and 2 before making deeper behavior changes.
- Do Phase 7 in parallel with Phases 3 through 6 where possible.
- Avoid merging large functional rewrites without tests covering the affected flow.
- Treat `models.py` and `helpers_astroquery.py` consolidation as a refactor after error handling and tests improve.

## First Concrete Milestone

Recommended first implementation slice:

- [ ] Unify the Flask bootstrap path.
- [ ] Fix real runtime session initialization.
- [ ] Remove dashboard secrets from source.
- [ ] Replace the highest-risk broad exception blocks in the main search flow.

This first milestone reduces operational confusion and security exposure without forcing the full query-layer rewrite immediately.