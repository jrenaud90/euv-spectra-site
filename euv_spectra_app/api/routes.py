from flask import Blueprint, request, render_template, current_app
import json
import os
from astropy.io import fits
from euv_spectra_app.extensions import *
from euv_spectra_app.helpers_astroquery import StellarTarget, GalexFlux
from euv_spectra_app.helpers import to_json
from euv_spectra_app.helpers_dbqueries import get_matching_subtype, get_matching_photosphere, get_models_with_chi_squared, get_models_within_limits, get_models_with_weighted_fuv, get_flux_ratios
from euv_spectra_app.extensions import cache

api = Blueprint("api", __name__, url_prefix="/api")

'''
ROUTES:

GETTING STELLAR PARAMETERS
1. Search for parameters by name (returns JSON)
2. Search for parameters by position/coords (returns JSON)

PREPARING GALEX FLUXES
3. Convert GALEX ujy to flux (returns JSON)
4. Scale fluxes to stellar surface (returns JSON)
5. Find matching photosphere model (returns b64 fits file)
6. Subtract photospheric flux (returns JSON)
7. Run all calculations for converted, scaled, and photospheric subtracted GALEX flux (returns JSON)

SEARCHING GRID
#TODO for converting file data, make sure there are enough sigfigs included so there are no duplicate wavelengths
8. Find matching subtype grid (returns JSON)
9. Find matching models within limits (returns b64 fits files)
10. Find matching models by chi squared value (returns b64 fits files)
11. Find matching models by weighted FUV flux (returns b64 fits files)
12. Find matching models by flux ratio (returns b64 fits files)

maybe:
- search simbad 
- search nasa exoplanet archive
- correct for proper motion for galex coordinates
- search galex
- predict fluxes
- something with saturated fluxes?
'''

# Helper function to convert fluxes
def convert_ujy_to_flux(flux, wv):
    return (((3e-5) * (flux * 10**-6)) / pow(wv, 2))

@api.route('/', methods=['GET', 'POST'])
def load_api():
    return render_template('load-api.html')


@api.route('/get_galex_obs_time', methods=['GET', 'POST'])
def get_galex_obs_time():
    """
    Example HTML path: /api/get_galex_obs_time?star_name=GJ338B
    """
    star_name = request.args.get('star_name')
    if star_name is not None:
        galex_time = db.mast_galex_times.find_one({'target': star_name})
        if galex_time:
            return_data = galex_time['t_min']
            return json.dumps(return_data)
    return json.dumps(f'No GALEX observations found for {star_name}. Please check your spelling, spacing, and/or capitalization and try again.')


@api.route('/get_parameters_by_name', methods=['GET', 'POST'])
def get_stellar_parameters_by_name():
    """Searches all dbs by name to return stellar parameters.

    Example HTML path: /api/get_parameters_by_name?name=GJ%20338%20B

    Args: 
        name: Name of a stellar object
    
    Returns:
        stellar_data: JSON data of all returned stellar parameters
        example: 
        {
            "star_name": "GJ 338 B", 
            "position": null, 
            "coordinates": [
                138.5977043051672, 
                52.68505424990028
            ], 
            "teff": 4014.0, 
            "logg": 4.68, 
            "mass": 0.64, 
            "dist": 6.33256, 
            "rad": 0.58, 
            "proper_motion_data": {
                "pmra": -1573.04, 
                "pmdec": -659.906,
                "parallax": 157.8825, 
                "radial_velocity": 12.43
            }, 
            "fluxes": {
                "fuv": 55.75778, 
                "fuv_err": 8.697778, 
                "nuv": 1002.1626, 
                "nuv_err": 14.8769665, 
                "scale": 2.3839961413240768e+17
            },
            "j_band": 4.779, 
            "fuv": 55.75778, 
            "nuv": 1002.1626, 
            "fuv_err": 8.697778, 
            "nuv_err": 14.8769665
        }
    """
    star_name = request.args.get('name')
    stellar_target = StellarTarget()
    if star_name == None:
        return json.dumps({})
    stellar_target.star_name = star_name
    stellar_target.search_dbs()
    stellar_data = json.dumps(to_json(stellar_target))
    return stellar_data


