"""
seed_db.py — Populates MongoDB collections from local FITS files.

Run once after standing up the MongoDB container:
    docker exec -it pegasus python seed_db.py

Collections populated:
    - m0_grid through m8_grid  (from FITS files in fits_files/<SUBTYPE>/)
    - model_parameter_grid     (one doc per subtype, representative stellar params)
    - photosphere_models       (from FITS files in fits_files/photosphere/ if available)
    - mast_galex_times         (manual entry or from a CSV if you have one)
"""

from astropy.io import fits
from pymongo import MongoClient
import os
import re

# ── Config ────────────────────────────────────────────────────────────────────
MONGO_URI = os.environ.get('MONGODB_URI', 'mongodb://pegasus_admin:password@localhost:27017/')
DB_NAME   = os.environ.get('MONGODB_DATABASE', 'pegasus_db')
FITS_ROOT = os.path.join(os.path.dirname(__file__), 'euv_spectra_app', 'fits_files')

client = MongoClient(MONGO_URI)
db     = client.get_database(DB_NAME)

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_integrated_flux(filepath, wavelength_col='WAVELENGTH', flux_col='FLUX'):
    """Opens a FITS file and returns integrated EUV, FUV, and NUV band fluxes."""
    with fits.open(filepath) as hst:
        data       = hst[1].data
        wavelength = data[wavelength_col][0]
        flux       = data[flux_col][0]

    # Define band ranges (Angstroms)
    EUV_MIN, EUV_MAX = 100,  912
    FUV_MIN, FUV_MAX = 912,  1700
    NUV_MIN, NUV_MAX = 1700, 3000

    def integrate_band(wv_min, wv_max):
        mask = (wavelength >= wv_min) & (wavelength <= wv_max)
        if mask.sum() < 2:
            return 0.0
        wv_band   = wavelength[mask]
        flux_band = flux[mask]
        # Trapezoidal integration
        return float(sum(
            0.5 * (flux_band[i] + flux_band[i+1]) * (wv_band[i+1] - wv_band[i])
            for i in range(len(wv_band) - 1)
        ))

    return {
        'euv': integrate_band(EUV_MIN, EUV_MAX),
        'fuv': integrate_band(FUV_MIN, FUV_MAX),
        'nuv': integrate_band(NUV_MIN, NUV_MAX),
    }


def parse_params_from_filename(filename):
    """
    Parses stellar parameters from PEGASUS FITS filename convention.
    Example: PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits
    """
    params = {}
    teff_match  = re.search(r'Teff=(\d+\.?\d*)',  filename)
    logg_match  = re.search(r'logg=(\d+\.?\d*)',  filename)
    mass_match  = re.search(r'mass=(\d+\.?\d*)',  filename)   # if present
    subtype_match = re.search(r'\.(M\d+)\.', filename)

    if teff_match:
        params['teff'] = float(teff_match.group(1))
    if logg_match:
        params['logg'] = float(logg_match.group(1))
    if mass_match:
        params['mass'] = float(mass_match.group(1))
    if subtype_match:
        params['subtype'] = subtype_match.group(1)

    return params


# ── Seed Model Grids (m0_grid → m8_grid) ──────────────────────────────────────

SUBTYPES = ['M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8']

for subtype in SUBTYPES:
    subtype_dir = os.path.join(FITS_ROOT, subtype)
    if not os.path.isdir(subtype_dir):
        print(f'  [SKIP] No directory found for {subtype} at {subtype_dir}')
        continue

    collection_name = f'{subtype.lower()}_grid'
    collection = db.get_collection(collection_name)
    collection.drop()   # Clear before re-seeding

    fits_files = [f for f in os.listdir(subtype_dir) if f.endswith('.fits')]
    print(f'\n[{subtype}] Found {len(fits_files)} FITS files → seeding {collection_name}')

    docs = []
    for filename in fits_files:
        filepath = os.path.join(subtype_dir, filename)
        try:
            params = parse_params_from_filename(filename)
            fluxes = get_integrated_flux(filepath)

            doc = {
                'fits_filename': filename,
                'teff': params.get('teff'),
                'logg': params.get('logg'),
                'mass': params.get('mass'),
                'euv':  fluxes['euv'],
                'fuv':  fluxes['fuv'],
                'nuv':  fluxes['nuv'],
            }
            docs.append(doc)
            print(f'  ✓ {filename}  EUV={fluxes["euv"]:.2f}  FUV={fluxes["fuv"]:.2f}  NUV={fluxes["nuv"]:.2f}')
        except Exception as e:
            print(f'  ✗ ERROR processing {filename}: {e}')

    if docs:
        collection.insert_many(docs)
        print(f'  → Inserted {len(docs)} documents into {collection_name}')

    # ── Seed model_parameter_grid (one entry per subtype) ─────────────────────
    # Uses the first file's params as the representative entry for this subtype
    if docs:
        rep = docs[0]
        db.model_parameter_grid.update_one(
            {'model': subtype},
            {'$set': {
                'model': subtype,
                'teff':  rep['teff'],
                'logg':  rep['logg'],
                'mass':  rep['mass'],
            }},
            upsert=True
        )
        print(f'  → Upserted model_parameter_grid entry for {subtype}')


# ── Seed photosphere_models ────────────────────────────────────────────────────
photo_dir = os.path.join(FITS_ROOT, 'photosphere')
if os.path.isdir(photo_dir):
    db.photosphere_models.drop()
    fits_files = [f for f in os.listdir(photo_dir) if f.endswith('.fits')]
    print(f'\n[PHOTOSPHERE] Found {len(fits_files)} FITS files')
    docs = []
    for filename in fits_files:
        filepath = os.path.join(photo_dir, filename)
        try:
            params = parse_params_from_filename(filename)
            fluxes = get_integrated_flux(filepath)
            doc = {
                'fits_filename': filename,
                'teff': params.get('teff'),
                'logg': params.get('logg'),
                'mass': params.get('mass'),
                'euv':  fluxes['euv'],
                'fuv':  fluxes['fuv'],
                'nuv':  fluxes['nuv'],
            }
            docs.append(doc)
        except Exception as e:
            print(f'  ✗ ERROR {filename}: {e}')
    if docs:
        db.photosphere_models.insert_many(docs)
        print(f'  → Inserted {len(docs)} photosphere model documents')
else:
    print('\n[PHOTOSPHERE] No photosphere/ directory found - skipping')
    print('  You will need to seed photosphere_models manually!')


print('\nSeeding complete!')
print('Collections in DB:', db.list_collection_names())