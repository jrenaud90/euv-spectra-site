import unittest
from unittest.mock import patch

from app import app as flask_app
from euv_spectra_app.extensions import cache
from euv_spectra_app.models import GalexFluxes, ProperMotionData, StellarObject


class ModelsCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.app_context = flask_app.app_context()
        self.app_context.push()
        cache.clear()

    def tearDown(self):
        cache.clear()
        self.app_context.pop()

    @patch.object(StellarObject, '_run_lookup_pipeline', autospec=True)
    def test_get_stellar_parameters_uses_cached_lookup_payload(self, mock_run_lookup_pipeline):
        def populate_lookup(stellar_object):
            stellar_object.star_name = 'GJ 338 B'
            stellar_object.coords = ('06 10 34.6', '+35 58 11')
            stellar_object.teff = 4014.0
            stellar_object.logg = 4.68
            stellar_object.mass = 0.64
            stellar_object.dist = 6.33
            stellar_object.rad = 0.58
            stellar_object.stellar_subtype = 'M0'
            stellar_object.model_collection = 'm0_grid'
            stellar_object.pm_corrected_coords = (92.644, 35.969)
            stellar_object.pm_data = ProperMotionData(1.0, 2.0, 3.0, 4.0)
            stellar_object.fluxes = GalexFluxes(fuv=10.0, nuv=20.0, fuv_err=1.0, nuv_err=2.0)
            stellar_object.modal_error_msgs = ['cached warning']

        mock_run_lookup_pipeline.side_effect = populate_lookup

        first = StellarObject(star_name='GJ 338 B')
        first.get_stellar_parameters()

        second = StellarObject(star_name='GJ 338 B')
        second.get_stellar_parameters()

        self.assertEqual(mock_run_lookup_pipeline.call_count, 1)
        self.assertEqual(second.teff, 4014.0)
        self.assertEqual(second.model_collection, 'm0_grid')
        self.assertEqual(second.stellar_subtype, 'M0')
        self.assertEqual(second.modal_error_msgs, ['cached warning'])
        self.assertEqual(second.fluxes.fuv, 10.0)
        self.assertEqual(second.pm_data.pm_ra, 1.0)

    @patch.object(StellarObject, '_run_lookup_pipeline', autospec=True)
    def test_get_stellar_parameters_bypasses_cached_fatal_lookup_and_reruns(self, mock_run_lookup_pipeline):
        failure = StellarObject(star_name='GJ 338 B')
        failure.modal_page_error_msg = 'Unable to retrieve any external catalog data for GJ 338 B.'
        cache.set(failure._lookup_cache_key(), failure._serialize_lookup_state())

        def populate_success(stellar_object):
            stellar_object.star_name = 'GJ 338 B'
            stellar_object.coords = ('06 10 34.6', '+35 58 11')
            stellar_object.teff = 4014.0
            stellar_object.logg = 4.68
            stellar_object.mass = 0.64
            stellar_object.dist = 6.33
            stellar_object.rad = 0.58
            stellar_object.fluxes = GalexFluxes(fuv=10.0, nuv=20.0, fuv_err=1.0, nuv_err=2.0)
            stellar_object.modal_page_error_msg = None

        mock_run_lookup_pipeline.side_effect = populate_success

        stellar_object = StellarObject(star_name='GJ 338 B')
        stellar_object.get_stellar_parameters()

        self.assertEqual(mock_run_lookup_pipeline.call_count, 1)
        self.assertIsNone(stellar_object.modal_page_error_msg)
        self.assertEqual(stellar_object.teff, 4014.0)
        cached_payload = cache.get(stellar_object._lookup_cache_key())
        self.assertIsNone(cached_payload.get('modal_page_error_msg'))

    @patch.object(StellarObject, '_run_lookup_pipeline', autospec=True)
    def test_get_stellar_parameters_does_not_cache_lookup_with_warnings(self, mock_run_lookup_pipeline):
        def populate_warning(stellar_object):
            stellar_object.star_name = 'GJ 338 B'
            stellar_object.coords = ('06 10 34.6', '+35 58 11')
            stellar_object.teff = 4014.0
            stellar_object.logg = 4.68
            stellar_object.mass = 0.64
            stellar_object.dist = 6.33
            stellar_object.rad = 0.58
            stellar_object.fluxes = GalexFluxes(fuv=10.0, nuv=20.0, fuv_err=1.0, nuv_err=2.0)
            stellar_object.modal_error_msgs = ['GALEX warning']
            stellar_object.lookup_details = [{'source': 'MAST GALEX', 'message': 'GALEX warning'}]

        mock_run_lookup_pipeline.side_effect = populate_warning

        stellar_object = StellarObject(star_name='GJ 338 B')
        stellar_object.get_stellar_parameters()

        self.assertEqual(stellar_object.modal_error_msgs, ['GALEX warning'])
        self.assertIsNone(cache.get(stellar_object._lookup_cache_key()))


if __name__ == '__main__':
    unittest.main()