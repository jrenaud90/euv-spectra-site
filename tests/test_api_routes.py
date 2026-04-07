import unittest
from unittest.mock import patch

from app import app as flask_app
from astropy.io import fits
import io


def build_test_fits_bytes():
    wavelength_column = fits.Column(name='WAVELENGTH', format='2D', array=[[100.0, 200.0]])
    flux_column = fits.Column(name='FLUX', format='2D', array=[[1.0, 2.0]])
    table_hdu = fits.BinTableHDU.from_columns([wavelength_column, flux_column])
    buffer = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), table_hdu]).writeto(buffer)
    return buffer.getvalue()


class ApiRoutesTestCase(unittest.TestCase):
    def setUp(self):
        flask_app.config.update(TESTING=True)
        self.client = flask_app.test_client()

    @patch('euv_spectra_app.api.routes.get_model_fits_bytes', return_value=None)
    @patch('euv_spectra_app.api.routes.get_test_fits_bytes', return_value=None)
    def test_get_model_data_returns_not_found_when_fits_missing(self, mock_get_test_fits_bytes, mock_get_model_fits_bytes):
        response = self.client.get('/api/get_model_data?fits_filename=PEGASUS.M0.missing.fits')

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload['error']['field'], 'fits_filename')

    @patch('euv_spectra_app.api.routes.get_model_fits_bytes', return_value=build_test_fits_bytes())
    @patch('euv_spectra_app.api.routes.get_test_fits_bytes', return_value=None)
    def test_get_model_data_returns_flux_arrays_when_fits_found(self, mock_get_test_fits_bytes, mock_get_model_fits_bytes):
        response = self.client.get('/api/get_model_data?fits_filename=PEGASUS.M0.synthetic.fits')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['data']['wavelength_data'], [100.0, 200.0])
        self.assertEqual(payload['data']['flux_data'], [1.0, 2.0])
