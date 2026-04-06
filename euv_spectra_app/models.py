# FOR ASTROQUERY/GALEX DATA
import logging
import numpy.ma as ma
import math
import requests
from astropy.time import Time
import astropy.units as u
from astroquery.exceptions import ResolverError
from astropy.coordinates import SkyCoord, Distance
from astroquery.mast import Catalogs
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from astroquery.simbad import Simbad
from pymongo.errors import PyMongoError
from euv_spectra_app.errors import CatalogLookupError, DataProcessingError, ModelSelectionError
from euv_spectra_app.extensions import db
from euv_spectra_app.helpers_dbqueries import get_matching_subtype, get_matching_photosphere, search_db, get_models_with_chi_squared, get_models_with_weighted_fuv, get_flux_ratios


logger = logging.getLogger(__name__)

customSimbad = Simbad()
customSimbad.remove_votable_fields('coordinates')
customSimbad.add_votable_fields(
    'ra', 'dec', 'pmra', 'pmdec', 'plx', 'rv_value', 'typed_id')

"""——————————————————————————————PROPER MOTION OBJECT——————————————————————————————"""   

class ProperMotionData():
    """Represents proper motion data of a stellar object."""
    def __init__(self, pm_ra=None, pm_dec=None, plx=None, rad_vel=None):
        self.pm_ra = pm_ra
        self.pm_dec = pm_dec
        self.plx = plx
        self.rad_vel = rad_vel

    def correct_pm(self, star_name, coords):
        """Corrects the given coordinates for proper motion using the GALEX observation time.

        Args:
            star_name (str): The name of the star to be queried on PEGASUS API.
            coords (tuple): A tuple containing two strings representing right ascension and declination.

        Returns:
            tuple: A tuple containing two floats representing the corrected right ascension and declination coordinates.

        Raises:
            TypeError: If the target star name is not found in the GALEX obs time collection (cannot get t_min)
            KeyError: If the target star name is not found in the GALEX obs time collection
            ValueError: If the star name is not a valid string to search with
            Exception: If an error occurs during coordinate correction or any other error occurs during galex search.
        """
        try:
            # STEP 1: Find a GALEX observation time from custom compiled dataset
            galex_time = db.mast_galex_times.find_one(
                {'target': star_name})['t_min']
        except TypeError as te:
            logger.warning('Missing GALEX observation time for %s: %s', star_name or coords, te)
            raise CatalogLookupError(
                f'GALEX Error: Did not find matches in GALEX observations for {star_name if star_name else coords}. Unable to correct for proper motion.',
                log_message=f'Missing GALEX observation time for {star_name or coords}: {te}',
                recoverable=True,
            ) from te
        except KeyError as ke:
            logger.warning('GALEX observation record missing t_min for %s: %s', star_name or coords, ke)
            raise CatalogLookupError(
                f'GALEX Error: Did not find matches in GALEX observations for {star_name if star_name else coords}. Unable to correct for proper motion.',
                log_message=f'GALEX observation record missing t_min for {star_name or coords}: {ke}',
                recoverable=True,
            ) from ke
        except ValueError as ve:
            logger.warning('Invalid GALEX observation lookup for %s: %s', star_name or coords, ve)
            raise CatalogLookupError(
                f'GALEX Error: Unable to search GALEX observations for {star_name if star_name else coords}. Unable to correct for proper motion.',
                log_message=f'Invalid GALEX observation lookup for {star_name or coords}: {ve}',
                recoverable=True,
            ) from ve
        else:
            try:
                # STEP 2: If observation time is found, start coordinate correction by initializing variables
                coordinates = coords[0] + ' ' + coords[1]
                skycoord_obj = ''
                # STEP 3: Calculate time difference between observation time and Jan 1st, 2000 (J2000)
                t3 = Time(galex_time, format='mjd') - \
                    Time(51544.0, format='mjd')
                # STEP 4: Convert time (which will return in seconds) into years
                td_year = t3.sec / 60 / 60 / 24 / 365.25
                # STEP 5: Check to see if radial velocity is given then create SkyCoord object with all data
                if self.rad_vel:
                    skycoord_obj = SkyCoord(coordinates, unit=(u.hourangle, u.deg), distance=Distance(parallax=self.plx*u.mas, allow_negative=True),
                                            pm_ra_cosdec=self.pm_ra*u.mas/u.yr, pm_dec=self.pm_dec*u.mas/u.yr, radial_velocity=self.rad_vel*u.km/u.s)
                else:
                    skycoord_obj = SkyCoord(coordinates, unit=(u.hourangle, u.deg), distance=Distance(
                        parallax=self.plx*u.mas, allow_negative=True), pm_ra_cosdec=self.pm_ra*u.mas/u.yr, pm_dec=self.pm_dec*u.mas/u.yr)
                # STEP 6: Use apply_space_motion function to calculate new coordinates
                skycoord_obj = skycoord_obj.apply_space_motion(
                    dt=td_year * u.yr)
                # STEP 7: Add new coordinates to return data dict
                return (skycoord_obj.ra.degree, skycoord_obj.dec.degree)
            except (TypeError, ValueError) as exc:
                logger.warning('Proper motion correction failed for %s: %s', star_name or coords, exc)
                raise DataProcessingError(
                    'Unable to correct coordinates for proper motion. Please enter GALEX flux values manually or try again later.',
                    log_message=f'Proper motion correction failed for {star_name or coords}: {exc}',
                ) from exc

"""——————————————————————————————GALEX FLUXES OBJECT——————————————————————————————"""   

