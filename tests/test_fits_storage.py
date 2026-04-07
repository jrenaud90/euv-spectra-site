import io
import unittest
from unittest.mock import MagicMock, patch

from app import app as flask_app
from astropy.io import fits
from botocore.exceptions import ClientError
from euv_spectra_app import fits_storage


def build_test_fits_bytes():
    wavelength_column = fits.Column(name='WAVELENGTH', format='2D', array=[[100.0, 200.0]])
    flux_column = fits.Column(name='FLUX', format='2D', array=[[1.0, 2.0]])
    table_hdu = fits.BinTableHDU.from_columns([wavelength_column, flux_column])
    buffer = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), table_hdu]).writeto(buffer)
    return buffer.getvalue()


class FitsStorageTestCase(unittest.TestCase):
    def setUp(self):
        flask_app.config.update(
            TESTING=True,
            FITS_STORAGE_BACKEND='hybrid',
            FITS_S3_BUCKET='pegasus-fits-prod-731493186153-us-east-2-an',
            FITS_S3_PREFIX='',
            FITS_S3_REGION='us-east-2',
        )
        self.app_context = flask_app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_build_s3_key_candidates_includes_legacy_name_variant(self):
        keys = fits_storage.build_s3_key_candidates(
            'M0',
            'PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits',
        )

        self.assertEqual(
            keys,
            [
                'M0/PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits',
                'M0/M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits',
            ],
        )

    def test_get_model_fits_bytes_uses_s3_key_fallback(self):
        s3_client = MagicMock()
        s3_client.get_object.side_effect = [
            ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'missing'}}, 'GetObject'),
            {'Body': MagicMock(read=MagicMock(return_value=build_test_fits_bytes()))},
        ]

        with patch('euv_spectra_app.fits_storage.os.path.isfile', return_value=False), patch(
            'euv_spectra_app.fits_storage._get_s3_client', return_value=s3_client
        ):
            fits_bytes = fits_storage.get_model_fits_bytes(
                'M0',
                'PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits',
            )

        self.assertIsInstance(fits_bytes, bytes)
        self.assertEqual(s3_client.get_object.call_args_list[0].kwargs['Key'], 'M0/PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits')
        self.assertEqual(s3_client.get_object.call_args_list[1].kwargs['Key'], 'M0/M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits')


if __name__ == '__main__':
    unittest.main()