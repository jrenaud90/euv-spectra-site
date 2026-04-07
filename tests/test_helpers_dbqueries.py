import unittest
from unittest.mock import MagicMock, patch

from app import app as flask_app
from euv_spectra_app.extensions import cache
from euv_spectra_app import helpers_dbqueries


class HelpersDbQueriesTestCase(unittest.TestCase):
    def setUp(self):
        self.app_context = flask_app.app_context()
        self.app_context.push()
        cache.clear()

    def tearDown(self):
        cache.clear()
        self.app_context.pop()

    def test_construct_flux_query_for_normal_flux(self):
        query = helpers_dbqueries.construct_flux_query('fuv', 'normal', 100.0, 5.0)

        self.assertEqual(
            query,
            {'$match': {'fuv': {'$gte': 95.0, '$lte': 105.0}}},
        )

    def test_construct_flux_query_for_detection_only_flux(self):
        query = helpers_dbqueries.construct_flux_query('nuv', 'detection_only', 42.0, None)

        self.assertEqual(
            query,
            {'$addFields': {'diff_flux': {'$abs': {'$subtract': [42.0, '$nuv']}}}},
        )

    @patch('euv_spectra_app.helpers_dbqueries.model_parameter_grid')
    def test_get_matching_subtype_uses_weighted_pipeline(self, mock_model_parameter_grid):
        mock_model_parameter_grid.aggregate.return_value = [{'_id': 'x', 'model': 'M0'}]

        result = helpers_dbqueries.get_matching_subtype(4014.0, 4.68, 0.64)

        self.assertEqual(result['model'], 'M0')
        pipeline = mock_model_parameter_grid.aggregate.call_args.args[0]
        weighted_add = pipeline[1]['$addFields']['diff_sum']['$add']
        self.assertEqual(weighted_add[0]['$multiply'], ['$diff_teff', 10])
        self.assertEqual(weighted_add[1]['$multiply'], ['$diff_logg', 2])
        self.assertEqual(weighted_add[2]['$multiply'], ['$diff_mass', 5])
        self.assertEqual(pipeline[-2], {'$sort': {'diff_sum': 1}})
        self.assertEqual(pipeline[-1], {'$limit': 1})

    @patch('euv_spectra_app.helpers_dbqueries.model_parameter_grid')
    def test_get_matching_subtype_uses_cache_on_repeat_lookup(self, mock_model_parameter_grid):
        mock_model_parameter_grid.aggregate.return_value = [{'_id': 'x', 'model': 'M0'}]

        first = helpers_dbqueries.get_matching_subtype(4014.0, 4.68, 0.64)
        second = helpers_dbqueries.get_matching_subtype(4014.0, 4.68, 0.64)

        self.assertEqual(first['model'], 'M0')
        self.assertEqual(second['model'], 'M0')
        mock_model_parameter_grid.aggregate.assert_called_once()

    @patch('euv_spectra_app.helpers_dbqueries.photosphere_models')
    def test_get_matching_photosphere_uses_cache_on_repeat_lookup(self, mock_photosphere_models):
        mock_photosphere_models.aggregate.return_value = [{'_id': 'x', 'fits_filename': 'photo.fits'}]

        first = helpers_dbqueries.get_matching_photosphere(3850.0, 4.78, 0.53)
        second = helpers_dbqueries.get_matching_photosphere(3850.0, 4.78, 0.53)

        self.assertEqual(first['fits_filename'], 'photo.fits')
        self.assertEqual(second['fits_filename'], 'photo.fits')
        mock_photosphere_models.aggregate.assert_called_once()

    @patch('euv_spectra_app.helpers_dbqueries.db')
    def test_get_models_within_limits_builds_expected_match_bounds(self, mock_db):
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = []
        mock_db.get_collection.return_value = mock_collection

        list(helpers_dbqueries.get_models_within_limits(120.0, 50.0, 10.0, 5.0, 'm0_grid'))

        mock_db.get_collection.assert_called_once_with('m0_grid')
        pipeline = mock_collection.aggregate.call_args.args[0]
        self.assertEqual(
            pipeline[0],
            {
                '$match': {
                    'fuv': {'$gte': 45.0, '$lte': 55.0},
                    'nuv': {'$gte': 110.0, '$lte': 130.0},
                }
            },
        )
        self.assertEqual(pipeline[-1], {'$sort': {'chi_squared': 1}})

    @patch('euv_spectra_app.helpers_dbqueries.db')
    def test_get_models_with_weighted_fuv_filters_on_component_scores(self, mock_db):
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = [
            {'fits_filename': 'keep.fits', 'chi_squared_fuv': 1.0, 'chi_squared_nuv': 2.0, 'chi_squared': 3.0},
            {'fits_filename': 'drop.fits', 'chi_squared_fuv': 4.0, 'chi_squared_nuv': 1.0, 'chi_squared': 5.0},
        ]
        mock_db.get_collection.return_value = mock_collection

        result = helpers_dbqueries.get_models_with_weighted_fuv(120.0, 50.0, 'm0_grid')

        self.assertEqual([model['fits_filename'] for model in result], ['keep.fits'])

    @patch('euv_spectra_app.helpers_dbqueries.db')
    def test_get_models_by_chi_squared_pipeline_sorts_by_chi_squared(self, mock_db):
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = []
        mock_db.get_collection.return_value = mock_collection

        list(helpers_dbqueries.get_models_with_chi_squared(120.0, 50.0, 'm0_grid'))

        pipeline = mock_collection.aggregate.call_args.args[0]
        self.assertEqual(pipeline[-1], {'$sort': {'chi_squared': 1}})


if __name__ == '__main__':
    unittest.main()