class GalexFluxes():
    """Represents GALEX flux values."""

    def __init__(self, fuv=None, nuv=None, fuv_saturated=None, nuv_saturated=None, fuv_upper_limit=None, nuv_upper_limit=None, fuv_err=None, nuv_err=None, fuv_is_saturated=None, nuv_is_saturated=None, fuv_is_upper_limit=None, nuv_is_upper_limit=None, stellar_obj=None):
        self.fuv = fuv # GALEX FUV value (float)
        self.nuv = nuv # GALEX NUV value (float)
        self.fuv_saturated = fuv_saturated # GALEX FUV saturated value (float)
        self.nuv_saturated = nuv_saturated # GALEX NUV saturated value (float)
        self.fuv_upper_limit = fuv_upper_limit # GALEX FUV upper limit value (float)
        self.nuv_upper_limit = nuv_upper_limit # GALEX NUV upper limit value (float)
        self.fuv_err = fuv_err # GALEX FUV error value (float)
        self.nuv_err = nuv_err # GALEX NUV error value (float)
        self.fuv_is_saturated = fuv_is_saturated # Boolean indicating if GALEX FUV is saturated (bool)
        self.nuv_is_saturated = nuv_is_saturated # Boolean indicating if GALEX NUV is saturated (bool)
        self.fuv_is_upper_limit = fuv_is_upper_limit # Boolean indicating if GALEX FUV is upper limit (bool)
        self.nuv_is_upper_limit = nuv_is_upper_limit # Boolean indicating if GALEX NUV is upper limit (bool)
        self.stellar_obj = stellar_obj # The stellar object associated with the GALEX fluxes

    def has_attr_val(self, attr):
        if hasattr(self, attr) and getattr(self, attr) is not None:
            return True
        else:
            return False

    def check_null_fluxes(self):
        # check that absolutely all fluxes are None
        if (self.fuv is None or ma.is_masked(self.fuv)) and (self.nuv is None or ma.is_masked(self.nuv)) and self.fuv_saturated is None and self.nuv_saturated is None and self.fuv_upper_limit is None and self.nuv_upper_limit is None:
            # Absolutely all fluxes are none/null. Normal fluxes are none, saturated fluxes 
            # are none, and upper limit fluxes are None. Means no flux data was inputted 
            # and cannot continue.
            return ('No GALEX detections found.')
        elif (self.fuv is None or ma.is_masked(self.fuv)) and self.fuv_saturated is None and self.fuv_upper_limit is None:
            # No value for FUV in normal, saturated, or upper limit values.
            # FUV is null. Need to predict for FUV and add an error message to flash on modal (if on modal)
            if self.nuv_is_saturated:
                # If the non-null flux is saturated, use that value to predict
                # pass in None for the error because saturated vals do not have error
                self.predict_fluxes(self.nuv_saturated, None, 'fuv')
            elif self.nuv_is_upper_limit:
                # Else If the non-null flux is an upper limit, use that value to predict
                # pass in None for the error because upper limit vals do not have error
                self.predict_fluxes(self.nuv_upper_limit, None, 'fuv')
            else:
                # Else do regular prediction with NUV and error
                self.predict_fluxes(self.nuv, self.nuv_err, 'fuv')
            return ('GALEX FUV not detected. Predicting for FUV and FUV error.')
        elif (self.nuv is None or ma.is_masked(self.nuv)) and self.nuv_saturated is None and self.nuv_upper_limit is None:
            # No value for NUV in normal, saturated, or upper limit values.
            # NUV is null. Need to predict for NUV and add an error message to flash on modal (if on modal)
            if self.fuv_is_saturated:
                # If the non-null flux is saturated, use that value to predict
                # pass in None for the error because saturated vals do not have error
                self.predict_fluxes(self.fuv_saturated, None, 'nuv')
            elif self.fuv_is_upper_limit:
                # Else If the non-null flux is an upper limit, use that value to predict
                # pass in None for the error because upper limit vals do not have error
                self.predict_fluxes(self.fuv_upper_limit, None, 'nuv')
            else:
                # Else do regular prediction with FUV and error
                self.predict_fluxes(self.fuv, self.fuv_err, 'nuv')
            return ('GALEX NUV not detected. Predicting for NUV and NUV error.')

    def check_saturated_fluxes(self):
        """Checks if the FUV or NUV fluxes are saturated and corrects them if possible.

        If both the FUV and NUV fluxes are saturated, raises an exception and sets both
        fluxes to 'No Detection' and their errors to 'No Detection'. If only the FUV
        flux is saturated, predicts the corrected flux using the non-saturated NUV flux,
        updates the FUV flux and error, and returns the maximum flux and error between
        the predicted and original values. If only the NUV flux is saturated, predicts
        the corrected flux using the non-saturated FUV flux, updates the NUV flux and
        error, and returns the maximum flux and error between the predicted and original
        values. If none of the fluxes are saturated, prints a message and does nothing.

        Side effects: 
            If both fuv and nuv are saturated, sets values of fuv, fuv_err, nuv, and nuv_err of GalexFluxes object to 'No Detection'.
            If only fuv is saturated, may set values of fuv and fuv_err of GalexFluxes object.
            If only nuv is saturated, may set values of nuv and nuv_err of GalexFluxes object.

        Raises:
            ValueError if fuv_aper or nuv_aper is invalid.
            Exception if both fluxes are saturated.
        """
        try:
            # If a flux is saturated, do two options:
            # OPTION A: Search on the grid using saturated flux as a lower limit
            # Option B: Predict the actual flux and do normal search
                # for option B, check to see if you can predict 
                # (can only predict if other flux has values for both detection and error)
                # if you can't, just skip
                # if you can, we will only use the prediction if the predicted flux is greater 
                # than the saturated flux. If predicted flux is not greater than saturated flux, 
                # change flux and err to None so they will not be used
            if self.fuv_is_saturated:
                if self.nuv is not None and self.nuv_err is not None:
                    self.predict_fluxes(self.nuv, self.nuv_err, 'fuv')
                    if self.fuv < self.fuv_saturated:
                        self.fuv = None
                        self.fuv_err = None
            elif self.nuv_is_saturated:
                if self.fuv is not None and self.fuv_err is not None:
                    self.predict_fluxes(self.fuv, self.fuv_err, 'nuv')
                    if self.nuv < self.nuv_saturated:
                        self.nuv = None
                        self.nuv_err = None
        except ValueError as e:
            return ('Invalid `fuv_saturated`, `fuv_is_saturated` and/or `nuv_saturated`, `nuv_is_saturated` attributes:' + str(e))

    def check_upper_limit_fluxes(self):
        try:
            # If a flux is an upper limit, do two options:
            # OPTION A: Search on the grid using flux as an upper limit
            # Option B: Predict the actual flux and do normal search
                # for option B, check to see if you can predict 
                # (can only predict if other flux has values for both detection and error)
                # if you can't, just skip
                # if you can, we will only use the prediction if the predicted flux is less than 
                # the upper limit flux. If predicted flux is not less than the upper limit flux, 
                # change flux and err to None so they will not be used
                if self.fuv_is_upper_limit:
                    if self.nuv is not None and self.nuv_err is not None:
                        self.predict_fluxes(self.nuv, self.nuv_err, 'fuv')
                        if self.fuv > self.fuv_upper_limit:
                            self.fuv = None
                            self.fuv_err = None
                elif self.nuv_is_upper_limit:
                    if self.fuv is not None and self.fuv_err is not None:
                        self.predict_fluxes(self.fuv, self.fuv_err, 'nuv')
                        if self.nuv > self.nuv_upper_limit:
                            self.nuv = None
                            self.nuv_err = None
        except ValueError as e:
            return ('Invalid `fuv_upper_limit`, `fuv_is_upper_limit` and/or `nuv_upper_limit`, `nuv_is_upper_limit` attributes:' + str(e))

    def predict_early_ms_equation(self, flux_val, flux_type, unscale):
        """Runs the equation for the predicted flux value using other flux value for early M stars.

        This equation uses flux values scaled at 10 parsecs. The values given should already be scaled.
        The equation is then run depending on the flux type. The following equations that correspond to 
        flux types are:
            FUV = 10 ^ ( 1.17 * log10(NUV) - 1.26 )
            NUV = 10 ^ ( ( log10(FUV) + 1.26 ) / 1.17 )
        Then, these predicted flux values are 'unscaled', or scaled back to their original distances 
        with the given unscale value.

        Args:
            flux_val: The value of the flux that will be used in the prediction equation.
            flux_type: The flux you are predicting for. Will be either fuv or nuv.
            unscale: The unscale value that will be used to reverse original scaling. Calculated using 
                the equation (100 / (stellar distance^2))
        
        Returns:
            The final predicted flux value.
        
        Raises:
            No errors are raised but will return string error if the flux type is not nuv or fuv.
        """
        if flux_type == 'nuv':
            # Equation for predicting NUV
            return((pow(10, (( math.log10(flux_val) + 1.26 ) / 1.17 ))) * unscale)
        elif flux_type == 'fuv':
            # Equation for predicting FUV
            return((pow(10, ( 1.17 * math.log10(flux_val) - 1.26 ))) * unscale)
        else:
            return f'Can only correct for flux types: fuv, nuv. Please retry with one of these flux types.'
        
    def predict_late_ms_equation(self, flux_val, flux_type, unscale):
        """Runs the equation for the predicted flux value using other flux value for late M stars.

        This equation uses flux values scaled at 10 parsecs. The values given should already be scaled.
        The equation is then run depending on the flux type. The following equations that correspond to 
        flux types are:
            FUV = 10 ^ ( 0.98 * log10(NUV) - 0.47 )
            NUV = 10 ^ ( ( log10(FUV) + 0.47 ) / 0.98 )
        Then, these predicted flux values are 'unscaled', or scaled back to their original distances 
        with the given unscale value.

        Args:
            flux_val: The value of the flux that will be used in the prediction equation.
            flux_type: The flux you are predicting for. Will be either fuv or nuv.
            unscale: The unscale value that will be used to reverse original scaling. Calculated using 
                the equation (100 / (stellar distance^2))
        
        Returns:
            The final predicted flux value.
        
        Raises:
            No errors are raised but will return string error if the flux type is not nuv or fuv.
        """
        if flux_type == 'nuv':
            # Equation for predicting NUV
            return((pow(10, (( math.log10(flux_val) + 0.47 ) / 0.98 ))) * unscale)
        elif flux_type == 'fuv':
            # Equation for predicting FUV
            return((pow(10, ( 0.98 * math.log10(flux_val) - 0.47 ))) * unscale)
        else:
            return f'Can only correct for flux types: fuv, nuv. Please retry with one of these flux types.'

    def predict_early_ms(self, flux_val, flux_err, flux_type):
        """Predicts the values for given fluxes and errors for early M stars.

        The function scales the given flux value by 10 parsecs, then runs the prediction equation.
        The resulting predicted flux is assigned to an attribute of this object using the given
        flux type. The errors will also be predicted if an error is given using the same functionality
        described above.

        Args:
            flux_val: The value of the flux that will be used in the prediction equation.
                (Will be the non-null flux value).
            flux_err: The error of the flux that will be used in the prediction equation.
                (Will be the non-null flux value).
            flux_type: The flux you are predicting for. Will be either fuv or nuv.

        Side Effects:
            Sets the attribute corresponding with the given flux type to the predicted flux.
            If the flux error is given, will also set the attribute corresponding with the given
            flux type's error to the predicted error.     
        """
        # STEP 1: Scale GALEX flux densities to be at 10 parsecs equation: stellar_dist^2 / 100 
        # NOTE: the stellar distance needs to be in parsecs
        scale = ((pow(self.stellar_obj['dist'], 2)) / 100)
        scaled_flux = flux_val * scale
        # STEP 2: Calculate value to unscale the flux from 10 psc back to earth surface using
        # equation 100 / stellar_dist^2
        unscale = (100 / (pow(self.stellar_obj['dist'], 2)))
        # STEP 3: Solve for the missing flux, use the following equations
        pred_flux = self.predict_early_ms_equation(scaled_flux, flux_type, unscale)
        # STEP 4: Set the attribute of the flux you are predicting for to the flux returned from equation
        setattr(self, flux_type, pred_flux)
        # STEP 5: If an error is given, predict the error as well.
        if flux_err is not None:
            # Scale the upper and lower limits of the flux
            upper_lim_scaled = (flux_val + flux_err) * scale
            lower_lim_scaled = (flux_val - flux_err) * scale
            # Run prediction equation
            pred_upper_lim = self.predict_early_ms_equation(upper_lim_scaled, flux_type, unscale)
            pred_lower_lim = self.predict_early_ms_equation(lower_lim_scaled, flux_type, unscale)
            # Find new upper error and lower error
            new_upper_flux = pred_upper_lim - pred_flux
            new_lower_flux = pred_flux - pred_lower_lim
            # Take average to find new error
            pred_err = (new_upper_flux + new_lower_flux) / 2
            # Set the attribute of the flux error you are predicting for usign avg error
            which_err = f'{flux_type}_err'
            setattr(self, which_err, pred_err)

    def predict_late_ms(self, flux_val, flux_err, flux_type):
        """Predicts the values for given fluxes and errors for late M stars.

        The function scales the given flux value by 10 parsecs, then runs the prediction equation.
        The resulting predicted flux is assigned to an attribute of this object using the given
        flux type. The errors will also be predicted if an error is given using the same functionality
        described above.

        Args:
            flux_val: The value of the flux that will be used in the prediction equation.
                (Will be the non-null flux value).
            flux_err: The error of the flux that will be used in the prediction equation.
                (Will be the non-null flux value).
            flux_type: The flux you are predicting for. Will be either fuv or nuv.

        Side Effects:
            Sets the attribute corresponding with the given flux type to the predicted flux.
            If the flux error is given, will also set the attribute corresponding with the given
            flux type's error to the predicted error.     
        """
        # STEP 1: Scale GALEX flux densities to be at 10 parsecs equation: stellar_dist^2 / 100 
        # NOTE: the stellar distance needs to be in parsecs
        scale = ((pow(self.stellar_obj['dist'], 2)) / 100)
        scaled_flux = flux_val * scale
        # STEP 2: Calculate value to unscale the flux from 10 psc back to earth surface using
        # equation 100 / stellar_dist^2
        unscale = (100 / (pow(self.stellar_obj['dist'], 2)))
        # STEP 3: Solve for the missing flux, use the following equations
        pred_flux = self.predict_late_ms_equation(scaled_flux, flux_type, unscale)
        # STEP 4: Set the attribute of the flux you are predicting for to the flux returned from equation
        setattr(self, flux_type, pred_flux)
        # STEP 5: If an error is given, predict the error as well.
        if flux_err is not None:
            # Scale the upper and lower limits of the flux
            upper_lim_scaled = (flux_val + flux_err) * scale
            lower_lim_scaled = (flux_val - flux_err) * scale
            # Run prediction equation
            pred_upper_lim = self.predict_late_ms_equation(upper_lim_scaled, flux_type, unscale)
            pred_lower_lim = self.predict_late_ms_equation(lower_lim_scaled, flux_type, unscale)
            # Find new upper error and lower error
            new_upper_flux = pred_upper_lim - pred_flux
            new_lower_flux = pred_flux - pred_lower_lim
            # Take average to find new error
            pred_err = (new_upper_flux + new_lower_flux) / 2
            # Set the attribute of the flux error you are predicting for usign avg error
            which_err = f'{flux_type}_err'
            setattr(self, which_err, pred_err)

    def predict_fluxes(self, flux_val, flux_err, flux_type):
        """Predicts the specified flux based on the remaining GALEX flux values.

        Args:
            flux_val: The value of the flux that will be used in the prediction equation.
                (Will be the non-null flux value).
            flux_err: The error of the flux that will be used in the prediction equation.
                (Will be the non-null flux value).
            flux_type: The flux you are predicting for. Will be either fuv or nuv.

        Side Effects:
            If flux_type is 'fuv', sets fuv and fuv_err of GalexFluxes object.
            If flux_type is 'nuv', sets nuv and nuv_err of GalexFluxes object.
        """
        early_m = ['M0', 'M1', 'M2', 'M3', 'M4', 'M5']
        late_m = ['M6', 'M7', 'M8', 'M9', 'M5']
        # STEP 1: Check that stellar_subtype value exists
        if 'stellar_subtype' not in self.stellar_obj:
            logger.info('Skipping flux prediction because stellar subtype is unavailable.')
            return ('Cannot predict flux without stellar subtype. Please run the get_stellar_subtype function for your stellar object and try again.')
        elif self.stellar_obj['stellar_subtype'] in early_m:
            logger.debug('Using early-M flux prediction path.')
            self.predict_early_ms(flux_val, flux_err, flux_type)
        elif self.stellar_obj['stellar_subtype'] in late_m:
            logger.debug('Using late-M flux prediction path.')
            self.predict_late_ms(flux_val, flux_err, flux_type)
        else:
            logger.info('Skipping flux prediction for unsupported stellar subtype %s', self.stellar_obj['stellar_subtype'])
            return ('Can only run predictions on M stars at the moment.')

    def convert_mag_to_ujy(self, num, flux_type):
        if flux_type == 'fuv':
            # mag(AB) → erg/s/cm^2/A
            # FUV = ( ( (10^(mag-18.82))/-2.5 ) * (1.4*10^-15) )
            mag_to_flux = ((pow(10, ((num-18.82)/-2.5))) * (1.4e-15))
            # erg/s/cm^2/A → uJY
            flux_to_uJy = (((mag_to_flux * pow(1542.3, 2)) / (3e-5)) * (pow(10, 6)))
        elif flux_type == 'nuv':
            # mag(AB) → erg/s/cm^2/A
            # NUV = ( ( (10^(mag-20.08))/-2.5 ) * (2.06*10^-16) )
            mag_to_flux = ((pow(10, ((num-20.08)/-2.5))) * (2.06e-16))
            # erg/s/cm^2/A → uJY
            flux_to_uJy = (((mag_to_flux * pow(2274.4, 2)) / (3e-5)) * (pow(10, 6)))
        return flux_to_uJy

    def convert_ujy_to_flux_density(self, num, wv):
        """Converts microjanskies to ergs/s/cm2/A."""
        return (((3e-5) * (num * 10**-6)) / pow(wv, 2))

    def scale_flux(self, num):
        """Scales flux to stellar surface."""
        scale = (((self.stellar_obj['dist'] * 3.08567758e18)
                 ** 2) / ((self.stellar_obj['rad'] * 6.9e10)**2))
        return num * scale

    def get_photosphere_model(self):
        """Returns a PEGASUS photosphere model for photosphere subtraction."""
        try:
            matching_photosphere_model = get_matching_photosphere(
                self.stellar_obj['teff'], self.stellar_obj['logg'], self.stellar_obj['mass'])
            return matching_photosphere_model
        except (IndexError, KeyError, PyMongoError, TypeError) as exc:
            logger.warning('Unable to fetch photosphere model: %s', exc)
            return None

    def subtract_photosphere_flux(self, chosen_flux, photo_flux):
        """Subtracts the photospheric contributed flux from GALEX flux."""
        return chosen_flux - photo_flux
    
    def convert_scale_photosphere_subtract_single_flux(self, flux, flux_type):
        """Runs all calculations to process a GALEX flux to prepare for searching PEGASUS grid.

        Will run three processes on the given GALEX flux: 
            1. Converts the flux from microjanskies to ergs/s/cm2/A.
            2. Scales the flux to the stellar surface.
            3. Finds a matching photosphere model with the given stellar parameters and subtracts 
                photospheric flux contribution.
        
        Args:
            flux: The value of the given flux.
            flux_type: The type of the given flux. Will be either fuv or nuv.
        
        Returns:
            The final processed flux.
        # TODO Add type error catch
        """
        wv = None
        photo_flux = None
        photosphere_data = self.get_photosphere_model()
        if not isinstance(photosphere_data, dict):
            raise ValueError('Unable to retrieve photosphere model data from database.')
        if flux_type == 'fuv':
            wv = 1542.3
            photo_flux = photosphere_data['fuv']
        elif flux_type == 'nuv':
            wv = 2274.4
            photo_flux = photosphere_data['nuv']
        else:
            raise DataProcessingError('Can only process FUV or NUV flux values.')
        converted_flux = self.convert_ujy_to_flux_density(flux, wv)
        scaled_flux = self.scale_flux(converted_flux)
        photosub_flux = self.subtract_photosphere_flux(scaled_flux, photo_flux)
        return photosub_flux

    def convert_scale_photosphere_subtract_fluxes(self):
        """Runs all processing needed to search PEGASUS grid for each valid GALEX flux.

        Iterates through each attribute in the object and if it is valid flux, will run processes:
            1. Converts the flux from microjanskies to ergs/s/cm2/A.
            2. Scales the flux to the stellar surface.
            3. Finds a matching photosphere model with the given stellar parameters and subtracts 
                photospheric flux contribution.
        """
        for key, val in dict(vars(self)).items():
            processed_flux_name = f'processed_{key}'
            if ('fuv' in key or 'nuv' in key) and 'err' not in key and 'is' not in key and val is not None:
                if 'fuv' in key:
                    processed_flux = self.convert_scale_photosphere_subtract_single_flux(val, 'fuv')
                elif 'nuv' in key:
                    processed_flux = self.convert_scale_photosphere_subtract_single_flux(val, 'nuv')
                setattr(self, processed_flux_name, processed_flux)
            elif (key == 'fuv_err' or key == 'nuv_err') and val is not None:
                # get the attribute value with the name of which flux
                which_flux = key[:3]
                flux = getattr(self, which_flux)
                processed_flux = getattr(self, f'processed_{which_flux}')
                upper_lim = flux + val
                lower_lim = flux - val
                photosub_upper_lim = self.convert_scale_photosphere_subtract_single_flux(upper_lim, which_flux)
                photosub_lower_lim = self.convert_scale_photosphere_subtract_single_flux(lower_lim, which_flux)
                new_upper_err = photosub_upper_lim - processed_flux
                new_lower_err = processed_flux - photosub_lower_lim
                avg_err = (new_upper_err + new_lower_err) / 2
                setattr(self, processed_flux_name, avg_err)