@api.route('/get_parameters_by_position', methods=['GET', 'POST'])
def get_stellar_parameters_by_position():
    """Searches all dbs by position to return stellar parameters.

    Example HTML path: /api/get_parameters_by_position?position=09h14m22.00s+52d41m00.68s
    
    Args: 
        position: ICRS coordinates of a stellar object.
    
    Returns:
        stellar_data_json: JSON data of all returned stellar parameters
        example: 
        {
            "star_name": null, 
            "position": "09h14m22.00s 52d41m00.68s", 
            "coordinates": [
                138.5916666666666, 
                52.683522222222216
            ], 
            "teff": 4014.0, 
            "logg": 4.68, 
            "mass": 0.64, 
            "dist": 6.33256, 
            "rad": 0.58, 
            "proper_motion_data": null, 
            "fluxes": {
                "fuv": 55.5165367, 
                "fuv_err": 8.743722, 
                "nuv": 1032.93921, 
                "nuv_err": 15.09048, 
                "scale": 2.3839961413240768e+17
            }, 
            "j_band": 4.779, 
            "fuv": 55.5165367, 
            "nuv": 1032.93921, 
            "fuv_err": 8.743722, 
            "nuv_err": 15.09048
        }
    """
    position = request.args.get('position')
    stellar_target = StellarTarget()
    if position == None:
        return json.dumps({})
    stellar_target.position = position
    stellar_target.search_dbs()
    stellar_data = json.dumps(to_json(stellar_target))
    return stellar_data


@api.route('/convert_microjanskies_to_flux')
def convert_microjanskies_to_flux():
    """Converts GALEX flux from ujy to flux density.

    Example HTML path: /api/convert_microjanskies_to_flux?fuv=55.76&fuv_err=8.7&nuv=1002.16&nuv_err=14.88

    Args: 
        fuv: GALEX FUV in microjanskies,
        nuv: GALEX NUV in microjanskies,
        fuv_err: GALEX FUV error in microjanskies,
        nuv_err: GALEX NUV error in microjanskies

    Returns:
        JSON data including the converted GALEX fluxes
        example:
            {
                "converted_nuv": 5.811986886972328e-15, 
                "converted_nuv_err": 8.629596559246903e-17, 
                "converted_fuv": 7.032444325673151e-16, 
                "converted_fuv_err": 1.0972429274274818e-16
            }
    """
    FUV_WV = 1542.3
    NUV_WV = 2274.4

    fluxes = ['fuv', 'nuv']
    return_data = {}
    
    for flux in fluxes:
        try:
            flux_value = request.args.get(flux)
            flux_err_value = request.args.get(f'{flux}_err')
            if flux_value is not None:
                wv = None
                if flux == 'fuv':
                    wv = FUV_WV
                elif flux == 'nuv':
                    wv = NUV_WV
                return_data[f'converted_{flux}'] = convert_ujy_to_flux(float(flux_value), wv)
                if flux_err_value is not None:
                    upper_lim = float(flux_value) + float(flux_err_value)
                    lower_lim = float(flux_value) - float(flux_err_value)
                    converted_upper_lim = convert_ujy_to_flux(upper_lim, wv)
                    converted_lower_lim = convert_ujy_to_flux(lower_lim, wv)
                    new_upper_lim = converted_upper_lim - return_data[f'converted_{flux}']
                    new_lower_lim = return_data[f'converted_{flux}'] - converted_lower_lim
                    return_data[f'converted_{flux}_err'] = (new_upper_lim + new_lower_lim) / 2
        except ValueError:
            return_data[f'converted_{flux}'] = f'Value of {flux} is non-numerical. Please check your inputs and try again.'
    
    return json.dumps(return_data)


