![The PEGASUS Logo](https://github.com/maliabarker/euv-spectra-site/blob/main/euv_spectra_app/static/imgs/PEGASUS-Logo-B2.png)
# PEGASUS: PHOENIX EUV Grid and Stellar UV Spectra

<p align='center'>
    <a href='phoenixpegasusgrid.com'>Click here to access the website!</a></br>
    Welcome to the PEGASUS webtool, an easy way to gain access to generalized EUV spectra. </br>
</p>


### EUV Background
_**The Importance**_ </br>
Extreme ultraviolet (EUV) radiation from stars affects planetary atmospheres and can lead to water loss and atmospheric escape—both very important factors in determining habitability. </br>

_**The Problem**_ </br>
We face an issue today in which we are unable to observe and measure EUV wavelengths (124 - 10 nm). Earth's atmosphere absorbs EUV radiation, making it difficult to observe from our planet's surface. There are currently no missions or observatories beyond our planet that have the tools to observe these wavelengths either. Even if we did have the tools in space, interstellar hydrogen and helium easily absorb EUV radiation, once again making it difficult to observe.</br>

_**The Solution**_ </br>
We can build synthetic models with atmospheric code—in this case, the PHOENIX code—to predict the EUV radiation coming from a star. Instead of building a painstakingly long list of simulated atmospheres for specific target stars, we built a generalized grid of stellar subtypes. Each subtype has a unique combination of stellar effective temperature, surface gravity, and mass, shown in the image below. </br>
<p align='center'>
    <img src="https://github.com/maliabarker/euv-spectra-site/blob/main/euv_spectra_app/static/imgs/model-grid.png" width="300"> </br>
</p>
Each subtype has its own subgrid of 72 data points, each with unique values of FUV, NUV, and EUV flux densities in ergs/cm2/s/Å. 

### The Webtool
[phoenixpegasusgrid.com](phoenixpegasusgrid.com) works in a few steps. 
- First, the user searches by a star name or a position (which hopefully points towards a stellar object).
- A search is run on the star using Astroquery's Nasa Exoplanet Archive, MAST, and SIMBAD packages. The user is returned data from their star including:
    * Effective temperature
    * Surface Gravity
    * Mass
    * Distance
    * Radius
    * GALEX NUV Flux Density & NUV Error
    * GALEX FUV Flux Density & FUV Error
- The user can choose to submit this data or input their own. This data is used to match the star to a model in the PEGASUS grid. First, a stellar subtype match is found using stellar parameters (temp, gravity, & mass). Then the stellar subtype's subgrid is searched and a match in found using the GALEX flux densities.
- Each matching model's FITS file (which includes wavelength and flux density of the model's EUV spectrum) is pulled and an interactive graph of wavelength vs. flux density is displayed to the user. The user can also download the FITS file for their own use.

### Acknowledgments
We wish to thank and recognize the following for their contribution to this project </br>

**Affiliations:**
University of Maryland, Baltimore County </br>
NASA Goddard Space Flight Center </br>
University of Arizona, Lunar and Planetary Lab </br>

**High Performance Computing Centers:**
NASA Center for Climate Simulation </br>
University of Arizona HPC </br>
University of Arizona PACMAN </br>

**Archives:**
NASA Exoplanet Archive </br>
MAST </br>
GALEX </br>

And I wish to thank my mentor, the lead in the PEGASUS project, Dr. Sarah Peacock.

### Contacts
If there are any questions regarding access, use, errors, or more, please email me at maliabarker[at]icloud.com

## API notes

- The interactive API page is available at `/apps/pegasus/api/` in a running deployment.
- API responses now use a consistent JSON envelope. Successful requests return `{"ok": true, "data": ...}` and validation or lookup failures return `{"ok": false, "error": {...}}` with an HTTP status such as 400 or 404.
- Route arguments are validated centrally. Numeric fields must parse as floats, required text fields must be present and non-blank, and coordinate lookups expect ICRS sexagesimal strings such as `09h14m22.00s+52d41m00.68s`.
- Core lookup endpoints:
    - `/api/get_parameters_by_name?name=...`
    - `/api/get_parameters_by_position?position=...`
    - `/api/get_galex_obs_time?star_name=...`
- Flux-processing endpoints:
    - `/api/convert_microjanskies_to_flux`
    - `/api/scale_galex_flux`
    - `/api/get_matching_photosphere_model`
    - `/api/subtract_photospheric_flux`
    - `/api/convert_scale_photosphere_subtract_galex_fluxes`
- Model-selection endpoints:
    - `/api/get_matching_subtype`
    - `/api/get_models_in_limits`
    - `/api/get_models_by_chi_squared`
    - `/api/get_models_by_weighted_fuv`
    - `/api/get_models_by_flux_ratio`
    - `/api/get_model_data`

