# FOR ASTROQUERY/GALEX DATA
from euv_spectra_app.extensions import db
import numpy.ma as ma
from astropy.time import Time
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance
from astroquery.mast import Catalogs
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from astroquery.simbad import Simbad

# Set global astroquery timeouts
Simbad.TIMEOUT = 30       # 30 seconds
Catalogs.TIMEOUT = 30     # 30 seconds

customSimbad = Simbad()
customSimbad.remove_votable_fields('coordinates')
customSimbad.add_votable_fields(
    'ra', 'dec', 'pmra', 'pmdec', 'plx', 'rv_value', 'typed_id')


class StellarTarget():
    """Represents a stellar object."""

    def __init__(self, star_name=None, position=None, coordinates=None, teff=None, logg=None, mass=None, dist=None, rad=None, proper_motion_data=None, fluxes=None, j_band=None):
        self.star_name = star_name
        self.position = position

        self.coordinates = coordinates
        self.teff = teff
        self.logg = logg
        self.mass = mass
        self.dist = dist
        self.rad = rad

        self.proper_motion_data = proper_motion_data
        self.fluxes = fluxes

        # self.fuv = fuv
        # self.fuv_err = fuv_err
        # self.nuv = nuv
        # self.nuv_err = nuv_err

        self.j_band = j_band

    def search_dbs(self):
        """Searches Astroquery databases for stellar data.

        Searches SIMBAD, the NASA Exoplanet Archive, and MAST GALEX databases for 
        stellar data. Right ascension, declination, proper motion data, radial 
        velocity, parallax, and J band 2MASS magnitude are pulled from SIMBAD. 
        Effective temperature, surface gravity, mass, distance, and radius are pulled 
        from the NASA Exoplanet Archive. GALEX FUV and NUV flux density and the 
        respective errors are pulled from the MAST GALEX database. The data is used to 
        populate the resulting modal form.

        Args:
            star_name OR position: The search term the user submitted in the search bar input.
            search_format: The format the search input is in, either name or position.

        Returns:
            Stellar parameters with cooresponding values to be passed to the modal form

        Raises:
            No errors are raised but if an error is detected, the function returns None and
            an error message is sent to the front end error page to be displayed.
        """

        # STEP 1: Check for search type (position or name)
        if self.position:
            # STEP P1: Change coordinates to ra and dec
            converted_coords = self.convert_coords()
            if converted_coords != None:
                self.modal_error_msg = converted_coords
                return
        elif self.star_name:
            # STEP N1: Check if name is in the mast target database (meant to check for case & spacing errors)
            data = NasaExoplanetArchive.query_criteria(
                table="pscomppars", select="DISTINCT hostname")
            host_stars = data['hostname']
            for name in host_stars:
                if self.star_name.upper().replace(' ', '') == name.upper().replace(' ', ''):
                    self.star_name = name
                    break
            # STEP N2: Get coordinate and motion info from Simbad
            simbad_data = self.search_simbad()
            if simbad_data != None:
                self.modal_error_msg = simbad_data
                return

            # self.test_tic()
            # STEP N3: Put PM and Coord info into correction function
            pm_corrected_coords = self.proper_motion_data.correct_pm(
                self.star_name, self.coordinates)
            if isinstance(pm_corrected_coords, tuple):
                self.coordinates = pm_corrected_coords
            else:
                self.modal_error_msg = pm_corrected_coords
                if 'GALEX' not in pm_corrected_coords:
                    return
        # STEP 2: Search NASA Exoplanet Archive with the search term & type
        nea_data = self.search_nea()
        if nea_data != None:
            self.modal_error_msg = nea_data
            return
        # STEP 3: Check if coordinate correction happened (if it didn't there would be
            # GALEX error model error message), then search GALEX with corrected/converted
            # coords
        self.search_galex()

    def convert_coords(self):
        """Converts coordinates to right ascension and declination.

        Takes in position as inputted into the search bar and converts to ra and dec.

        Args:
            position: A coordinate value not already in ra and dec format.

        Returns:
            Coordinates in ra and dec computed from a skycoord object.

        Raises:
            String error message detailing the coordinates could not be converted.
        """
        try:
            # create a skycoord object
            c = SkyCoord(self.position, unit=(u.hourangle, u.deg))
            # get ra and dec from skycoord object
            self.coordinates = (c.ra.degree, c.dec.degree)
            return
        except:
            return f'Error converting your coordinates {self.position}. \nPlease check your format and try again.'

    def search_simbad(self):
        """Searches SIMBAD by name for stellar data.

        Args:
            star_name: The stellar object name of a stellar object.

        Returns:
            Right ascension, declination, proper motion in RA and Dec, parallax, and radial
            velocity.

        Raises:
            A string detailing that SIMBAD coulld not find any object under the inputted name.
        """
        result_table = customSimbad.query_object(self.star_name)
        if result_table and len(result_table) > 0:
            data = result_table[0]
            self.coordinates = (data['RA'], data['DEC'])
            self.proper_motion_data = ProperMotionDataOld(
                data['PMRA'], data['PMDEC'], data['PLX_VALUE'])
            # check if radial velocity exists
            if ma.is_masked(data['RV_VALUE']):
                return
            else:
                self.proper_motion_data.radial_velocity = data['RV_VALUE']
            return
        else:
            return f'No target found for {self.star_name} in Simbad. \nPlease check spelling or coordinate format.'

    def search_nea(self):
        """Searches the NASA Exoplanet Archive for stellar parameters.

        Args:
            star_name OR position: Object (string) or coordinates to query by.
            search_format: Will be position or name.

        Returns:
            Stellar parameters including effective temperature (teff), surface gravity
            (logg), mass (mass), distance (dist), radius (rad), and 2MASS J band magnitude
            to be used for GALEX flux predictions if needed.

        Raises:
            Sends a string error message to the front end custom error page if no results
            are found or if the target is not a M or K type star.
        """
        if self.star_name:
            nea_data = NasaExoplanetArchive.query_criteria(
                table="pscomppars", select="top 5 disc_refname, st_spectype, st_teff, st_logg, st_mass, st_rad, sy_dist, sy_jmag", where=f"hostname like '%{self.star_name}%'", order="hostname")
        elif self.position:
            nea_data = NasaExoplanetArchive.query_region(table="pscomppars", coordinates=SkyCoord(
                ra=self.coordinates[0] * u.deg, dec=self.coordinates[1] * u.deg), radius=1.0 * u.deg)
        if len(nea_data) > 0:
            data = nea_data[0]
            if 2400 < data['st_teff'].unmasked.value < 5500:
                # if 'M' in data['st_spectype'] or 'K' in data['st_spectype']:
                self.teff = data['st_teff'].unmasked.value
                # handle dex unit safely:
                try:
                    logg_val = data['st_logg']
                    if hasattr(logg_val, 'unmasked'):
                        logg_val = logg_val.unmasked
                    if hasattr(logg_val, 'value'):
                        self.logg = float(logg_val.value)
                    else:
                        self.logg = float(logg_val)
                except Exception as e:
                    print(f'Warning: could not parse st_logg: {e}')
                    self.logg = None
                self.mass = data['st_mass'].unmasked.value
                self.rad = data['st_rad'].unmasked.value
                self.dist = data['sy_dist'].unmasked.value
                self.j_band = data['sy_jmag'].unmasked.value
            else:
                return f'{self.star_name} is not an M or K type star. Data is currently only available for these spectral sybtypes. \nPlease contact us with your target and parameters if you think this is a mistake.'
        else:
            error_term = ''
            if self.star_name:
                error_term = self.star_name
            elif self.position:
                error_term = self.position
            return f'Nothing found for {error_term} in the NExSci database. <br>\
                     At this time, retrieved input parameters are only available for known exoplanet host stars with 2500 K < Teff < 5044 K. <br>\
                     If {error_term} is a known exoplanet host star, please check spelling or coordinates and resubmit, or enter the input parameters manually via <a href="{{ url_for(\'main.homepage\', form=\'extended\') }}">this form</a>. <br>\
                     If {error_term} is not a known exoplanet host star, please enter the input parameters manually via <a href="{{ url_for(\'main.homepage\', form=\'extended\') }}">this form</a>.'

    def search_galex(self):
        """Searches the MAST GALEX database by coordinates for flux densities.

        Queries the MAST GALEX database for FUV and NUV flux densities and respective
        errors. If one flux density is missing, the other will be estimated with the
        predict_fluxes() method below.

        Args:
            coordinates: RA and Dec to query the database.

        Returns:
            GALEX FUV flux density, NUV flux density, FUV flux density error, and NUV flux
            density error.

        Raises:
            Sends a string error message if no results are found to be displayed on the
            modal form so users can still enter fluxes manually and get other stellar
            information back.
        """
        # STEP 1: Query the MAST catalogs object by GALEX catalog & given ra and dec
        try:
            galex_data = Catalogs.query_object(
                f'{self.coordinates[0]} {self.coordinates[1]}', catalog="GALEX")
            # STEP 2: If there are results returned and results within 0.167 arcmins, then start processing the data.
            if len(galex_data) > 0:
                # Set minimum distance between target coordinates and actual coordinates of object.
                MIN_DIST = galex_data['distance_arcmin'] < 0.167
                if len(galex_data[MIN_DIST]) > 0:
                    filtered_data = galex_data[MIN_DIST][0]
                    nuv_is_saturated = filtered_data['nuv_flux_aper_7'] > 108
                    fuv_is_saturated = filtered_data['fuv_flux_aper_7'] > 34
                    self.fluxes = GalexFluxesOld(filtered_data['fuv_flux'], filtered_data['fuv_fluxerr'], filtered_data['nuv_flux'], filtered_data['nuv_fluxerr'], ((
                        (self.dist * 3.08567758e18)**2) / ((self.rad * 6.9e10)**2)))
                    self.fuv = filtered_data['fuv_flux']
                    self.nuv = filtered_data['nuv_flux']
                    self.fuv_err = filtered_data['fuv_fluxerr']
                    self.nuv_err = filtered_data['nuv_fluxerr']
                    # STEP 3: Check if there are any masked values (these will be null values) and change accordingly
                    # if ma.is_masked(self.fuv) and ma.is_masked(self.nuv):
                    if ma.is_masked(self.fluxes.fuv) and ma.is_masked(self.fluxes.nuv):
                        # both are null, point to null placeholders and add error message
                        self.fuv, self.nuv, self.fuv_err, self.nuv_err = 'No Detection', 'No Detection', 'No Detection', 'No Detection'
                        self.fluxes.fuv, self.fluxes.nuv, self.fluxes.fuv_err, self.fluxes.nuv_err = 'No Detection', 'No Detection', 'No Detection', 'No Detection'
                        return 'No detection in GALEX FUV and NUV. \nLook under question 3 on the FAQ page for more information.'
                    elif ma.is_masked(self.fluxes.fuv):
                        # only FUV is null, predict FUV and add error message
                        self.predict_fluxes('fuv')
                        self.fluxes.predict_fluxes('fuv', self.j_band)
                        self.modal_error_msg = 'No detection in GALEX FUV, substitution is calculated for you. \nLook under question 3 on the FAQ page for more information.'
                    elif ma.is_masked(self.fluxes.nuv):
                        # only NUV is null, predict NUV and add error message
                        self.predict_fluxes('nuv')
                        self.fluxes.predict_fluxes('nuv', self.j_band)
                        self.modal_error_msg = 'No detection in GALEX NUV, substitution is calculated for you. \nLook under question 3 on the FAQ page for more information.'
                    elif fuv_is_saturated:
                        # FUV is saturated
                        # predict flux and compare predicted flux to actual flux
                        # return whatever is higher
                        self.predict_fluxes('fuv')
                        fuv_fluxes = [self.fuv,
                                      filtered_data['fuv_flux']]
                        fuv_errors = [self.fuv_err,
                                      filtered_data['fuv_fluxerr']]
                        self.fuv = max(fuv_fluxes)
                        self.fuv_err = max(fuv_errors)

                        self.fluxes.predict_fluxes('fuv', self.j_band)
                        fuv_fluxes = [self.fluxes.fuv,
                                      filtered_data['fuv_flux']]
                        fuv_errors = [self.fluxes.fuv_err,
                                      filtered_data['fuv_fluxerr']]
                        self.fluxes.fuv = max(fuv_fluxes)
                        self.fluxes.fuv_err = max(fuv_errors)
                        self.modal_error_msg = 'GALEX FUV flux density is saturated. If submitted, we will treat it as a lower limit.'
                    elif nuv_is_saturated:
                        # NUV is saturated
                        # predict flux and compare predicted flux to actual flux
                        # return whatever is higher
                        self.predict_fluxes('nuv')
                        nuv_fluxes = [self.fuv,
                                      filtered_data['nuv_flux']]
                        nuv_errors = [self.fuv_err,
                                      filtered_data['nuv_fluxerr']]
                        self.nuv = max(nuv_fluxes)
                        self.nuv_err = max(nuv_errors)

                        self.fluxes.predict_fluxes('nuv')
                        nuv_fluxes = [self.fluxes.fuv,
                                      filtered_data['nuv_flux']]
                        nuv_errors = [self.fluxes.fuv_err,
                                      filtered_data['nuv_fluxerr']]
                        self.fluxes.nuv = max(nuv_fluxes)
                        self.fluxes.nuv_err = max(nuv_errors)
                        self.modal_error_msg = 'GALEX NUV flux density is saturated. If submitted, we will treat it as a lower limit.'
                else:
                    self.modal_error_msg = 'No detection in GALEX FUV and NUV. \nLook under question 3 on the FAQ page for more information.'
            else:
                self.modal_error_msg = 'No GALEX observations found, unable to correct coordinates. \nLook under question 3 on the FAQ page for more information.'
        except:
            self.modal_error_msg = 'Unable to query MAST, the server may be down. Please try again later.'

    def predict_fluxes(self, flux_type):
        """Calculates a predicted flux if the value is missing from GALEX.

        Args:
            flux_type: Either fuv or nuv, specified to know which equation to use.

        Returns:
            A predicted nuv or fuv flux value and corresponding error.
        """
        # STEP 1: Convert J band 2MASS magnitude to microjanskies
        ZEROPOINT = 1594
        j_band_ujy = 1000 * (ZEROPOINT * pow(10.0, -0.4 * self.j_band))
        # STEP 3: Use equation to predict missing flux & error
        if flux_type == 'nuv':
            upper_lim = self.fuv + self.fuv_err
            lower_lim = self.fuv - self.fuv_err
            # Predict NUV flux using NUV = ((FUV/J)^(1/1.1)) * J
            # STEP N1: Use equation to find upper, lower limits and new flux values
            new_nuv_upper_lim = (
                pow((upper_lim / j_band_ujy), (1 / 1.1))) * j_band_ujy
            new_nuv = (pow((self.fuv / j_band_ujy), (1 / 1.1))) * j_band_ujy
            new_nuv_lower_lim = (
                pow((lower_lim / j_band_ujy), (1 / 1.1))) * j_band_ujy
            # STEP N2: Find the differences between the upper and lower limits and flux value (these will be error)
            #  Then calculate average of these values to get the average error
            upper_nuv = new_nuv_upper_lim - new_nuv
            lower_nuv = new_nuv - new_nuv_lower_lim
            avg_nuv_err = (upper_nuv + lower_nuv) / 2
            # STEP N3: Assign new values to return data dict using calculated flux & error
            self.nuv = new_nuv
            self.nuv_err = avg_nuv_err
        elif flux_type == 'fuv':
            upper_lim = self.nuv + self.nuv_err
            lower_lim = self.nuv - self.nuv_err
            # Predict FUV flux using FUV = ((NUV/J)^1.11) * J
            # STEP F1: Use equation to find upper, lower limits and new flux values
            new_fuv_upper_lim = (
                pow((upper_lim / j_band_ujy), 1.1)) * j_band_ujy
            new_fuv = (pow((self.nuv / j_band_ujy), 1.1)) * j_band_ujy
            new_fuv_lower_lim = (
                pow((lower_lim / j_band_ujy), 1.1)) * j_band_ujy
            # STEP F2: Find the differences between the upper and lower limits and flux value (these will be error)
            #  Then calculate average of these values to get the average error
            upper_fuv = new_fuv_upper_lim - new_fuv
            lower_fuv = new_fuv - new_fuv_lower_lim
            avg_fuv_err = (upper_fuv + lower_fuv) / 2
            # STEP N3: Assign new values to return data dict using calculated flux & error
            self.fuv = new_fuv
            self.fuv_err = avg_fuv_err


