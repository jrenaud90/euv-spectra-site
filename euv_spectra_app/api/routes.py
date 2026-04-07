from flask import Blueprint, request, render_template, current_app, jsonify
import io
import os
from astropy.io import fits
from astropy.coordinates import SkyCoord
import astropy.units as u
from euv_spectra_app.extensions import *
from euv_spectra_app.fits_storage import get_model_fits_bytes, get_test_fits_bytes, infer_model_subtype_from_filename, is_test_fits_filename
from euv_spectra_app.flux_utils import FUV_WAVELENGTH, NUV_WAVELENGTH, average_error_from_limits, calculate_surface_scale, convert_microjanskies_to_flux_density, process_galex_flux_with_error, subtract_photospheric_flux as subtract_photospheric_flux_value
from euv_spectra_app.models import StellarObject
from euv_spectra_app.helpers_dbqueries import get_matching_subtype, get_matching_photosphere, get_models_with_chi_squared, get_models_within_limits, get_models_with_weighted_fuv, get_flux_ratios
from euv_spectra_app.extensions import cache

api = Blueprint("api", __name__, url_prefix="/api")


class ApiValidationError(ValueError):
    def __init__(self, message, field=None, code='invalid_argument'):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code


def api_success(data=None, status=200):
    return jsonify({'ok': True, 'data': data}), status


def api_error(message, status=400, code='invalid_request', field=None, details=None):
    error = {'code': code, 'message': message}
    if field is not None:
        error['field'] = field
    if details is not None:
        error['details'] = details
    return jsonify({'ok': False, 'error': error}), status


def get_text_arg(name, label=None, required=False):
    value = request.args.get(name)
    if value is None:
        if required:
            raise ApiValidationError(f'{label or name} is required.', field=name, code='missing_argument')
        return None

    value = value.strip()
    if required and not value:
        raise ApiValidationError(f'{label or name} cannot be blank.', field=name, code='missing_argument')
    return value or None


def get_float_arg(name, label=None, required=False):
    value = get_text_arg(name, label=label, required=required)
    if value is None:
        return None

    try:
        return float(value)
    except ValueError as exc:
        raise ApiValidationError(f'{label or name} must be numeric.', field=name, code='invalid_argument') from exc


def get_position_arg(name='position', label='position', required=False):
    value = get_text_arg(name, label=label, required=required)
    if value is None:
        return None

    try:
        SkyCoord(value, unit=(u.hourangle, u.deg))
    except Exception as exc:
        raise ApiValidationError(
            f'{label} must be valid ICRS coordinates in sexagesimal format.',
            field=name,
            code='invalid_argument',
        ) from exc
    return value


def scrub_document(document, drop_fields=None):
    if document is None:
        return None

    cleaned = dict(document)
    for field in drop_fields or ():
        cleaned.pop(field, None)
    return cleaned


def serialize_model_collection(documents, drop_fields=None):
    payload = {}
    for count, document in enumerate(documents):
        payload[f'model_{count}'] = scrub_document(document, drop_fields=drop_fields)
    return payload


def parse_api_validation_error(exc):
    return api_error(exc.message, status=400, code=exc.code, field=exc.field)


def parse_unexpected_api_error(message):
    current_app.logger.exception(message)
    return api_error(message, status=500, code='internal_error')

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

def serialize_api_coordinates(stellar_object):
    if getattr(stellar_object, 'pm_corrected_coords', None):
        return list(stellar_object.pm_corrected_coords)

    coords = getattr(stellar_object, 'coords', None)
    if not coords:
        return None

    if isinstance(coords, (list, tuple)) and len(coords) == 2:
        if all(isinstance(value, (int, float)) for value in coords):
            return [float(coords[0]), float(coords[1])]
        if all(isinstance(value, str) for value in coords):
            converted = SkyCoord(f'{coords[0]} {coords[1]}', unit=(u.hourangle, u.deg))
            return [converted.ra.degree, converted.dec.degree]

    return None


