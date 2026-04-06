import math
import unittest

from euv_spectra_app.flux_utils import (
    FUV_WAVELENGTH,
    NUV_WAVELENGTH,
    average_error_from_limits,
    calculate_surface_scale,
    convert_microjanskies_to_flux_density,
    process_galex_flux,
    process_galex_flux_with_error,
    scale_flux_to_surface,
    subtract_photospheric_flux,
)


class FluxUtilsTestCase(unittest.TestCase):
    def test_convert_microjanskies_to_flux_density_matches_formula(self):
        flux = 55.76
        expected = ((3e-5) * (flux * 10 ** -6)) / (FUV_WAVELENGTH ** 2)

        self.assertAlmostEqual(
            convert_microjanskies_to_flux_density(flux, FUV_WAVELENGTH),
            expected,
            places=24,
        )

    def test_calculate_surface_scale_matches_existing_equation(self):
        dist = 6.33256
        rad = 0.58
        expected = ((dist * 3.08567758e18) ** 2) / ((rad * 6.9e10) ** 2)

        self.assertAlmostEqual(calculate_surface_scale(dist, rad), expected)

    def test_average_error_from_limits_is_symmetric(self):
        center_value = 10.0
        upper_value = 13.5
        lower_value = 6.5

        self.assertEqual(average_error_from_limits(center_value, upper_value, lower_value), 3.5)

    def test_process_galex_flux_matches_stepwise_pipeline(self):
        flux = 1002.16
        photo_flux = 166.280545204594
        dist = 6.33256
        rad = 0.58

        converted_flux = convert_microjanskies_to_flux_density(flux, NUV_WAVELENGTH)
        scaled_flux = scale_flux_to_surface(converted_flux, dist, rad)
        expected = subtract_photospheric_flux(scaled_flux, photo_flux)

        self.assertAlmostEqual(
            process_galex_flux(flux, photo_flux, dist, rad, NUV_WAVELENGTH),
            expected,
        )

    def test_process_galex_flux_with_error_returns_none_when_error_missing(self):
        processed_flux, processed_err = process_galex_flux_with_error(
            55.76,
            None,
            0.0034849216444831,
            6.33256,
            0.58,
            FUV_WAVELENGTH,
        )

        self.assertIsNone(processed_err)
        self.assertTrue(math.isfinite(processed_flux))

    def test_process_galex_flux_with_error_matches_manual_error_propagation(self):
        flux = 55.76
        flux_err = 8.7
        photo_flux = 0.0034849216444831
        dist = 6.33256
        rad = 0.58

        processed_flux, processed_err = process_galex_flux_with_error(
            flux,
            flux_err,
            photo_flux,
            dist,
            rad,
            FUV_WAVELENGTH,
        )
        manual_upper = process_galex_flux(flux + flux_err, photo_flux, dist, rad, FUV_WAVELENGTH)
        manual_lower = process_galex_flux(flux - flux_err, photo_flux, dist, rad, FUV_WAVELENGTH)
        manual_err = average_error_from_limits(processed_flux, manual_upper, manual_lower)

        self.assertAlmostEqual(processed_flux, process_galex_flux(flux, photo_flux, dist, rad, FUV_WAVELENGTH))
        self.assertAlmostEqual(processed_err, manual_err)


if __name__ == '__main__':
    unittest.main()