class ProperMotionDataOld():

    def __init__(self, pmra=None, pmdec=None, parallax=None, radial_velocity=None):
        self.pmra = pmra
        self.pmdec = pmdec
        self.parallax = parallax
        self.radial_velocity = radial_velocity

    def correct_pm(self, star_name, coordinates):
        """Corrects coordinates for proper motion.

        Takes in a set of coordinates and a stellar object. Searches our custom 
        database of GALEX observation times and pulls an observation time matching to
        the target name. A skycoord object is created using coordinates and proper 
        motion data pulled from SIMBAD. The AstroPy apply_space_motion function is used
        with a time difference between Jan 1st, 2000 and the GALEX observation time to
        calculate the new coordinate position during the GALEX observation. These
        coordinates are used to search GALEX for a more accurate match.

        Args:
            star_name: The stellar object name input from the search bar.
            coordinates: RA and Dec of target stellar object pulled from SIMBAD.

        Returns:
            RA and Dec corrected for proper motion between Jan 1, 2000 and GALEX observation time.

        Raises:
            A string error passed to the error front end page for display if there is no
            GALEX observation for the target in our database or if coordinate correction
            fails for any reason.
        """
        try:
            # STEP 1: Find a GALEX observation time from custom compiled dataset
            galex_time = db.mast_galex_times.find_one(
                {'target': star_name})['t_min']
        except:
            return 'No GALEX observations found, unable to correct coordinates. \nLook under question 3 on the FAQ page for more information.'
        else:
            try:
                # STEP 2: If observation time is found, start coordinate correction by initializing variables
                coords = coordinates[0] + ' ' + coordinates[1]
                skycoord_obj = ''
                # STEP 3: Calculate time difference between observation time and Jan 1st, 2000 (J2000)
                t3 = Time(galex_time, format='mjd') - \
                    Time(51544.0, format='mjd')
                # STEP 4: Convert time (which will return in seconds) into years
                td_year = t3.sec / 60 / 60 / 24 / 365.25
                # STEP 5: Check to see if radial velocity is given then create SkyCoord object with all data
                if self.radial_velocity:
                    skycoord_obj = SkyCoord(coords, unit=(u.hourangle, u.deg), distance=Distance(parallax=self.parallax*u.mas, allow_negative=True),
                                            pm_ra_cosdec=self.pmra*u.mas/u.yr, pm_dec=self.pmdec*u.mas/u.yr, radial_velocity=self.radial_velocity*u.km/u.s)
                else:
                    skycoord_obj = SkyCoord(coords, unit=(u.hourangle, u.deg), distance=Distance(
                        parallax=self.parallax*u.mas, allow_negative=True), pm_ra_cosdec=self.pmra*u.mas/u.yr, pm_dec=self.pmdec*u.mas/u.yr)
                # STEP 6: Use apply_space_motion function to calculate new coordinates
                skycoord_obj = skycoord_obj.apply_space_motion(
                    dt=td_year * u.yr)
                # STEP 7: Add new coordinates to return data dict
                return (skycoord_obj.ra.degree, skycoord_obj.dec.degree)
            except:
                return 'Could not correct coordinates.'


