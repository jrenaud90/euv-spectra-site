# Pegasus Search Latency Report

Date: 2026-04-10

Scope: review of page reload, star search, and results rendering based on the provided container logs. This report identifies the slow functions and proposes optimization strategies beyond the caching already in place.

## Executive Summary

The star-search request is dominated by external network calls, not local Flask or MongoDB work.

For the example search of `GJ 338 B`, the main lookup took about 7 seconds:

- `20:13:16` search POST begins
- `20:13:23` lookup pipeline completes and result is cached

The slowest parts are:

1. `normalize_star_name()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)
2. `query_nasa_exoplanet_archive()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)
3. `query_simbad()` plus proper-motion correction in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)
4. `get_model_fits_bytes()` and `_get_s3_client()` in [fits_storage.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/fits_storage.py) during results rendering

The results page itself is relatively fast in database terms, but its FITS retrieval path is paying a noticeable S3 and IAM bootstrap cost, plus two 404 object probes before falling back to a local test FITS file.

## Observed Timing Breakdown

### 1. Initial page reload

`GET /apps/pegasus/` at `20:13:10` returns immediately, followed by static assets. Nothing in the logs suggests server-side latency on the reload itself.

### 2. Search request timing

`POST /apps/pegasus/` starts at `20:13:16`.

#### A. Hostname normalization

Function: `normalize_star_name()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Approximate duration: 3 seconds

Evidence:

- `20:13:16` Attempting NEA hostname normalization
- `20:13:17` first NEA TAP response
- `20:13:19` second NEA TAP response and normalization complete

This is one of the most expensive individual steps in the request.

#### B. SIMBAD lookup and proper-motion correction

Functions:

- `query_simbad()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)
- `ProperMotionData.correct_pm()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Approximate duration: 2 seconds total

Evidence:

- `20:13:19` SIMBAD query starts
- `20:13:20` SIMBAD lookup succeeds
- `20:13:21` proper-motion correction succeeds

This step is not as expensive as NEA normalization, but it is still material.

#### C. NEA stellar parameter lookup

Function: `query_nasa_exoplanet_archive()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Approximate duration: 2 seconds

Evidence:

- `20:13:21` NEA query starts
- `20:13:21` health-check GET returns
- `20:13:22` TAP POST returns
- `20:13:23` row count and parameter success logged

This is the other major contributor to search latency.

#### D. GALEX lookup

