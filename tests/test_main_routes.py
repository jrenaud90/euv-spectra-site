import unittest
from unittest.mock import patch

from app import app as flask_app
from euv_spectra_app.errors import PegasusError
from euv_spectra_app.main import routes


class FakeFluxes:
    def __init__(self, should_raise=False):
        self.should_raise = should_raise
        self.fuv = 55.75778
        self.fuv_err = 8.697778
        self.nuv = 1002.1626
        self.nuv_err = 14.8769665
        self.processed_fuv = 167.64971644316745
        self.processed_fuv_err = 26.158229050822513
        self.processed_nuv = 1219.2948859922221
        self.processed_nuv_err = 20.57292489842814
        self.fuv_is_saturated = False
        self.nuv_is_saturated = False
        self.fuv_is_upper_limit = False
        self.nuv_is_upper_limit = False

    def convert_scale_photosphere_subtract_fluxes(self):
        if self.should_raise:
            raise PegasusError('Synthetic processing failure for test coverage.')


class FakeStellarObject:
    def __init__(self, should_raise=False):
        self.star_name = 'GJ 338 B'
        self.position = None
        self.teff = 4014.0
        self.logg = 4.68
        self.mass = 0.64
        self.dist = 6.33256
        self.rad = 0.58
        self.model_subtype = None
        self.modal_error_msgs = []
        self.modal_page_error_msg = None
        self.fluxes = FakeFluxes(should_raise=should_raise)

    def has_all_stellar_parameters(self):
        return True


class FakePegasusGrid:
    def __init__(self, stellar_object):
        self.stellar_object = stellar_object

    def query_pegasus_subtype(self):
        return {'model': 'M0'}

    def query_model_collection(self, fuv_value, nuv_value):
        return [{
            'fits_filename': 'PEGASUS.M0.synthetic.fits',
            'nuv': 1236.0,
            'fuv': 177.6,
            'euv': 3330.4,
        }]

    def query_pegasus_chi_square(self):
        return self.query_model_collection(None, None)

    def query_pegasus_weighted_fuv(self):
        return []


