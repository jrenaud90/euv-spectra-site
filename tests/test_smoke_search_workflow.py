import unittest
from unittest.mock import patch

from app import app as flask_app
from euv_spectra_app.main import routes


class HomepageFakeFluxes:
    pass


class HomepageFakeStellarObject:
    def __init__(self):
        self.star_name = None
        self.modal_error_msgs = []
        self.fluxes = HomepageFakeFluxes()

    def get_stellar_parameters(self):
        self.teff = 4014.0
        self.logg = 4.68
        self.mass = 0.64
        self.dist = 6.33256
        self.rad = 0.58


class ResultsFakeFluxes:
    def __init__(self):
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
        return None


class ResultsFakeStellarObject:
    def __init__(self):
        self.star_name = 'GJ 338 B'
        self.teff = 4014.0
        self.logg = 4.68
        self.mass = 0.64
        self.dist = 6.33256
        self.rad = 0.58
        self.position = None
        self.model_subtype = None
        self.fluxes = ResultsFakeFluxes()

    def has_all_stellar_parameters(self):
        return True


class ResultsFakePegasusGrid:
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


class SmokeSearchWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = flask_app.test_client()

    @patch('euv_spectra_app.main.routes.os.path.exists', return_value=True)
    @patch('euv_spectra_app.main.routes.create_plotly_graph', return_value={'data': [], 'layout': {}})
    @patch('euv_spectra_app.main.routes.render_template')
    @patch('euv_spectra_app.main.routes.insert_data_into_form')
    @patch('euv_spectra_app.main.routes.deserialize_stellar_object', return_value=ResultsFakeStellarObject())
    @patch('euv_spectra_app.main.routes.serialize_stellar_object', return_value='serialized-smoke-object')
    @patch('euv_spectra_app.main.routes.StellarObject', HomepageFakeStellarObject)
    @patch('euv_spectra_app.main.routes.PegasusGrid', ResultsFakePegasusGrid)
    @patch('euv_spectra_app.main.routes.db.list_collection_names', return_value=['m0_grid'])
    def test_name_search_workflow_reaches_results_page(
        self,
        mock_list_collection_names,
        mock_serialize,
        mock_deserialize,
        mock_insert,
        mock_render_template,
        mock_create_plot,
        mock_exists,
    ):
        mock_insert.return_value = None
        mock_render_template.side_effect = lambda template_name, **context: template_name

        home_response = self.client.post('/', data={'star_name': 'GJ 338 B', 'submit': 'Search'})

        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(home_response.get_data(as_text=True), 'home.html')
        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state[routes.STELLAR_OBJECT_SESSION_KEY], 'serialized-smoke-object')
            self.assertTrue(session_state['modal_show'])

        results_response = self.client.get('/results')

        self.assertEqual(results_response.status_code, 200)
        self.assertEqual(results_response.get_data(as_text=True), 'result.html')
        mock_serialize.assert_called_once()
        mock_deserialize.assert_called_once_with('serialized-smoke-object')
        mock_list_collection_names.assert_called_once()
        mock_create_plot.assert_called_once()
        self.assertTrue(mock_exists.called)


if __name__ == '__main__':
    unittest.main()