Function: `query_galex()` in [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Approximate duration: under 1 second

Evidence:

- `20:13:23` GALEX query starts
- `20:13:23` MAST and GALEX responses complete in the same second

GALEX is not free, but it is not the bottleneck in this trace.

### 3. Results page timing

`GET /apps/pegasus/results` begins at `20:13:27`.

#### A. Local model lookup and subtype selection

Functions:

- `query_pegasus_subtype()` via helper lookup logic
- `query_model_collection()` via Mongo aggregation

Approximate duration: negligible in this trace

Evidence:

- subtype resolution and model query are logged within the same second as results entry

The MongoDB/model-selection path is not the main issue here.

#### B. FITS retrieval path

Functions:

- `get_model_fits_bytes()` in [fits_storage.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/fits_storage.py)
- `_get_s3_client()` in [fits_storage.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/fits_storage.py)

Approximate duration: about 1 second

Evidence:

- `20:13:27` S3 load attempt starts
- IAM credential discovery, botocore client setup, and two S3 `404` object lookups happen
- `20:13:28` fallback to local test FITS file

The expensive parts are:

- creating a fresh S3 client
- walking the AWS credential provider chain
- calling IMDS for IAM credentials
- trying two candidate keys, both missing

## Slow Functions Identified

### 1. `normalize_star_name()`

Location: [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Why it is slow:

- it performs a separate NEA round-trip before the actual NEA data query
- in this trace it appears to trigger two TAP interactions before returning

Impact:

- roughly 3 seconds by itself
- it is on the critical path before SIMBAD and NEA parameter retrieval continue

### 2. `query_nasa_exoplanet_archive()`

Location: [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Why it is slow:

- separate health-check request plus the actual archive query
- external service latency dominates

Impact:

- roughly 2 seconds

### 3. `query_simbad()` and `ProperMotionData.correct_pm()`

Location: [models.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/models.py)

Why they are slow:

- SIMBAD requires a health check plus a remote query
- proper-motion correction depends on preceding remote lookup and cannot be skipped for name-based searches

Impact:

- roughly 2 seconds combined

### 4. `get_model_fits_bytes()` / `_get_s3_client()`

Location: [fits_storage.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/fits_storage.py)

Why they are slow:

- a fresh boto3 client is constructed per request
- botocore walks the full credential provider chain each time
- IMDS is queried at runtime for credentials
- two missing-key S3 lookups are attempted before fallback

Impact:

- roughly 1 second in this trace
- likely worse under heavier load or when S3 latency increases

## Additional Observations

### Duplicate log lines

Several application log messages appear twice, for example:

- `Processing name-based homepage submission.`
- `Modal parameter update stored in session.`
- `Entering results workflow.`

This is probably a logger handler configuration issue in [extensions.py](/home/ubuntu/EMAC-Apps/apps/pegasus/euv_spectra_app/extensions.py), not a major latency driver, but it makes performance analysis harder and slightly increases log overhead.

### CSRF mismatch before the successful flow

The earlier `20:12:57` POST failed with `The CSRF tokens do not match.` That is separate from the search latency issue.

### GALEX is comparatively healthy in this trace

The GALEX leg completed quickly. The main search cost is mostly NEA-related plus SIMBAD.

### Result rendering is bottlenecked by FITS backend probing, not model search

The results flow is spending more time discovering AWS credentials and probing nonexistent S3 keys than querying MongoDB for the best model.

## Improvement Strategies Beyond Existing Caching

### 1. Collapse hostname normalization and NEA parameter lookup into one NEA query

Current issue:

- the request pays once for `normalize_star_name()` and then again for `query_nasa_exoplanet_archive()`

Strategy:

- query NEA once for the user input and reuse the returned row for both canonical hostname resolution and stellar parameters
- or perform normalization only when the direct parameter lookup fails

Why this helps:

- removes an entire network phase from the critical path
- likely saves the biggest single chunk of latency in the current flow

### 2. Parallelize independent remote lookups after proper-motion data is ready

Current issue:

- once SIMBAD and proper-motion correction are done, NEA and GALEX are still executed sequentially

Strategy:

- run NEA and GALEX concurrently after coordinates are available
- join results before continuing to subtype and form population

Why this helps:

- in this trace, roughly 2 seconds of NEA time and under 1 second of GALEX time are serialized
- concurrency could reduce wall-clock search time even if both services remain equally slow

Constraint:

- concurrency should be implemented carefully because astroquery and request/session objects may not be trivially thread-safe in every configuration

### 3. Remove or soften synchronous health-check requests from the hot path

Current issue:

- the search flow performs availability checks immediately before the real service calls

Strategy options:

- treat the real query itself as the health check
- use a background health monitor instead of per-request preflight checks
- use a circuit-breaker pattern with short-lived degraded mode rather than synchronous GETs in the request path

Why this helps:

- reduces extra round-trips for SIMBAD, NEA, and GALEX
- simplifies the request flow

### 4. Keep a long-lived boto3 session/client instead of constructing one per request

Current issue:

- `_get_s3_client()` builds a new boto3 client every time
- that triggers repeated config loading and credential provider resolution

Strategy:

- initialize a module-level or app-scoped boto3 session/client once per worker
- refresh only when needed rather than rebuilding on every FITS lookup

Why this helps:

- avoids repeated IMDS and botocore startup overhead
- should make results-page rendering more predictable

### 5. Stop probing multiple S3 key patterns at request time

Current issue:

- `build_s3_key_candidates()` causes multiple `GetObject` attempts for the same logical FITS file
- in this trace both candidate keys miss before local fallback

Strategy options:

- maintain a canonical filename convention and store only one resolvable key
- persist the resolved storage key alongside model metadata in MongoDB
- generate a manifest/index of valid FITS keys during deploy or ingest

Why this helps:

- eliminates wasted 404s on the request path
- converts runtime discovery into deterministic lookup

This is not the same as request-result caching; it is data-model cleanup and precomputed storage mapping.

### 6. Pre-stage FITS availability metadata in MongoDB or a manifest file

Current issue:

- the request discovers missing FITS files by asking S3 directly

Strategy:

- publish an availability manifest during the data pipeline
- store the exact storage location and availability bit with each model record

Why this helps:

- avoids remote object-store misses during user requests
- lets the UI and results logic skip unavailable models earlier

### 7. Precompute alias tables for common star names

Current issue:

- user-submitted star names require external normalization before the real search begins

Strategy:

- build a local alias table from NEA hostnames and common spelling variations
- resolve common names locally before going remote

Why this helps:

- removes latency for common objects
- reduces dependency on NEA for name canonicalization

This is broader than runtime caching because it turns a remote normalization problem into a local data product.

### 8. Consider asynchronous search orchestration for the UX

Current issue:

- the user waits synchronously for every external step before seeing the modal

Strategy:

- move the lookup pipeline to a short-lived background job or async task
- immediately return a progress state to the UI and poll for completion

Why this helps:

- does not reduce absolute backend work, but improves perceived responsiveness
- makes slow external services less damaging to the interactive flow

### 9. Reduce duplicated log handling

Current issue:

- log lines are duplicated, which makes latency analysis noisy

Strategy:

- ensure handlers are attached once per worker
- avoid propagating application logs into duplicate gunicorn/root handlers

Why this helps:

- cleaner profiling and lower logging overhead
- easier correlation of timing in production incidents

## Priority Recommendations

If the goal is to lower real user-facing latency quickly, the highest-value improvements are:

1. Eliminate the separate hostname-normalization round-trip or fold it into the main NEA lookup.
2. Run NEA and GALEX in parallel once proper-motion-corrected coordinates are available.
3. Rework FITS retrieval so the request does not create a fresh boto3 client and does not probe missing S3 keys blindly.
4. Remove synchronous service health checks from the hot path and rely on query-time error handling or background health monitoring.

## Expected Payoff

Based on this trace alone, the current cold search path is about 7 seconds.

Reasonable savings from structural improvements, without relying on cache hits, would likely come from:

- removing separate normalization work: roughly 2 to 3 seconds
- overlapping NEA and GALEX: roughly up to 1 second of wall-clock savings in this trace
- reducing S3 client/bootstrap and failed-object probing: roughly about 1 second on results rendering

That would not make the flow instantaneous, but it would materially reduce first-hit latency and make performance much less dependent on external service jitter.