class GalexFlux():
    """Represents one GALEX flux and error (FUV or NUV)."""

    def __init__(self, flux, flux_err, photospheric_flux, dist, rad, wv):
        self.flux = flux
        self.upper_lim = flux + flux_err
        self.lower_lim = flux - flux_err
        self.photo_flux = photospheric_flux
        self.dist = dist * 3.08567758e18
        self.rad = rad * 6.9e10
        self.wv = wv
        self.scale = ((self.dist**2) / (self.rad**2))

    def convert_ujy_to_flux(self, chosen_flux):
        """Converts microjanskies to ergs/s/cm2/A."""
        return (((3e-5) * (chosen_flux * 10**-6)) / pow(self.wv, 2))

    def scale_flux(self, chosen_flux):
        """Scales flux to stellar surface."""
        return chosen_flux * self.scale

    def subtract_photosphere_flux(self, chosen_flux):
        """Subtracts the photospheric contributed flux from GALEX flux."""
        return chosen_flux - self.photo_flux

    def run_calculations(self, chosen_flux):
        """Runs calculations in correct order to return converted, scaled flux."""
        converted_flux = self.convert_ujy_to_flux(chosen_flux)
        scaled_flux = self.scale_flux(converted_flux)
        photo_subtracted_flux = self.subtract_photosphere_flux(scaled_flux)
        return photo_subtracted_flux

    def return_new_flux(self):
        """Returns newly calculated flux density."""
        return self.run_calculations(self.flux)

    def return_new_err(self):
        """Calculates the new flux error."""
        new_flux = self.return_new_flux()
        new_upper_lim = self.run_calculations(self.upper_lim)
        new_lower_lim = self.run_calculations(self.lower_lim)
        new_upper_err = new_upper_lim - new_flux
        new_lower_err = new_flux - new_lower_lim
        new_err = (new_upper_err + new_lower_err) / 2
        return new_err