"""——————————————————————————————STELLAR OBJECT——————————————————————————————"""

class StellarObject():
    """Represents a stellar object."""

    def __init__(self, star_name=None, position=None, coords=None, teff=None, logg=None, mass=None, dist=None, rad=None, pm_data=None, pm_corrected_coords=None, fluxes=None, stellar_subtype=None):
        self.star_name = star_name
        self.position = position
        self.coords = coords
        self.teff = teff
        self.logg = logg
        self.mass = mass
        self.dist = dist
        self.rad = rad
        self.pm_data = pm_data
        self.pm_corrected_coords = pm_corrected_coords
        self.fluxes = fluxes
        self.stellar_subtype = stellar_subtype
        self.modal_error_msgs = []
        if self.fluxes is None:
            self.fluxes = GalexFluxes()

    def has_all_stellar_parameters(self):
        # Checks to see that all stellar intrinstic parameters exist.
        if self.teff is not None and self.logg is not None and self.mass is not None and self.dist is not None and self.rad is not None:
            return True
        else:
            return False

    def get_stellar_parameters(self):
        """Searches Astroquery databases for stellar data.

        Searches SIMBAD, the NASA Exoplanet Archive, and MAST GALEX databases for 
        stellar data. Right ascension, declination, proper motion data, radial 
        velocity, and parallax are pulled from SIMBAD. Effective temperature, 
        surface gravity, mass, distance, and radius are pulled from the NASA 
        Exoplanet Archive. GALEX FUV and NUV flux density and the respective errors 
        are pulled from the MAST GALEX database. The data is used to populate the 
        resulting modal form.

        We check if each catalog/dataset search was successful by checking if the returned 
        data is None or not. If the search goes well, the searched catalog will assign 
        parameters in place and will return None. However, if the search does not run for 
        any reason, an error will be returned as a string error message. So, we check each 
        catalog search by checking if result of function call is None (search went well) or 
        not (error message is returned and we add that to modal error messages to return 
        on the user's front end.)

        Args:
            star_name OR position: The search term the user submitted in the search bar input.
            search_format: The format the search input is in, either name or position.

        Side Effects:
            If every function runs without errors, will assign teff, logg, mass, dist, rad, 
            fluxes, and stellar subtype.
            If the search is by star name, will assign proper motion data and proper motion 
            corrected coordinates.
            If the search is by position, will assign coordinates converted to RA and DEC.
            If an error occurs, will append to the modal galex error messages list.

        Raises:
            No errors are raised but if an error is detected from within a catalog search, the 
            function returns the error as a string and is sent to the front end error page to be displayed.
        """
        # STEP 1: Check for search type (position or name)
        if self.position:
            # STEP Pos1: Change coordinates to ra and dec
            try:
                self.convert_coords(self.position)
            except CatalogLookupError as exc:
                self.modal_page_error_msg = exc.user_message
                return
        elif self.star_name:
            # STEP Name1: Check if name is in the mast target database 
            # (used to check for case & spacing errors in user input)
            data = NasaExoplanetArchive.query_criteria(
                table="pscomppars", select="DISTINCT hostname")
            host_stars = data['hostname']
            for name in host_stars:
                # take away all spaces and make every letter upper case
                if self.star_name.upper().replace(' ', '') == name.upper().replace(' ', ''):
                    # if there is a match, assign the input star name to the correct format from NEA
                    self.star_name = name
                    break
            # STEP Name2: Get coordinate and proper motion info from Simbad
            try:
                self.query_simbad(self.star_name)
            except CatalogLookupError as exc:
                self.modal_error_msgs.append(exc.user_message)
            # STEP Name3: Put PM and Coord info into proper motion correction function
            if self.pm_data is not None:
                try:
                    self.pm_corrected_coords = self.pm_data.correct_pm(
                        self.star_name, self.coords)
                except (CatalogLookupError, DataProcessingError) as exc:
                    if exc.recoverable:
                        self.modal_error_msgs.append(exc.user_message)
                    else:
                        self.modal_page_error_msg = exc.user_message
                        return
        # STEP 2: Search NASA Exoplanet Archive with the search term & type
        nea_data = None
        try:
            self.query_nasa_exoplanet_archive(self.star_name, self.coords)
        except CatalogLookupError as exc:
            nea_data = exc
            self.modal_error_msgs.append(exc.user_message)
        # STEP 3: Get the stellar subtype. Needed for GALEX flux predictions if a flux is null
        if self.teff is not None and self.logg is not None and self.mass is not None:
            try:
                self.get_stellar_subtype(self.teff, self.logg, self.mass)
            except DataProcessingError as exc:
                self.modal_error_msgs.append(exc.user_message)
        # STEP 4: Check if coordinate correction happened then search GALEX with corrected/converted coords
        galex_data = None
        try:
            self.query_galex(self.star_name, self.position, self.pm_corrected_coords, self.coords)
        except CatalogLookupError as exc:
            galex_data = exc
            self.modal_error_msgs.append(exc.user_message)
        
        # STEP 5: Check that at least one main search returned data
        if nea_data is not None and galex_data is not None:
            # This means that no data was returned, redirect to error page with link to manual form
            self.modal_page_error_msg = 'Nothing found for your target in the NExSci database or the MAST GALEX database.'
            return
        
    def convert_coords(self, position):
        """Converts the position attribute to equatorial coordinates (coords attribute) using the SkyCoord class from the astropy.coordinates module.
        Args:
            position: The user's inputted position from search form.

        Side effects:
            Sets the coordinates of the stellar object.

        Raises:
            ValueError: If the position attribute is not in the expected format.
            TypeError: If the position attribute is not a string or a tuple of two strings.
            Exception: If an unknown error occurs during the coordinate conversion process.
        """
        try:
            c = SkyCoord(position, unit=(u.hourangle, u.deg))
            self.coords = (c.ra.degree, c.dec.degree)
            return
        except ValueError as ve:
            raise CatalogLookupError(
                f'Invalid position attribute: {ve}',
                log_message=f'Invalid position attribute {position}: {ve}',
            ) from ve
        except TypeError as te:
            raise CatalogLookupError(
                f'Invalid position attribute: {te}',
                log_message=f'Invalid position attribute {position}: {te}',
            ) from te

    def query_simbad(self, star_name):
        """Searches the SIMBAD astronomical database to retrieve data on a specified star.
        Args:
            star_name: The user's inputted star name from the search form.

        Side effects:
            Sets the coordinates and proper motion data of the stellar object.

        Raises:
            Request Exception: If SIMBAD is down, will throw flash error on modal telling user SIMBAD is down.
            Exception: If an error occurs during the SIMBAD search, or if no data is found for the specified star.
        """
        try:
            # Check if SIMBAD is accessible
            simbad_response = requests.get("http://simbad.cds.unistra.fr/simbad/")
            if simbad_response.status_code != 200:
                raise CatalogLookupError(
                    'Error connecting to SIMBAD. Cannot get data to correct for proper motion. Please enter GALEX flux values manually or try again later.',
                    log_message=f'SIMBAD health check returned status {simbad_response.status_code}',
                    recoverable=True,
                )
            
            result_table = customSimbad.query_object(star_name)
            if result_table and len(result_table) > 0:
                data = result_table[0]
                self.coords = (data['RA'], data['DEC'])
                self.pm_data = ProperMotionData(
                    data['PMRA'], data['PMDEC'], data['PLX_VALUE'])
                # check if radial velocity exists
                if not ma.is_masked(data['RV_VALUE']):
                    self.pm_data.rad_vel = data['RV_VALUE']
                return
            else:
                raise CatalogLookupError(
                    f'No results found in SIMBAD for {star_name}. Please check spelling, spacing, and or capitalization and try again.',
                    log_message=f'No SIMBAD result for {star_name}',
                    recoverable=True,
                )
        except requests.exceptions.RequestException as rqe:
            logger.warning('SIMBAD request failed for %s: %s', star_name, rqe)
            raise CatalogLookupError(
                'Error connecting to SIMBAD. Cannot get data to correct for proper motion. Please enter GALEX flux values manually or try again later.',
                log_message=f'SIMBAD request failed for {star_name}: {rqe}',
                recoverable=True,
            ) from rqe
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning('SIMBAD returned unusable data for %s: %s', star_name, exc)
            raise CatalogLookupError(
                'SIMBAD returned unusable target data. Please enter GALEX flux values manually or try again later.',
                log_message=f'SIMBAD returned unusable data for {star_name}: {exc}',
                recoverable=True,
            ) from exc

    def query_nasa_exoplanet_archive(self, star_name, coords):
        """Searches the NASA Exoplanet Archive for stellar parameters.

        Queries the NASA Exoplanet Archive (NExSci) for data on a given star_name or position and sets the attributes
        of the object to the retrieved data. Raises an exception if no results are found in the NExSci database
        for the given input parameters or if the spectral type of the star is not M or K.

        Args:
            star_name: The user's inputted star name from the search form.
            coords: The user's inputted coordinates from the search from, converted to RA and DEC.

        Side effects:
            Sets effective temperature (teff), surface gravity (logg), mass, distance (dist), and radius (rad)
            of the stellar object.

        Raises:
            Sends a string error message to the front end custom error page if no results
            are found or if the target is not a M or K type star.
            Request Exception: If the NASA Exoplanet Archive homepage is down.
            Exception: If any unknown error occurs during search.
        """
        try:
            nea_response = requests.get("https://exoplanetarchive.ipac.caltech.edu/")
            if nea_response.status_code != 200:
                raise CatalogLookupError(
                    'The NASA Exoplanet Archive is currently down. Please enter stellar parameters manually or try again later.',
                    log_message=f'NEA health check returned status {nea_response.status_code}',
                    recoverable=True,
                )
            
            if star_name:
                corrected_star_name = star_name.replace("'", "''")
                nea_data = NasaExoplanetArchive.query_criteria(
                    table="pscomppars", 
                    select="top 5 disc_refname, st_spectype, st_teff, st_logg, st_mass, st_rad, sy_dist, sy_jmag", 
                    where=f"hostname like '%{corrected_star_name}%'", 
                    order="hostname")
            elif coords:
                nea_data = NasaExoplanetArchive.query_region(table="pscomppars", coordinates=SkyCoord(
                    ra=coords[0] * u.deg, dec=coords[1] * u.deg), radius=1.0 * u.deg)
            if len(nea_data) > 0:
                data = nea_data[0]
                if 2400 < data['st_teff'].unmasked.value < 5500:
                    self.teff = data['st_teff'].unmasked.value
                    self.logg = data['st_logg']
                    self.mass = data['st_mass'].unmasked.value
                    self.rad = data['st_rad'].unmasked.value
                    self.dist = data['sy_dist'].unmasked.value
                    return
                else:
                    raise CatalogLookupError(
                        f'{star_name if star_name else coords} is not an M or K type star. Data is currently only available for these spectral sybtypes.',
                        log_message=f'Unsupported stellar type returned for {star_name or coords}',
                        recoverable=True,
                    )
            else:
                raise CatalogLookupError(
                    f'Nothing found for {star_name if star_name else coords} in the NExSci database.',
                    log_message=f'No NEA result for {star_name or coords}',
                    recoverable=True,
                )
        except requests.exceptions.RequestException as rqe:
            logger.warning('NEA request failed for %s: %s', star_name or coords, rqe)
            raise CatalogLookupError(
                'Error connecting to the NASA Exoplanet Archive. Please enter stellar parameters manually or try again later.',
                log_message=f'NEA request failed for {star_name or coords}: {rqe}',
                recoverable=True,
            ) from rqe
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning('NEA returned unusable data for %s: %s', star_name or coords, exc)
            raise CatalogLookupError(
                'Unable to use the NASA Exoplanet Archive response for this target. Please enter stellar parameters manually or try again later.',
                log_message=f'NEA returned unusable data for {star_name or coords}: {exc}',
                recoverable=True,
            ) from exc

    def query_galex(self, star_name, position, pm_corrected_coords, coords):
        """Searches the MAST GALEX database by coordinates for flux densities.

        Queries the MAST GALEX database for FUV and NUV flux densities and respective
        errors. If one flux density is missing, the other will be estimated with the
        predict_fluxes() method below.

        Args:
            star_name: The original star name user input from the search bar. Used to see if we should 
                query GALEX with pm_corrected_coords.
            position: The original position user input from the search bar. Used to see if we should 
                query GALEX with coords
            pm_corrected_coords: The proper motion corrected coordinates (RA and DEC) for a given star name.
            coords: RA and Dec to query the database.

        Side Effects:
            Sets GALEX FUV flux density, NUV flux density, FUV flux density error, and NUV flux
            density error for the stellar object's GalexFlux object.
            Will also set saturated and/or upper limits flags and fluxes for the stellar object's 
            GalexFlux object if they exist.

        Raises:
            Sends a string error message if no results are found to be displayed on the
            modal form so users can still enter fluxes manually and get other stellar
            information back.
        """
        # STEP 1: Query the MAST catalogs object by GALEX catalog & given ra and dec
        try:
            # Check if SIMBAD is accessible
            mast_response = requests.get("https://galex.stsci.edu/GR6/?page=mastform")
            if mast_response.status_code != 200:
                raise CatalogLookupError(
                    'Error connecting to MAST. Please enter GALEX flux values manually or try again later.',
                    log_message=f'MAST health check returned status {mast_response.status_code}',
                    recoverable=True,
                )
            
            galex_data = None
            if star_name and pm_corrected_coords:
                # if the original query was by star name and the proper motion corrected coords exist
                galex_data = Catalogs.query_object(
                    f'{pm_corrected_coords[0]} {pm_corrected_coords[1]}', catalog="GALEX")
            elif position and coords:
                # elif the original query was by position and the coords exist
                galex_data = Catalogs.query_object(
                    f'{coords[0]} {coords[1]}', catalog="GALEX")
            # STEP 2: If there are results returned and results within 0.167 arcmins, then start processing the data.
            if galex_data is not None:
                if len(galex_data) > 0:
                    # Set minimum distance between target coordinates and actual coordinates of object.
                    MIN_DIST = galex_data['distance_arcmin'] < 0.167
                    if len(galex_data[MIN_DIST]) > 0:
                        filtered_data = galex_data[MIN_DIST][0]
                        # create new fluxes object to store data in if there isn't one yet
                        if self.fluxes is None:
                            self.fluxes = GalexFluxes()
                        # STEP 3: Assign the edited stellar object to the flux object
                        # delete any objects within stellar object and assign this to the flux object's stellar object
                        # this is done so the flux object can access attributes from the stellar object such as teff, logg, and mass
                        fluxes_stell_obj = self.__dict__.copy()
                        del fluxes_stell_obj['fluxes']
                        del fluxes_stell_obj['pm_data']
                        self.fluxes.stellar_obj = fluxes_stell_obj
                        # STEP 4: Assign fuv, nuv, and error to flux object
                        self.fluxes.fuv = filtered_data['fuv_flux']
                        self.fluxes.nuv = filtered_data['nuv_flux']
                        self.fluxes.fuv_err = filtered_data['fuv_fluxerr']
                        self.fluxes.nuv_err = filtered_data['nuv_fluxerr']
                        # STEP 5: Check for saturated fluxes
                        if not ma.is_masked(filtered_data['fuv_flux_aper_7']) and filtered_data['fuv_flux_aper_7'] > 34:
                            self.fluxes.fuv_is_saturated = True
                            self.fluxes.fuv_saturated = filtered_data['fuv_flux']
                        if not ma.is_masked(filtered_data['nuv_flux_aper_7']) and filtered_data['nuv_flux_aper_7'] > 108:
                            self.fluxes.nuv_is_saturated = True
                            self.fluxes.nuv_saturated = filtered_data['nuv_flux']
                        # STEP 6: Check if there are any masked values (these will be null values)
                        null_fluxes = self.fluxes.check_null_fluxes()
                        if null_fluxes is not None:
                            self.modal_error_msgs.append(null_fluxes)
                        saturated_fluxes = self.fluxes.check_saturated_fluxes()
                        if saturated_fluxes is not None:
                            self.modal_error_msgs.append(saturated_fluxes)
                        return
                    else:
                        # No results within 0.167 arc minutes
                        raise CatalogLookupError(
                            'GALEX Error: No detection in GALEX FUV and NUV. Look under question 3 on the FAQ page for more information.',
                            log_message=f'GALEX returned no close match for {star_name or coords}',
                            recoverable=True,
                        )
                else:
                    # No results found for the GALEX catalog query
                    raise CatalogLookupError(
                        'GALEX Error: No GALEX observations found. Please enter flux values manually or approximate flux values using the proxy table under question 3 on the FAQ page.',
                        log_message=f'GALEX returned no observations for {star_name or coords}',
                        recoverable=True,
                    )
            else:
                # No results found because proper info was not given for example, will happen if 
                # proper motion correction did not occur and is therefore not given
                raise CatalogLookupError(
                    f'GALEX Error: Missing data to query GALEX {"because coordinates were not corrected for proper motion" if star_name else f"for {coords}"}. Please enter flux values manually or approximate flux values using the proxy table under question 3 on the FAQ page.',
                    log_message=f'GALEX query missing coordinates for {star_name or coords}',
                    recoverable=True,
                )
        except requests.exceptions.RequestException as rqe:
            logger.warning('MAST request failed for %s: %s', star_name or coords, rqe)
            raise CatalogLookupError(
                'Error connecting to MAST. Please enter GALEX flux values manually or try again later.',
                log_message=f'MAST request failed for {star_name or coords}: {rqe}',
                recoverable=True,
            ) from rqe
        except ResolverError as re:
            logger.warning('GALEX resolver error for %s: %s', star_name or coords, re)
            raise CatalogLookupError(
                f'GALEX Error: Could not search GALEX catalog with object {coords if position else pm_corrected_coords}. Please enter flux values manually or approximate flux values using the proxy table under question 3 on the FAQ page.',
                log_message=f'GALEX resolver error for {star_name or coords}: {re}',
                recoverable=True,
            ) from re
        except ValueError as ve:
            logger.warning('GALEX search received invalid data for %s: %s', star_name or coords, ve)
            raise CatalogLookupError(
                f'GALEX Error: Could not search GALEX catalog with object {coords if position else pm_corrected_coords}. Please enter flux values manually or approximate flux values using the proxy table under question 3 on the FAQ page.',
                log_message=f'GALEX search received invalid data for {star_name or coords}: {ve}',
                recoverable=True,
            ) from ve
        except (TypeError, KeyError) as exc:
            logger.warning('GALEX returned unusable data for %s: %s', star_name or coords, exc)
            raise CatalogLookupError(
                'GALEX returned unusable flux data for this target. Please enter flux values manually or try again later.',
                log_message=f'GALEX returned unusable data for {star_name or coords}: {exc}',
                recoverable=True,
            ) from exc
    
    def get_stellar_subtype(self, teff, logg, mass):
        """Assigns the matching PEGASUS grid stellar subtype to object.

        Args:
            teff: The stellar effective temp (K) of the current stellar object.
            logg: The surface gravity of the current stellar object.
            mass: The mass (in solar masses) of the current stellar object.
        
        Side Effects:
            Sets the object's stellar_subtype attribute.

        Raises:
            TypeError if no subtype was returned from query.
            Exception if any unknown error occurs.
        """
        try:
            matching_subtype = get_matching_subtype(teff, logg, mass)
            try:
                self.stellar_subtype = matching_subtype['model']
            except TypeError as te:
                logger.warning('Subtype record missing model for teff=%s logg=%s mass=%s: %s', teff, logg, mass, te)
                raise DataProcessingError(
                    f'No PEGASUS subtype found with inputs: teff={teff}, logg={logg}, and mass={mass}. Please check your input(s) and try again, or manually input your values on the home page manual form.',
                    log_message=f'Subtype record missing model for teff={teff} logg={logg} mass={mass}: {te}',
                    recoverable=True,
                ) from te
        except (IndexError, KeyError, PyMongoError, TypeError) as exc:
            logger.warning('Unable to find stellar subtype for teff=%s logg=%s mass=%s: %s', teff, logg, mass, exc)
            raise DataProcessingError(
                f'Unable to find stellar subtype with inputs: teff={teff}, logg={logg}, and mass={mass}. Please check your input and try again, or manually input your values on the home page manual form.',
                log_message=f'Unable to find stellar subtype for teff={teff} logg={logg} mass={mass}: {exc}',
                recoverable=True,
            ) from exc