@api.route('/scale_galex_flux')
def scale_galex_flux_to_stellar_surface():
    """Scales GALEX flux to the stellar surface.

    Example HTML path: /api/scale_galex_flux?fuv=55.76&fuv_err=8.7&nuv=1002.16&nuv_err=14.88&dist=6.33256&rad=0.58

    Args:
        fuv: GALEX FUV flux density (units of ergs/s/cm2/Å)
        nuv: GALEX NUV flux density (units of ergs/s/cm2/Å)
        fuv_err: GALEX FUV flux density error (units of ergs/s/cm2/Å)
        nuv_err: GALEX NUV flux density error (units of ergs/s/cm2/Å)
        dist: Stellar distance in parsecs,
        rad: Stellar radius in solar masses

    Returns:
        JSON data including the scaled GALEX fluxes
        Example:
            {
                "scale": 2.3839961413240768e+17, 
                "scaled_fuv": 1.3293162484023052e+19, 
                "scaled_nuv": 2.3891455729893366e+20, 
                "scaled_fuv_err": 2.0740766429519468e+18, 
                "scaled_nuv_err": 3.5473862582902267e+18
            }
    """
    dist = request.args.get('dist')
    rad = request.args.get('rad')

    fluxes = ['fuv', 'nuv', 'fuv_err', 'nuv_err']
    return_data = {}

    try:
        if dist is not None and rad is not None:
            return_data['scale'] = (((float(dist) * 3.08567758e18)**2) / ((float(rad) * 6.9e10)**2))
        else:
            return_data['scale'] = 'Values needed for dist and rad in order to calculate scale. Please include these values and try again.'
            return json.dumps(return_data)
    except ValueError:
        return_data['scale'] = 'Dist and/or Rad values are non-numerical, please check your formats and try again.'
        return json.dumps(return_data)
    
    for flux in fluxes:
        try:
            value = request.args.get(flux)
            if value is not None:
                return_data[f'scaled_{flux}'] = float(value) * return_data['scale']
        except ValueError:
            return_data[f'{flux}'] = f'{value} is non-numerical. Please check your format and try again.'
    
    return json.dumps(return_data)


@api.route('/get_matching_photosphere_model')
def get_matching_photosphere_model():
    """Returns a matching PHOENIX photosphere model.

    Example HTML path: /api/get_matching_photosphere_model?teff=4014.0&logg=4.68&mass=0.64

    Args:
        teff: The effective temperature of the target star in Kelvin.
        logg: The surface gravity of the target star in centimeters per second squared (cm/s^2).
        mass: The mass of the target star in solar masses.

    Returns:
        JSON data of photosphere model
        Example:
        {
            "teff": 3900.0, 
            "logg": 4.7, 
            "mass": 0.6, 
            "euv": 7.58057477103571e-14, 
            "fuv": 0.0034849216444831, 
            "nuv": 166.280545204594, 
            "diff_teff": 114.0, 
            "diff_logg": 0.020000000000000462, 
            "diff_mass": 0.040000000000000036
        }
    """
    teff = request.args.get('teff')
    logg = request.args.get('logg')
    mass = request.args.get('mass')
    try:
        if teff is not None and logg is not None and mass is not None:
            matching_photosphere_model = get_matching_photosphere(float(teff), float(logg), float(mass))
            del matching_photosphere_model['_id']
            del matching_photosphere_model['fits_filename']
            return json.dumps(matching_photosphere_model)
        else:
            return json.dumps('Stellar effective temperature (teff), surface gravity (logg), and mass are needed to find the matching photosphere. Please include these arguments and try again.')
    except ValueError:
        return json.dumps('Teff, logg, or mass has a non-numerical value. Please check your inputs and try again.')


@api.route('/subtract_photospheric_flux')
def subtract_photospheric_flux():
    """Subtracts photospheric flux contribution from GALEX fluxes.

    Example HTML path: /api/subtract_photospheric_flux?fuv=55.76&fuv_err=8.7&nuv=1002.16&nuv_err=14.88&photo_fuv=0.0034849216444831&photo_nuv=166.280545204594

    Args:
        fuv: GALEX FUV flux density (units of ergs/s/cm2/Å)
        nuv: GALEX NUV flux density (units of ergs/s/cm2/Å)
        fuv_err: GALEX FUV flux density error (units of ergs/s/cm2/Å)
        nuv_err: GALEX NUV flux density error (units of ergs/s/cm2/Å)
        photo_fuv: FUV flux density of a PHOENIX photospheric model (units of ergs/s/cm2/Å)
        photo_nuv: NUV flux density of a PHOENIX photospheric model (units of ergs/s/cm2/Å)

    Returns:
        JSON string including the photospheric subtracted GALEX fluxes
        Example:
            {
                "photosphere_subtracted_fuv": 55.75651507835551, 
                "photosphere_subtracted_fuv_err": 8.699999999999996, 
                "photosphere_subtracted_nuv": 835.87945479541, 
                "photosphere_subtracted_nuv_err": 14.879999999999995
            }
    
    """
    fluxes = ['fuv', 'nuv']
    return_data = {}

    for flux in fluxes:
        try:
            flux_value = request.args.get(flux)
            flux_err_value = request.args.get(f'{flux}_err')
            photo_flux = request.args.get(f'photo_{flux}')
            if flux_value is not None and photo_flux is not None:
                return_data[f'photosphere_subtracted_{flux}'] = float(flux_value) - float(photo_flux)
                if flux_err_value is not None:
                    upper_lim = float(flux_value) + float(flux_err_value)
                    lower_lim = float(flux_value) - float(flux_err_value)
                    photosphere_subtracted_upper_lim = upper_lim - float(photo_flux)
                    photosphere_subtracted_lower_lim = lower_lim - float(photo_flux)
                    new_upper_lim = photosphere_subtracted_upper_lim - return_data[f'photosphere_subtracted_{flux}']
                    new_lower_lim = return_data[f'photosphere_subtracted_{flux}'] - photosphere_subtracted_lower_lim
                    return_data[f'photosphere_subtracted_{flux}_err'] = (new_upper_lim + new_lower_lim) / 2
        except ValueError:
            return_data[f'photosphere_subtracted_{flux}'] = f'Value of {flux} or photo_{flux} is non-numerical. Please check your inputs and try again.'
    
    return json.dumps(return_data)