class GalexFluxesOld():
    def __init__(self, fuv='No Detection', fuv_err='No Detection', nuv='No Detection', nuv_err='No Detection', scale=None):
        self.fuv = fuv
        self.fuv_err = fuv_err
        self.nuv = nuv
        self.nuv_err = nuv_err
        self.scale = scale

    def predict_fluxes(self, flux_type, j_band):
        """Calculates a predicted flux if the value is missing from GALEX.

        Args:
            flux_type: Either fuv or nuv, specified to know which equation to use.

        Returns:
            A predicted nuv or fuv flux value and corresponding error.
        """
        # STEP 1: Convert J band 2MASS magnitude to microjanskies
        ZEROPOINT = 1594
        j_band_ujy = 1000 * (ZEROPOINT * pow(10.0, -0.4 * j_band))
        # STEP 3: Use equation to predict missing flux & error
        if flux_type == 'nuv':
            upper_lim = self.fuv + self.fuv_err
            lower_lim = self.fuv - self.fuv_err
            # Predict NUV flux using NUV = ((FUV/J)^(1/1.1)) * J
            # STEP N1: Use equation to find upper, lower limits and new flux values
            new_nuv_upper_lim = (
                pow((upper_lim / j_band_ujy), (1 / 1.1))) * j_band_ujy
            new_nuv = (pow((self.fuv / j_band_ujy), (1 / 1.1))) * j_band_ujy
            new_nuv_lower_lim = (
                pow((lower_lim / j_band_ujy), (1 / 1.1))) * j_band_ujy
            # STEP N2: Find the differences between the upper and lower limits and flux value (these will be error)
            #  Then calculate average of these values to get the average error
            upper_nuv = new_nuv_upper_lim - new_nuv
            lower_nuv = new_nuv - new_nuv_lower_lim
            avg_nuv_err = (upper_nuv + lower_nuv) / 2
            # STEP N3: Assign new values to return data dict using calculated flux & error
            self.nuv = new_nuv
            self.nuv_err = avg_nuv_err
        elif flux_type == 'fuv':
            upper_lim = self.nuv + self.nuv_err
            lower_lim = self.nuv - self.nuv_err
            # Predict FUV flux using FUV = ((NUV/J)^1.11) * J
            # STEP F1: Use equation to find upper, lower limits and new flux values
            new_fuv_upper_lim = (
                pow((upper_lim / j_band_ujy), 1.1)) * j_band_ujy
            new_fuv = (pow((self.nuv / j_band_ujy), 1.1)) * j_band_ujy
            new_fuv_lower_lim = (
                pow((lower_lim / j_band_ujy), 1.1)) * j_band_ujy
            # STEP F2: Find the differences between the upper and lower limits and flux value (these will be error)
            #  Then calculate average of these values to get the average error
            upper_fuv = new_fuv_upper_lim - new_fuv
            lower_fuv = new_fuv - new_fuv_lower_lim
            avg_fuv_err = (upper_fuv + lower_fuv) / 2
            # STEP N3: Assign new values to return data dict using calculated flux & error
            self.fuv = new_fuv
            self.fuv_err = avg_fuv_err