"""——————————————————————————————PEGASUS GRID OBJECT——————————————————————————————"""   

class PegasusGrid():
    """Represents the PEGASUS grid"""

    def __init__(self, stellar_obj=None):
        self.stellar_obj = stellar_obj

    def query_pegasus_subtype(self):
        """Queries pegasus for stellar subtype based on stellar parameters.
        """
        try:
            matching_subtype = get_matching_subtype(
                self.stellar_obj.teff, self.stellar_obj.logg, self.stellar_obj.mass)
            self.stellar_obj.model_collection = f"{matching_subtype['model'].lower()}_grid"
            return matching_subtype
        except (IndexError, KeyError, PyMongoError, TypeError) as exc:
            logger.warning('Unable to determine PEGASUS subtype for current stellar object: %s', exc)
            raise ModelSelectionError(
                'Unable to determine a PEGASUS model subtype for the submitted stellar parameters.',
                log_message=f'Unable to determine PEGASUS subtype: {exc}',
            ) from exc
    
    def query_model_collection(self, fuv, nuv):
        try:
            models = search_db(self.stellar_obj.model_collection, fuv, nuv)
            return list(models)
        except (PyMongoError, TypeError, ValueError, KeyError) as exc:
            logger.warning('Unable to query model collection %s: %s', getattr(self.stellar_obj, 'model_collection', None), exc)
            raise ModelSelectionError(
                'Unable to query PEGASUS models for the submitted flux values.',
                log_message=f'Unable to query model collection {getattr(self.stellar_obj, "model_collection", None)}: {exc}',
            ) from exc

    def query_pegasus_chi_square(self):
        """Queries pegasus models based on chi square of fuv and nuv flux densities.
        """
        try:
            model_with_chi_squared = get_models_with_chi_squared(
                self.stellar_obj.fluxes.processed_nuv, self.stellar_obj.fluxes.processed_fuv, self.stellar_obj.model_collection)
            return list(model_with_chi_squared)
        except (PyMongoError, TypeError, ValueError, KeyError) as exc:
            logger.warning('Unable to calculate chi-squared PEGASUS models: %s', exc)
            raise ModelSelectionError(
                'Unable to rank PEGASUS models for the submitted flux values.',
                log_message=f'Unable to calculate chi-squared PEGASUS models: {exc}',
            ) from exc

    def query_pegasus_weighted_fuv(self):
        """Queries pegasus models based on weighted FUV and chi square.
        """
        try:
            models_weighted = get_models_with_weighted_fuv(
                self.stellar_obj.fluxes.processed_nuv, self.stellar_obj.fluxes.processed_fuv, self.stellar_obj.model_collection)
            return models_weighted
        except (PyMongoError, TypeError, ValueError, KeyError) as exc:
            logger.warning('Unable to calculate weighted-FUV PEGASUS models: %s', exc)
            raise ModelSelectionError(
                'Unable to rank PEGASUS models for the submitted flux values.',
                log_message=f'Unable to calculate weighted-FUV PEGASUS models: {exc}',
            ) from exc

    def query_pegasus_flux_ratio(self):
        """Queries pegasus models based on chi square of flux ratio.
        """
        try:
            models_with_ratios = get_flux_ratios(
                self.stellar_obj.fluxes.processed_nuv, self.stellar_obj.fluxes.processed_fuv, self.stellar_obj.model_collection)
            return list(models_with_ratios)
        except (PyMongoError, TypeError, ValueError, KeyError) as exc:
            logger.warning('Unable to calculate flux-ratio PEGASUS models: %s', exc)
            raise ModelSelectionError(
                'Unable to rank PEGASUS models for the submitted flux values.',
                log_message=f'Unable to calculate flux-ratio PEGASUS models: {exc}',
            ) from exc