@api.route('/convert_scale_photosphere_subtract_galex_fluxes')
def convert_scale_photosphere_subtract_galex_fluxes():
    """Runs all calculations on GALEX fluxes to prepare them for searching the PEGASUS grid.

    Will first convert FUV and NUV GALEX fluxes and their respective errors from microjanskies to flux density.
    Then it will scale the GALEX fluxes to the stellar surface.
    Then it will find a matching PHOENIX photosphere model based on the given stellar parameters.
    Then it will subtract the photospheric FUV and NUV contributions from the GALEX fluxes.

    Example HTML path: /api/convert_scale_photosphere_subtract_galex_fluxes?fuv=55.76&fuv_err=8.7&nuv=1002.16&nuv_err=14.88&dist=6.33256&rad=0.58&teff=4014.0&logg=4.68&mass=0.64

    Args:
        fuv: GALEX FUV in microjanskies
        nuv: GALEX NUV in microjanskies
        fuv_err: GALEX FUV error in microjanskies
        nuv_err: GALEX NUV error in microjanskies
        teff: Effective temperature of the target star in Kelvin
        logg: Surface gravity of the target star in centimeters per second squared (cm/s^2)
        mass: Mass of the target star in solar masses
        dist: Distance of the target star in parsecs
        rad: Stellar radius in solar masses

    Returns:
        JSON string including the newly calculated GALEX fluxes
        Example:
            {
                "photo_fuv": 0.0034849216444831, 
                "photo_nuv": 166.280545204594, 
                "scale": 2.3839961413240768e+17, 
                "new_fuv": 167.64971644316745, 
                "new_fuv_err": 26.158229050822513, 
                "new_nuv": 1219.2948859922221, 
                "new_nuv_err": 20.57292489842814
            }
    """
    # 1. Find photosphere model
    # 2. Compute scale
    # 3. Run calculations by flux name
    teff = request.args.get('teff')
    logg = request.args.get('logg')
    mass = request.args.get('mass')
    dist = request.args.get('dist')
    rad = request.args.get('rad')

    FUV_WV = 1542.3
    NUV_WV = 2274.4
    fluxes = ['fuv', 'nuv']
    return_data = {}

    try:
        if teff is not None and logg is not None and mass is not None:
            matching_photosphere_model = get_matching_photosphere(float(teff), float(logg), float(mass))
            return_data['photo_fuv'] = matching_photosphere_model['fuv']
            return_data['photo_nuv'] = matching_photosphere_model['nuv']
        else:
            return json.dumps('Stellar effective temperature (teff), surface gravity (logg), and mass are needed to find the matching photosphere. Please include these arguments and try again.')
    except ValueError:
        return json.dumps('Teff, logg, or mass has a non-numerical value. Please check your inputs and try again.')


    try:
        if dist is not None and rad is not None:
            return_data['scale'] = (((float(dist) * 3.08567758e18)**2) / ((float(rad) * 6.9e10)**2))
        else:
            return_data['scale'] = 'Values needed for dist and rad in order to calculate scale. Please include these values and try again.'
            return json.dumps(return_data)
    except ValueError:
        return_data['scale'] = 'Dist and/or Rad values are non-numerical, please check your formats and try again.'
        return json.dumps(return_data)


    for flux in fluxes:
        try:
            flux_value = request.args.get(flux)
            flux_err_value = request.args.get(f'{flux}_err')
            #TODO find a better way to check that dist and rad are okay because we don't need to calculate scale
            if flux_value is not None and f'photo_{flux}' in return_data and 'scale' in return_data:
                wv = None
                if flux == 'fuv':
                    wv = FUV_WV
                elif flux == 'nuv':
                    wv = NUV_WV
                photo_flux = return_data[f'photo_{flux}']
                flux_obj = GalexFlux(float(flux_value), float(flux_err_value), photo_flux, float(dist), float(rad), wv)
                return_data[f'new_{flux}'] = flux_obj.return_new_flux()
                return_data[f'new_{flux}_err'] = flux_obj.return_new_err()
        except ValueError:
            json.dumps(f'Value of {flux} is non-numerical. Please check your inputs and try again.')
    return json.dumps(return_data)


