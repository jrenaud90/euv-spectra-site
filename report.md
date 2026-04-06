# Pegasus Review Report

Date: 2026-04-06

Scope: static review of the Pegasus application tree under `apps/pegasus`, including Flask app code, API routes, helpers, templates, JavaScript, deployment files, and configuration artifacts. This report focuses on defects, operational risk, security concerns, and maintainability issues.

## Summary

Pegasus is functional, but there are several structural problems that will make production behavior brittle over time. The most important issues are inconsistent application bootstrap paths, insecure embedded dashboard credentials, reliance on broad exception handling with string-based error propagation, and expensive external lookups running synchronously in request handlers.

The codebase also has a strong duplication signal: there are overlapping implementations of the same astronomy-query logic in `models.py` and `helpers_astroquery.py`, debug logging is still embedded throughout the request path, and test-only assets are still wired into the main results flow.

No automated tests were found for the critical query, conversion, or results-selection paths.

## Findings

### 1. Two competing Flask bootstrap paths create inconsistent runtime behavior

Severity: High

Evidence:

- [app.py](app.py)
- [euv_spectra_app/extensions.py](euv_spectra_app/extensions.py)
- [euv_spectra_app/__init__.py](euv_spectra_app/__init__.py)
- [euv_spectra_app/config.py](euv_spectra_app/config.py)

Why this matters:

- The deployed app starts from `app.py`, which imports the Flask app from `extensions.py`.
- There is a second Flask app created in `euv_spectra_app/__init__.py` with a different secret key setup and `Session(app)` initialization.
- That second path is not the one used by the current container entrypoint, but it is close enough to the real app to mislead future changes.

Impact:

- Session behavior, secret handling, and extension wiring are easy to misunderstand.
- Changes made against one bootstrap path can silently fail to affect production.

Recommendation:

- Consolidate to a single app factory or single bootstrap module.
- Remove dead initialization paths or convert them into a proper factory used everywhere.

### 2. Session storage intent and actual behavior do not match

Severity: High

Evidence:

- [euv_spectra_app/config.py](euv_spectra_app/config.py)
- [euv_spectra_app/__init__.py](euv_spectra_app/__init__.py)
- [euv_spectra_app/main/routes.py](euv_spectra_app/main/routes.py#L68)
- [euv_spectra_app/main/routes.py](euv_spectra_app/main/routes.py#L112)

Why this matters:

- `Config` declares `SESSION_TYPE = "filesystem"`, which implies server-side session storage.
- In the actual runtime path from `extensions.py`, `Flask-Session` is never initialized.
- The app stores a serialized `stellar_object` in `session`, which therefore falls back to Flask's signed cookie session unless the unused bootstrap path is involved.

Impact:

- Session payload size can grow unexpectedly.
- Complex object state is pushed into cookies instead of a server-side store.
- Debugging cross-request behavior becomes harder because the configured session backend is not the one actually in use.

Recommendation:

- Initialize `Flask-Session` in the real application bootstrap path or remove the server-side session configuration entirely.
- Store only the minimal identifiers or form state needed between requests.

### 3. Hardcoded dashboard credentials and security token are checked into the app tree

Severity: High

Evidence:

- [euv_spectra_app/config.cfg](euv_spectra_app/config.cfg)

Why this matters:

- The monitoring dashboard config includes static usernames, passwords, and a security token directly in the repository tree.
- Even if the dashboard is not exposed externally today, this is still credential material embedded in source.

Impact:

- Credential reuse or accidental exposure becomes far more likely.
- Rotating these values is harder because they are treated as source assets rather than deployment secrets.

Recommendation:

- Move dashboard auth entirely to environment variables or disable the dashboard in production.
- Rotate the existing values.

### 4. External catalog queries are performed synchronously in the request path, including one especially expensive pre-query

Severity: High

Evidence:

- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py#L46)
- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py#L70)
- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py#L171)
- [euv_spectra_app/models.py](euv_spectra_app/models.py#L688)

Why this matters:

- The name-search flow performs multiple remote calls inline to SIMBAD, the NASA Exoplanet Archive, and MAST.
- Before the main SIMBAD and NEA work, `search_dbs()` fetches the full distinct host star list from NEA just to normalize casing and spacing.

Impact:

- User-facing latency depends heavily on third-party uptime and performance.
- A single external slowdown can block request workers.
- Fetching a full distinct hostname list on each lookup is disproportionately expensive for the benefit it provides.

Recommendation:

- Remove the per-request full-hostname normalization query or cache it aggressively.
- Add timeouts, retries, and clearer fallbacks around all external requests.
- Consider asynchronous work or memoization for common targets.

### 5. Broad exception handling and string-based error propagation make failures hard to reason about

Severity: High

Evidence:

- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py#L130)
- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py#L315)
- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py#L404)
- [euv_spectra_app/models.py](euv_spectra_app/models.py#L688)
- [euv_spectra_app/main/routes.py](euv_spectra_app/main/routes.py#L286)

Why this matters:

- Several request-path functions use bare `except:` or broad `except Exception` blocks.
- Many helpers return strings to signal error states instead of raising structured exceptions.

Impact:

- Programming errors and transient service failures are handled the same way.
- Control flow becomes implicit and fragile because callers must remember which functions sometimes return strings instead of data.
- Root causes are harder to diagnose and recover from safely.

Recommendation:

- Replace string-returned errors with explicit exceptions or typed result objects.
- Narrow the caught exceptions to expected failure modes.

### 6. Production request paths still contain extensive debug printing

Severity: Medium

Evidence:

- [euv_spectra_app/main/routes.py](euv_spectra_app/main/routes.py)
- [euv_spectra_app/models.py](euv_spectra_app/models.py)
- [euv_spectra_app/helpers.py](euv_spectra_app/helpers.py)
- [euv_spectra_app/extensions.py](euv_spectra_app/extensions.py)

Why this matters:

- The request flow logs raw flux values, stellar object fields, subtype decisions, and internal error details via `print()`.
- This logging is neither structured nor leveled.

Impact:

- Logs become noisy and difficult to search.
- Potentially sensitive operational data is emitted more broadly than necessary.
- Production debugging remains manual and inconsistent.

Recommendation:

- Replace `print()` calls with the standard `logging` module.
- Use log levels and avoid logging full object dumps in normal execution.

### 7. Test FITS assets are wired directly into the main results route

Severity: Medium

Evidence:

- [euv_spectra_app/main/routes.py](euv_spectra_app/main/routes.py#L262)
- [euv_spectra_app/fits_files/test/README.md](euv_spectra_app/fits_files/README.md)

Why this matters:

- The production `/results` flow builds a hardcoded list of test FITS files before continuing with model work.
- Even if these files are only used conditionally later in the route, they are still embedded in the request logic.

Impact:

- Test fixtures remain coupled to production behavior.
- The route is harder to reason about, and future cleanup becomes riskier.

Recommendation:

- Move all test-only file references behind a debug flag or remove them entirely from the live route.

### 8. API routes use ad hoc parameter parsing and inconsistent error contracts

Severity: Medium

Evidence:

- [euv_spectra_app/api/routes.py](euv_spectra_app/api/routes.py)

Why this matters:

- Most endpoints read raw query parameters with `request.args.get(...)` and then perform inline conversions.
- Some endpoints return JSON objects, others return encoded strings, and some return partial success with embedded error text.

Impact:

- API consumers cannot reliably predict response shape.
- Validation is scattered and easy to miss.
- Bad inputs can fail late and ambiguously.

Recommendation:

- Introduce a consistent request-validation layer and a standard response envelope.
- Validate numeric, coordinate, and enum inputs before computation starts.

### 9. Astronomy-query logic is duplicated across legacy and newer implementations

Severity: Medium

Evidence:

- [euv_spectra_app/models.py](euv_spectra_app/models.py)
- [euv_spectra_app/helpers_astroquery.py](euv_spectra_app/helpers_astroquery.py)

Why this matters:

- The codebase contains overlapping logic for SIMBAD, NEA, GALEX, proper-motion correction, and flux handling.
- There are "Old" classes in one path and newer helper-oriented implementations in another.

Impact:

- Bug fixes can land in one path and not the other.
- Review and debugging cost is much higher because there is no single source of truth.

Recommendation:

- Pick one implementation path and retire the other.
- Extract shared domain logic into a single service layer.

### 10. The container and dependency setup are functional but not especially production-hardened

Severity: Low

Evidence:

- [Dockerfile](Dockerfile)
- [requirements.txt](requirements.txt)

Why this matters:

- The image uses `python:3.9` without a tighter base-image strategy.
- The Dockerfile uses `ADD` where `COPY` would be clearer.
- The dependency set includes both runtime and development-only packages, with no separation or pruning.

Impact:

- Larger image size and broader attack surface.
- Slower rebuilds and more dependency churn.

Recommendation:

- Switch to `COPY`, use `pip install --no-cache-dir`, and consider separating dev tooling from runtime requirements.
- Review package pins and remove anything not needed in production.

### 11. No automated tests were found for critical flows

Severity: Medium

Evidence:

- No `tests` directory or `test_*.py` files found under `apps/pegasus`

Why this matters:

- The application depends on complex flux transformations, external service interactions, database-backed selection logic, and session-persisted state.

Impact:

- Regressions are likely to be discovered only in manual testing or production.
- Refactoring the duplicated code paths will remain high risk until behavior is pinned down.

Recommendation:

- Add tests first around:
  - stellar parameter lookup fallbacks
  - GALEX flux conversion and error propagation
  - subtype/model selection logic
  - session-backed modal/result flow
  - admin upload and delete validation

## Suggested Improvement Order

1. Unify application initialization and fix session storage in the real runtime path.
2. Remove hardcoded dashboard credentials and rotate them.
3. Replace broad exception handling with structured error handling.
4. Reduce synchronous external-query cost, especially the full NEA hostname scan.
5. Remove test fixtures from live request paths.
6. Consolidate duplicate astronomy-query code.
7. Introduce automated tests before larger refactors.

## Notes

- This report is based on static inspection. It does not claim behavioral completeness for every route or edge case.
- Diagnostics were clean at review time, so the main risks are architectural, operational, and correctness-related rather than syntax errors.