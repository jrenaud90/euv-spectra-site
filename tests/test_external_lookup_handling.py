import unittest
from unittest.mock import patch

from euv_spectra_app.errors import CatalogLookupError
from euv_spectra_app.models import StellarObject, _run_with_retries


class ExternalLookupHandlingTestCase(unittest.TestCase):
    @patch('euv_spectra_app.models.time.sleep')
    def test_run_with_retries_returns_after_transient_failure(self, mock_sleep):
        attempts = []

        def flaky_operation():
            attempts.append('call')
            if len(attempts) == 1:
                raise OSError('temporary failure')
            return 'ok'

        result = _run_with_retries(
            flaky_operation,
            retriable_exceptions=(OSError,),
            operation_name='transient test operation',
        )

        self.assertEqual(result, 'ok')
        self.assertEqual(len(attempts), 2)
        mock_sleep.assert_called_once()

    @patch('euv_spectra_app.models.time.sleep')
    def test_run_with_retries_raises_last_error_after_exhaustion(self, mock_sleep):
        attempts = []

        def failing_operation():
            attempts.append('call')
            raise OSError('persistent failure')

        with self.assertRaises(OSError) as exc_context:
            _run_with_retries(
                failing_operation,
                retriable_exceptions=(OSError,),
                operation_name='persistent test operation',
            )

        self.assertEqual(str(exc_context.exception), 'persistent failure')
        self.assertEqual(len(attempts), 2)
        mock_sleep.assert_called_once()

    @patch('euv_spectra_app.models._service_is_available', return_value=False)
    def test_query_simbad_returns_recoverable_error_when_service_is_down(self, mock_available):
        stellar_object = StellarObject(star_name='GJ 338 B')

        with self.assertRaises(CatalogLookupError) as exc_context:
            stellar_object.query_simbad('GJ 338 B')

        self.assertTrue(exc_context.exception.recoverable)
        self.assertIn('SIMBAD', exc_context.exception.user_message)
        mock_available.assert_called_once()

    @patch('euv_spectra_app.models._service_is_available', return_value=False)
    def test_query_nea_returns_recoverable_error_when_service_is_down(self, mock_available):
        stellar_object = StellarObject(star_name='GJ 338 B')

        with self.assertRaises(CatalogLookupError) as exc_context:
            stellar_object.query_nasa_exoplanet_archive('GJ 338 B', (138.59, 52.68))

        self.assertTrue(exc_context.exception.recoverable)
        self.assertIn('NASA Exoplanet Archive', exc_context.exception.user_message)
        mock_available.assert_called_once()

    @patch('euv_spectra_app.models.normalize_star_name', side_effect=lambda value: value)
    @patch.object(StellarObject, 'query_simbad', return_value=None)
    @patch.object(StellarObject, 'query_nasa_exoplanet_archive')
    @patch.object(StellarObject, 'query_galex')
    def test_lookup_pipeline_sets_page_error_when_nea_and_galex_both_fail(
        self,
        mock_query_galex,
        mock_query_nea,
        mock_query_simbad,
        mock_normalize,
    ):
        stellar_object = StellarObject(star_name='GJ 338 B')
        mock_query_nea.side_effect = CatalogLookupError('NEA unavailable for test.', recoverable=True)
        mock_query_galex.side_effect = CatalogLookupError('GALEX unavailable for test.', recoverable=True)

        stellar_object._run_lookup_pipeline()

        self.assertEqual(
            stellar_object.modal_page_error_msg,
            'Nothing found for your target in the NExSci database or the MAST GALEX database.',
        )
        self.assertIn('NEA unavailable for test.', stellar_object.modal_error_msgs)
        self.assertIn('GALEX unavailable for test.', stellar_object.modal_error_msgs)


if __name__ == '__main__':
    unittest.main()