@api.route('/get_matching_subtype')
def find_matching_phoenix_subtype():
    """Returns a matching subtype based on the PHOENIX stellar subtype parameters.

    Example HTML path: /api/get_matching_subtype?teff=4014.0&logg=4.68&mass=0.64

    Args:
        teff: Effective temperature of the target star in Kelvin
        logg: Surface gravity of the target star in centimeters per second squared (cm/s^2)
        mass: Mass of the target star in solar masses

    Returns:
        JSON string including the details of the matching stellar subtype
        Example:
            {
                "model": "M0", 
                "teff": 3850, 
                "logg": 4.78, 
                "mass": 0.53, 
                "diff_teff": 164.0, 
                "diff_logg": 0.10000000000000053, 
                "diff_mass": 0.10999999999999999
            }
    """
    teff = request.args.get('teff')
    mass = request.args.get('mass')
    logg = request.args.get('logg')
    try:
        if teff is not None and mass is not None and logg is not None:
            matching_subtype = get_matching_subtype(float(teff), float(logg), float(mass))
            del matching_subtype['_id']
            del matching_subtype['diff_sum']
            return json.dumps(matching_subtype)
        else:
            return json.dumps('Values for teff, logg, and mass are needed to search the PHOENIX grid. Please include all arguments and try again.')
    except ValueError:
        return json.dumps('Teff, logg, or mass contain non-numerical data. Please check your inputs and try again.')


@api.route('/get_models_in_limits')
def get_models_in_limits():
    """Returns PHOENIX models that have FUV and NUV flux density values within the upper and lower limits of the given GALEX FUV and NUV values.

    Example HTML path: /api/get_models_in_limits?subtype=M0&fuv=167.64971644316745&fuv_err=26.158229050822513&nuv=1219.2948859922221&nuv_err=20.57292489842814&test=True

    Args:
        subtype: The name of the PHOENIX subtype grid to search on (example 'M2')
        fuv: GALEX FUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps
        nuv: GALEX NUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps
        fuv_err: GALEX FUV error flux density converted, scaled, and photosphere subtracted from previous flux processing steps
        nuv_err: GALEX NUV error flux density converted, scaled, and photosphere subtracted from previous flux processing steps

    Returns:
        JSON string with all models within limits
        Example:
            {
                "model_0": {
                    "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=5.5.cmin=3.fits",
                    "teff": 3850.0, 
                    "logg": 4.78, 
                    "mass": 0.53, 
                    "euv": 3330.45216695799, 
                    "fuv": 177.670504667116, 
                    "nuv": 1236.00277651224
                },
            }
    """
    subtype = request.args.get('subtype')
    fuv = request.args.get('fuv')
    nuv = request.args.get('nuv')
    fuv_err = request.args.get('fuv_err')
    nuv_err = request.args.get('nuv_err')
    
    try:
        if subtype is not None:
            grid = f'{subtype.lower()}_grid'
            if fuv is not None and nuv is not None and fuv_err is not None and nuv_err is not None:
                models_in_limits = get_models_within_limits(float(nuv), float(fuv), float(nuv_err), float(fuv_err), grid)
                return_data = {}
                count = 0
                for i in models_in_limits:
                    del i['_id']
                    return_data[f'model_{count}'] = i
                    count += 1
                return json.dumps(return_data)
            else:
                return json.dumps('Values are needed for fuv, fuv_err, nuv, and nuv_err, please include these arguments and try again.')
        else:
            return json.dumps('Value is needed for subtype, please include this argument and try again.')
    except ValueError:
        return json.dumps('Value of fuv, fuv_err, nuv, or nuv_err is non-numerical. Please check your arguments and try again.')