## Local deployment notes

- Copy `apps/pegasus/.env.example` to `apps/pegasus/.env` and fill in the Flask, mail, Mongo, and admin-key settings.
- The shared compose stack starts `pegasus_mongodb` alongside the Flask container and restores the repository backup archive on first boot.
- The restore script expects the archive source database to be `mydatabase`; override `MONGODB_ARCHIVE_SOURCE_DB` if your backup changes.
- Admin data management is exposed at `/apps/pegasus/admin` and requires signing a server-issued challenge with the configured private key.
- Flask Monitoring Dashboard is disabled by default. If you need it, enable it explicitly with the `DASHBOARD_*` environment variables instead of editing tracked config files.
- External catalog lookups use configurable request budgets. Adjust `EXTERNAL_REQUEST_TIMEOUT`, `ASTROQUERY_TIMEOUT`, and `HOSTNAME_CACHE_TIMEOUT` in the Pegasus environment if upstream services are consistently slow.
- Transient upstream failures are retried a small number of times. Tune `EXTERNAL_RETRY_ATTEMPTS` and `EXTERNAL_RETRY_BACKOFF_SECONDS` if a deployment needs a different retry budget.
- Service health checks are cached briefly to avoid repeated probe requests on back-to-back searches. Tune `EXTERNAL_HEALTHCHECK_CACHE_TIMEOUT` if you need faster freshness or lower overhead.
- Test FITS fallbacks are disabled by default in code. Enable `ALLOW_TEST_FITS_FALLBACK=1` in the deployment environment only if you intentionally want placeholder spectra to appear in results.

## Running tests

- Run Pegasus tests inside the container, not the host Python environment. The host machine may not have the Flask and astronomy dependencies installed.
- Rebuild Pegasus before running tests if you changed Python files or added new test files:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose up -d --build pegasus
```

- Run the current targeted regression suite:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose exec -T pegasus sh -lc 'cd /app && \
PYTHONPATH=/app python tests/test_flux_utils.py && \
PYTHONPATH=/app python tests/test_helpers_dbqueries.py && \
PYTHONPATH=/app python tests/test_main_routes.py && \
PYTHONPATH=/app python tests/test_admin_routes.py && \
PYTHONPATH=/app python tests/test_smoke_search_workflow.py && \
PYTHONPATH=/app python tests/test_external_lookup_handling.py'
```

- Run a single test file the same way:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose exec -T pegasus sh -lc 'cd /app && PYTHONPATH=/app python tests/test_main_routes.py'
```

- If a test file was just added and the container cannot find it, rebuild Pegasus again before rerunning the command.

## Following live logs

- Follow Pegasus application logs while the site is live:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose logs -f pegasus
```

- Follow nginx logs as well if you need to distinguish application errors from proxy errors such as `502 Bad Gateway`:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose logs -f nginx pegasus
```

- Follow MongoDB logs when debugging data restore, collection availability, or connection/authentication issues:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose logs -f pegasus_mongodb
```

- For a shorter live view, tail the most recent lines and then continue following:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose logs --tail=100 -f pegasus
```

## Accessing the admin portal

- The admin portal is exposed at `/apps/pegasus/admin`.
- The login page is at `/apps/pegasus/admin/login`.
- The admin UI allows authenticated users to load JSON or NDJSON documents into allowed MongoDB collections and delete documents or whole collection contents.

### Required configuration

- Set `ADMIN_PUBLIC_KEY_PATH` or `ADMIN_PUBLIC_KEY` in `apps/pegasus/.env` so Pegasus can verify login signatures.
- Confirm `ADMIN_ALLOWED_COLLECTIONS` includes only the MongoDB collections you want exposed in the UI.
- Rebuild or restart Pegasus after changing admin-related environment variables:

```bash
cd /home/ubuntu/EMAC-Apps/apps
sudo docker compose up -d --build pegasus
```

### Login flow

- Open `/apps/pegasus/admin/login` in the browser.
- Copy the one-time challenge string shown on the page.
- Sign that challenge with the private key that matches the configured public key.
- Base64-encode the signature and paste it into the `Base64 Signature` field.
- Submit the form to start an authenticated admin session.

### Access notes

- If admin authentication is not configured, Pegasus redirects away from the admin page and shows an error instead of exposing MongoDB controls.
- Admin sessions expire automatically based on `ADMIN_SESSION_MINUTES`.
- Replacing a collection requires typing `REPLACE` exactly.
- Deleting an entire collection requires typing the collection name exactly.
- The portal is intended for operators on the deployment host or trusted network path behind the existing site authentication and infrastructure controls.