def serialize_api_pm_data(stellar_object):
    pm_data = getattr(stellar_object, 'pm_data', None)
    if pm_data is None:
        return None

    return {
        'pmra': getattr(pm_data, 'pm_ra', None),
        'pmdec': getattr(pm_data, 'pm_dec', None),
        'parallax': getattr(pm_data, 'plx', None),
        'radial_velocity': getattr(pm_data, 'rad_vel', None),
    }


def serialize_api_fluxes(stellar_object):
    fluxes = getattr(stellar_object, 'fluxes', None)
    if fluxes is None:
        return None

    flux_payload = {
        'fuv': getattr(fluxes, 'fuv', None),
        'fuv_err': getattr(fluxes, 'fuv_err', None),
        'nuv': getattr(fluxes, 'nuv', None),
        'nuv_err': getattr(fluxes, 'nuv_err', None),
    }

    if getattr(stellar_object, 'dist', None) is not None and getattr(stellar_object, 'rad', None) is not None:
        flux_payload['scale'] = calculate_surface_scale(stellar_object.dist, stellar_object.rad)

    return flux_payload


def serialize_api_stellar_object(stellar_object):
    flux_payload = serialize_api_fluxes(stellar_object)
    response = {
        'star_name': getattr(stellar_object, 'star_name', None),
        'position': getattr(stellar_object, 'position', None),
        'coordinates': serialize_api_coordinates(stellar_object),
        'teff': getattr(stellar_object, 'teff', None),
        'logg': getattr(stellar_object, 'logg', None),
        'mass': getattr(stellar_object, 'mass', None),
        'dist': getattr(stellar_object, 'dist', None),
        'rad': getattr(stellar_object, 'rad', None),
        'proper_motion_data': serialize_api_pm_data(stellar_object),
        'fluxes': flux_payload,
        'j_band': None,
        'modal_error_msgs': getattr(stellar_object, 'modal_error_msgs', []),
        'modal_page_error_msg': getattr(stellar_object, 'modal_page_error_msg', None),
    }

    if flux_payload is not None:
        response['fuv'] = flux_payload.get('fuv')
        response['nuv'] = flux_payload.get('nuv')
        response['fuv_err'] = flux_payload.get('fuv_err')
        response['nuv_err'] = flux_payload.get('nuv_err')

    return response

@api.route('/', methods=['GET', 'POST'])
def load_api():
    return render_template('load-api.html')


@api.route('/get_galex_obs_time', methods=['GET', 'POST'])
def get_galex_obs_time():
    """
    Example HTML path: /api/get_galex_obs_time?star_name=GJ338B
    """
    try:
        star_name = get_text_arg('star_name', label='star_name', required=True)
        galex_time = db.mast_galex_times.find_one({'target': star_name})
        if galex_time:
            return api_success(galex_time['t_min'])
        return api_error(
            f'No GALEX observations found for {star_name}. Please check your spelling, spacing, and/or capitalization and try again.',
            status=404,
            code='not_found',
            field='star_name',
        )
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve GALEX observation time.')


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
    try:
        star_name = get_text_arg('name', label='name', required=True)
        stellar_target = StellarObject()
        stellar_target.star_name = star_name
        stellar_target.get_stellar_parameters()
        return api_success(serialize_api_stellar_object(stellar_target))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve stellar parameters by name.')


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
    try:
        position = get_position_arg(required=True)
        stellar_target = StellarObject()
        stellar_target.position = position
        stellar_target.get_stellar_parameters()
        return api_success(serialize_api_stellar_object(stellar_target))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve stellar parameters by position.')


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
    try:
        fluxes = ['fuv', 'nuv']
        return_data = {}

        for flux in fluxes:
            flux_value = get_float_arg(flux)
            flux_err_value = get_float_arg(f'{flux}_err')
            if flux_value is None:
                continue

            wavelength = FUV_WAVELENGTH if flux == 'fuv' else NUV_WAVELENGTH
            return_data[f'converted_{flux}'] = convert_microjanskies_to_flux_density(flux_value, wavelength)
            if flux_err_value is not None:
                upper_lim = flux_value + flux_err_value
                lower_lim = flux_value - flux_err_value
                converted_upper_lim = convert_microjanskies_to_flux_density(upper_lim, wavelength)
                converted_lower_lim = convert_microjanskies_to_flux_density(lower_lim, wavelength)
                return_data[f'converted_{flux}_err'] = average_error_from_limits(return_data[f'converted_{flux}'], converted_upper_lim, converted_lower_lim)

        if not return_data:
            raise ApiValidationError('At least one of fuv or nuv is required.', field='fuv', code='missing_argument')

        return api_success(return_data)
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to convert GALEX microjanskies to flux.')


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
    try:
        dist = get_float_arg('dist', label='dist', required=True)
        rad = get_float_arg('rad', label='rad', required=True)

        fluxes = ['fuv', 'nuv', 'fuv_err', 'nuv_err']
        return_data = {'scale': calculate_surface_scale(dist, rad)}

        for flux in fluxes:
            value = get_float_arg(flux)
            if value is not None:
                return_data[f'scaled_{flux}'] = value * return_data['scale']

        return api_success(return_data)
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to scale GALEX flux to the stellar surface.')


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
    try:
        teff = get_float_arg('teff', label='teff', required=True)
        logg = get_float_arg('logg', label='logg', required=True)
        mass = get_float_arg('mass', label='mass', required=True)
        matching_photosphere_model = get_matching_photosphere(teff, logg, mass)
        return api_success(scrub_document(matching_photosphere_model, drop_fields=('_id', 'fits_filename')))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve a matching photosphere model.')