@api.route('/get_models_by_chi_squared')
def get_models_by_chi_squared():
    """Returns PHOENIX models in the given subtype grid sorted by lowest to highest chi squared value.

    Example HTML path: /api/get_models_by_chi_squared?subtype=M0&fuv=167.64971644316745&nuv=1219.2948859922221

    Args:
        subtype: The name of the PHOENIX subtype grid to search on (example 'M2')
        fuv: GALEX FUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps
        nuv: GALEX NUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps

    Returns:
        JSON string with all models within provided subgrid sorted by chi squared value
        Example:
            { 
                "model_0": 
                    { 
                        "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=5.5.cmin=3.fits", 
                        "teff": 3850.0, 
                        "logg": 4.78, 
                        "mass": 0.53, 
                        "euv": 3330.45216695799, 
                        "fuv": 177.670504667116, 
                        "nuv": 1236.00277651224
                    }, 
                "model_1": 
                    { 
                        "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=5.5.cmin=3.5.fits", 
                        "teff": 3850.0, 
                        "logg": 4.78, 
                        "mass": 0.53, 
                        "euv": 3334.06409275876, 
                        "fuv": 161.605509788601, 
                        "nuv": 860.302752341006
                    }...
            }
    """
    subtype = request.args.get('subtype')
    fuv = request.args.get('fuv')
    nuv = request.args.get('nuv')
    try:
        if subtype is not None:
            grid = f'{subtype.lower()}_grid'
            if fuv is not None and nuv is not None:
                models_with_chi_squared = get_models_with_chi_squared(float(nuv), float(fuv), grid)
                return_data = {}
                count = 0
                for i in models_with_chi_squared:
                    del i['_id']
                    return_data[f'model_{count}'] = i
                    count += 1
                return json.dumps(return_data)
            else:
                return json.dumps('Values are needed for fuv, and nuv, please include these arguments and try again.')
        else:
            return json.dumps('Value is needed for subtype, please include this argument and try again.')
    except ValueError:
        return json.dumps('Value of fuv, fuv_err, nuv, or nuv_err is non-numerical. Please check your arguments and try again.')


@api.route('/get_models_by_weighted_fuv')
def get_models_by_weighted_fuv():
    """Returns PHOENIX models in the given subtype grid sorted by lowest to highest chi squared values and weighted on the FUV.

    Example HTML path: /api/get_models_by_weighted_fuv?subtype=M0&fuv=167.64971644316745&nuv=1219.2948859922221
    
    Args:
        subtype: The name of the PHOENIX subtype grid to search on (example 'M2')
        fuv: GALEX FUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps
        nuv: GALEX NUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps

    Returns:
        Example:
            { 
                "model_0": 
                    {
                        "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=5.5.cmin=3.5.fits", 
                        "teff": 3850.0, 
                        "logg": 4.78, 
                        "mass": 0.53, 
                        "euv": 3334.06409275876, 
                        "fuv": 161.605509788601, 
                        "nuv": 860.302752341006, 
                        "chi_squared": 105.91
                    }, 
                "model_1": 
                    {
                        "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=8.5.cmtop=6.cmin=3.fits", 
                        "teff": 3850.0, 
                        "logg": 4.78, 
                        "mass": 0.53, 
                        "euv": 3623.31043975706, 
                        "fuv": 163.419435009827, 
                        "nuv": 850.233439611939,
                        "chi_squared": 111.82
                    }...
            }
    """
    subtype = request.args.get('subtype')
    fuv = request.args.get('fuv')
    nuv = request.args.get('nuv')
    try:
        if subtype is not None:
            grid = f'{subtype.lower()}_grid'
            if fuv is not None and nuv is not None:
                models_weighted = get_models_with_weighted_fuv(float(nuv), float(fuv), grid)
                return_data = {}
                count = 0
                for i in models_weighted:
                    del i['_id']
                    del i['chi_squared_fuv']
                    del i['chi_squared_nuv']
                    return_data[f'model_{count}'] = i
                    count += 1
                return json.dumps(return_data)
            else:
                return json.dumps('Values are needed for fuv, and nuv, please include these arguments and try again.')
        else:
            return json.dumps('Value is needed for subtype, please include this argument and try again.')
    except ValueError:
        return json.dumps('Value of fuv, fuv_err, nuv, or nuv_err is non-numerical. Please check your arguments and try again.')