class MainRoutesTestCase(unittest.TestCase):
    def setUp(self):
        flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = flask_app.test_client()

    def _store_session_object(self, payload='serialized-stellar-object'):
        with self.client.session_transaction() as session_state:
            session_state[routes.STELLAR_OBJECT_SESSION_KEY] = payload

    def test_modal_submit_redirects_home_when_session_missing(self):
        response = self.client.get('/modal-submit')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/apps/pegasus/', response.location)

    def test_results_redirects_home_when_session_missing(self):
        response = self.client.get('/results')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/apps/pegasus/', response.location)

    @patch('euv_spectra_app.main.routes.render_template')
    @patch('euv_spectra_app.main.routes.insert_data_into_form')
    @patch('euv_spectra_app.main.routes.StellarObject.get_stellar_parameters')
    def test_homepage_post_does_not_redirect_to_error_when_modal_page_error_is_none(
        self,
        mock_get_stellar_parameters,
        mock_insert,
        mock_render_template,
    ):
        mock_get_stellar_parameters.return_value = None
        mock_insert.return_value = None
        mock_render_template.return_value = 'home rendered'

        response = self.client.post('/', data={'star_name': 'GJ 338 B', 'submit': 'Search →'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'home rendered')
        mock_render_template.assert_called_once()

    @patch('euv_spectra_app.main.routes.StellarObject.get_stellar_parameters')
    def test_homepage_post_redirects_to_error_with_lookup_details_in_session(self, mock_get_stellar_parameters):
        def populate_failure(stellar_object):
            stellar_object.modal_page_error_msg = 'Unable to retrieve any external catalog data for GJ 338 B.'
            stellar_object.lookup_details = [
                {'source': 'NASA Exoplanet Archive', 'message': 'Nothing found in NEA.'},
                {'source': 'MAST GALEX', 'message': 'No GALEX observations found.'},
            ]

        mock_get_stellar_parameters.side_effect = populate_failure

        response = self.client.post('/', data={'star_name': 'GJ 338 B', 'submit': 'Search →'})

        self.assertEqual(response.status_code, 302)
        self.assertIn('/apps/pegasus/error?', response.location)
        with self.client.session_transaction() as session_state:
            self.assertEqual(
                session_state[routes.ERROR_CONTEXT_SESSION_KEY],
                {
                    'summary': 'Unable to retrieve any external catalog data for GJ 338 B.',
                    'details': [
                        {'source': 'NASA Exoplanet Archive', 'message': 'Nothing found in NEA.'},
                        {'source': 'MAST GALEX', 'message': 'No GALEX observations found.'},
                    ],
                },
            )

    @patch('euv_spectra_app.main.routes.insert_data_into_form')
    @patch('euv_spectra_app.main.routes.deserialize_stellar_object')
    def test_results_redirects_to_error_when_flux_processing_fails(self, mock_deserialize, mock_insert):
        self._store_session_object()
        mock_insert.return_value = None
        mock_deserialize.return_value = FakeStellarObject(should_raise=True)

        response = self.client.get('/results')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/apps/pegasus/error?', response.location)
        self.assertIn('Synthetic+processing+failure+for+test+coverage.', response.location)

    @patch('euv_spectra_app.main.routes.create_plotly_graph', return_value={'data': [], 'layout': {}})
    @patch('euv_spectra_app.main.routes.render_template')
    @patch('euv_spectra_app.main.routes.insert_data_into_form')
    @patch('euv_spectra_app.main.routes.deserialize_stellar_object')
    @patch('euv_spectra_app.main.routes.get_model_fits_bytes', return_value=b'fits-bytes')
    @patch('euv_spectra_app.main.routes.PegasusGrid', FakePegasusGrid)
    @patch('euv_spectra_app.main.routes.db.list_collection_names', return_value=['m0_grid'])
    def test_results_renders_result_template_for_mocked_session(
        self,
        mock_list_collection_names,
        mock_get_model_fits_bytes,
        mock_deserialize,
        mock_insert,
        mock_render_template,
        mock_create_plot,
    ):
        self._store_session_object()
        mock_insert.return_value = None
        mock_deserialize.return_value = FakeStellarObject()
        mock_render_template.side_effect = lambda template_name, **context: f'{template_name}|{len(context.get("matching_models", []))}'

        response = self.client.get('/results')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'result.html|1')
        mock_list_collection_names.assert_called_once()
        mock_create_plot.assert_called_once()
        mock_get_model_fits_bytes.assert_called()

    @patch('euv_spectra_app.main.routes.fits_asset_exists', return_value=True)
    def test_check_directory_uses_filename_inference_without_session(self, mock_fits_asset_exists):
        response = self.client.get('/check-directory/PEGASUS.M0.synthetic.fits')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'exists': True})
        mock_fits_asset_exists.assert_called_once_with('M0', 'PEGASUS.M0.synthetic.fits')

    @patch('euv_spectra_app.main.routes.send_file')
    @patch('euv_spectra_app.main.routes.get_model_fits_bytes', return_value=b'fits-bytes')
    def test_download_uses_filename_inference_without_session(self, mock_get_model_fits_bytes, mock_send_file):
        mock_send_file.return_value = flask_app.response_class('ok', mimetype='text/plain')

        response = self.client.get('/download/PEGASUS.M0.synthetic.fits/Model%201')

        self.assertEqual(response.status_code, 200)
        mock_get_model_fits_bytes.assert_called_once_with('M0', 'PEGASUS.M0.synthetic.fits')
        mock_send_file.assert_called_once()

    @patch('euv_spectra_app.main.routes.cache.clear')
    def test_clear_cache_route_clears_application_cache(self, mock_cache_clear):
        response = self.client.get('/clear_cache')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'ok': True, 'message': 'Pegasus cache cleared.'})
        mock_cache_clear.assert_called_once_with()

    def test_error_route_renders_structured_error_details(self):
        with self.client.session_transaction() as session_state:
            session_state[routes.ERROR_CONTEXT_SESSION_KEY] = {
                'summary': 'Unable to retrieve any external catalog data for GJ 338 B.',
                'details': [
                    {'source': 'NASA Exoplanet Archive', 'message': 'Nothing found in NEA.'},
                    {'source': 'MAST GALEX', 'message': 'No GALEX observations found.'},
                ],
            }

        response = self.client.get('/error')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('What failed', body)
        self.assertIn('NASA Exoplanet Archive', body)
        self.assertIn('No GALEX observations found.', body)


if __name__ == '__main__':
    unittest.main()