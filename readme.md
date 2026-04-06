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

## Local deployment notes

- Copy `apps/pegasus/.env.example` to `apps/pegasus/.env` and fill in the Flask, mail, Mongo, and admin-key settings.
- The shared compose stack starts `pegasus_mongodb` alongside the Flask container and restores the repository backup archive on first boot.
- The restore script expects the archive source database to be `mydatabase`; override `MONGODB_ARCHIVE_SOURCE_DB` if your backup changes.
- Admin data management is exposed at `/apps/pegasus/admin` and requires signing a server-issued challenge with the configured private key.
- Flask Monitoring Dashboard is disabled by default. If you need it, enable it explicitly with the `DASHBOARD_*` environment variables instead of editing tracked config files.