@api.route('/get_models_by_flux_ratio')
def get_models_by_flux_ratio():
    """Returns PHOENIX models in the given subtype grid sorted from lowest to highest chi squared value of flux ratios.

    Example HTML path: /api/get_models_by_flux_ratio?subtype=M0&fuv=167.64971644316745&nuv=1219.2948859922221

    Args:
        subtype: The name of the PHOENIX subtype grid to search on (example 'M2')
        fuv: GALEX FUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps
        nuv: GALEX NUV flux density converted, scaled, and photosphere subtracted from previous flux processing steps

    Returns:
        Example:
            {
                "model_0": 
                    {
                        "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=5.5.cmin=3.fits", 
                        "teff": 3850.0, 
                        "logg": 4.78, 
                        "mass": 0.53, 
                        "euv": 3330.45216695799, 
                        "fuv": 177.670504667116, 
                        "nuv": 1236.00277651224, 
                        "galex_flux_ratio": 7.272871746285106, 
                        "model_flux_ratio": 6.956713376978461, 
                        "ratio_chi_squared": 0.013743692721337146
                    }, 
                "model_1": 
                    {
                        "fits_filename": "PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits", 
                        "teff": 3850.0, 
                        "logg": 4.78, 
                        "mass": 0.53, 
                        "euv": 1092.41877826431, 
                        "fuv": 52.3437581238288, 
                        "nuv": 401.803589862584, 
                        "galex_flux_ratio": 7.272871746285106, 
                        "model_flux_ratio": 7.676246495561966, 
                        "ratio_chi_squared": 0.022372343969530358
                    }...
            }
    """
    subtype = request.args.get('subtype')
    fuv = request.args.get('fuv')
    nuv = request.args.get('nuv')
    try:
        if subtype is not None:
            grid = f'{subtype.lower()}_grid'
            if fuv is not None and nuv is not None:
                models_ratios = get_flux_ratios(float(nuv), float(fuv), grid)
                return_data = {}
                count = 0
                for i in models_ratios:
                    del i['_id']
                    del i['galex_flux_ratio']
                    del i['model_flux_ratio']
                    return_data[f'model_{count}'] = i
                    count += 1
                return json.dumps(return_data)
            else:
                return json.dumps('Values are needed for fuv, and nuv, please include these arguments and try again.')
        else:
            return json.dumps('Value is needed for subtype, please include this argument and try again.')
    except ValueError:
        return json.dumps('Value of fuv, fuv_err, nuv, or nuv_err is non-numerical. Please check your arguments and try again.')


@api.route('/get_model_data')
def get_model_data():
    """Returns the wavelength and flux data columns from a PHEONIX model FITS file.

    Example HTML path: /api/get_model_data?fits_filename=new_test.fits

    Args:
        fits_filename: The filename of a PHOENIX model FITS file

    Returns:
        JSON data string with key value pairs of wavelength and flux data.
        Example:
            {}
    """
    fits_filename = request.args.get('fits_filename')
    try:
        if fits_filename is not None:
            filepath = None
            return_data = {}
            for root, subfolders, filenames in os.walk(os.path.join(current_app.root_path, current_app.config['FITS_FOLDER'])):
                for filename in filenames:
                    if filename == fits_filename:
                        filepath = root + '/' + filename
            if filepath is not None:    
                hst = fits.open(filepath)
                data = hst[1].data
                return_data['wavelength_data'] = data['WAVELENGTH'][0].tolist()
                return_data['flux_data'] = data['FLUX'][0].tolist()
                return json.dumps(return_data)
            else:
                return json.dumps('Data not yet available for that file.')
    except ValueError:
        return json.dumps('The value of fits_filename threw an error. Please check your value and try again.')