@api.route('/subtract_photospheric_flux')
def subtract_photospheric_flux_route():
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
    try:
        fluxes = ['fuv', 'nuv']
        return_data = {}

        for flux in fluxes:
            flux_value = get_float_arg(flux)
            flux_err_value = get_float_arg(f'{flux}_err')
            photo_flux = get_float_arg(f'photo_{flux}')
            if flux_value is None or photo_flux is None:
                continue

            return_data[f'photosphere_subtracted_{flux}'] = subtract_photospheric_flux_value(flux_value, photo_flux)
            if flux_err_value is not None:
                upper_lim = flux_value + flux_err_value
                lower_lim = flux_value - flux_err_value
                photosphere_subtracted_upper_lim = subtract_photospheric_flux_value(upper_lim, photo_flux)
                photosphere_subtracted_lower_lim = subtract_photospheric_flux_value(lower_lim, photo_flux)
                return_data[f'photosphere_subtracted_{flux}_err'] = average_error_from_limits(
                    return_data[f'photosphere_subtracted_{flux}'],
                    photosphere_subtracted_upper_lim,
                    photosphere_subtracted_lower_lim,
                )

        if not return_data:
            raise ApiValidationError(
                'At least one flux and matching photospheric flux pair is required.',
                field='fuv',
                code='missing_argument',
            )

        return api_success(return_data)
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to subtract photospheric flux.')


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
    try:
        teff = get_float_arg('teff', label='teff', required=True)
        logg = get_float_arg('logg', label='logg', required=True)
        mass = get_float_arg('mass', label='mass', required=True)
        dist = get_float_arg('dist', label='dist', required=True)
        rad = get_float_arg('rad', label='rad', required=True)

        fluxes = ['fuv', 'nuv']
        matching_photosphere_model = get_matching_photosphere(teff, logg, mass)
        return_data = {
            'photo_fuv': matching_photosphere_model['fuv'],
            'photo_nuv': matching_photosphere_model['nuv'],
            'scale': calculate_surface_scale(dist, rad),
        }

        processed_flux = False
        for flux in fluxes:
            flux_value = get_float_arg(flux)
            flux_err_value = get_float_arg(f'{flux}_err')
            if flux_value is None:
                continue

            wavelength = FUV_WAVELENGTH if flux == 'fuv' else NUV_WAVELENGTH
            photo_flux = return_data[f'photo_{flux}']
            new_flux, new_err = process_galex_flux_with_error(flux_value, flux_err_value, photo_flux, dist, rad, wavelength)
            return_data[f'new_{flux}'] = new_flux
            return_data[f'new_{flux}_err'] = new_err
            processed_flux = True

        if not processed_flux:
            raise ApiValidationError('At least one of fuv or nuv is required.', field='fuv', code='missing_argument')

        return api_success(return_data)
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to prepare GALEX fluxes for PEGASUS.')


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
    try:
        teff = get_float_arg('teff', label='teff', required=True)
        mass = get_float_arg('mass', label='mass', required=True)
        logg = get_float_arg('logg', label='logg', required=True)
        matching_subtype = get_matching_subtype(teff, logg, mass)
        return api_success(scrub_document(matching_subtype, drop_fields=('_id', 'diff_sum')))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to find a matching PHOENIX subtype.')


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
    try:
        subtype = get_text_arg('subtype', label='subtype', required=True)
        fuv = get_float_arg('fuv', label='fuv', required=True)
        nuv = get_float_arg('nuv', label='nuv', required=True)
        fuv_err = get_float_arg('fuv_err', label='fuv_err', required=True)
        nuv_err = get_float_arg('nuv_err', label='nuv_err', required=True)
        grid = f'{subtype.lower()}_grid'
        models_in_limits = get_models_within_limits(nuv, fuv, nuv_err, fuv_err, grid)
        return api_success(serialize_model_collection(models_in_limits, drop_fields=('_id',)))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve models within limits.')


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
    try:
        subtype = get_text_arg('subtype', label='subtype', required=True)
        fuv = get_float_arg('fuv', label='fuv', required=True)
        nuv = get_float_arg('nuv', label='nuv', required=True)
        grid = f'{subtype.lower()}_grid'
        models_with_chi_squared = get_models_with_chi_squared(nuv, fuv, grid)
        return api_success(serialize_model_collection(models_with_chi_squared, drop_fields=('_id',)))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve models by chi squared.')


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
    try:
        subtype = get_text_arg('subtype', label='subtype', required=True)
        fuv = get_float_arg('fuv', label='fuv', required=True)
        nuv = get_float_arg('nuv', label='nuv', required=True)
        grid = f'{subtype.lower()}_grid'
        models_weighted = get_models_with_weighted_fuv(nuv, fuv, grid)
        return api_success(serialize_model_collection(models_weighted, drop_fields=('_id', 'chi_squared_fuv', 'chi_squared_nuv')))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve models weighted by FUV.')


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
    try:
        subtype = get_text_arg('subtype', label='subtype', required=True)
        fuv = get_float_arg('fuv', label='fuv', required=True)
        nuv = get_float_arg('nuv', label='nuv', required=True)
        grid = f'{subtype.lower()}_grid'
        models_ratios = get_flux_ratios(nuv, fuv, grid)
        return api_success(serialize_model_collection(models_ratios, drop_fields=('_id', 'galex_flux_ratio', 'model_flux_ratio')))
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve models by flux ratio.')


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
    try:
        fits_filename = get_text_arg('fits_filename', label='fits_filename', required=True)
        current_app.logger.info('API get_model_data requested for filename=%s', fits_filename)
        return_data = {}
        if is_test_fits_filename(fits_filename):
            fits_bytes = get_test_fits_bytes(fits_filename)
        else:
            model_subtype = infer_model_subtype_from_filename(fits_filename)
            fits_bytes = get_model_fits_bytes(model_subtype, fits_filename)

        if fits_bytes is None:
            current_app.logger.info('API get_model_data could not find FITS data for filename=%s', fits_filename)
            return api_error('Data not yet available for that file.', status=404, code='not_found', field='fits_filename')

        with fits.open(io.BytesIO(fits_bytes)) as hst:
            data = hst[1].data
            return_data['wavelength_data'] = data['WAVELENGTH'][0].tolist()
            return_data['flux_data'] = data['FLUX'][0].tolist()
        current_app.logger.info('API get_model_data returned FITS payload for filename=%s', fits_filename)
        return api_success(return_data)
    except ApiValidationError as exc:
        return parse_api_validation_error(exc)
    except Exception:
        return parse_unexpected_api_error('Unable to retrieve model data.')