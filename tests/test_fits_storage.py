import io
import unittest
from unittest.mock import MagicMock, patch

from app import app as flask_app
from astropy.io import fits
from botocore.exceptions import ClientError
from euv_spectra_app.extensions import cache
from euv_spectra_app import fits_storage


def build_test_fits_bytes():
    wavelength_column = fits.Column(name='WAVELENGTH', format='2D', array=[[100.0, 200.0]])
    flux_column = fits.Column(name='FLUX', format='2D', array=[[1.0, 2.0]])
    table_hdu = fits.BinTableHDU.from_columns([wavelength_column, flux_column])
    buffer = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), table_hdu]).writeto(buffer)
    return buffer.getvalue()


class FakeFitsMetadataCollection:
    def __init__(self):
        self.records = {}

    def find_one(self, filter_query=None, projection=None, sort=None):
        if sort:
            if not self.records:
                return None
            latest = sorted(self.records.values(), key=lambda item: item.get('checked_at', 0), reverse=True)[0]
            return dict(latest)

        if not filter_query:
            return None

        key = (filter_query.get('model_subtype'), filter_query.get('fits_filename'))
        record = self.records.get(key)
        if record is None:
            return None
        if projection and projection.get('_id') == 0:
            return dict(record)
        return dict(record)

    def update_one(self, filter_query, update_doc, upsert=False):
        key = (filter_query.get('model_subtype'), filter_query.get('fits_filename'))
        self.records[key] = dict(update_doc.get('$set', {}))
        return MagicMock()

    def delete_many(self, filter_query):
        deleted_count = len(self.records)
        self.records = {}
        return MagicMock(deleted_count=deleted_count)

    def count_documents(self, filter_query):
        return len(self.records)


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
        cache.clear()
        self.metadata_collection = FakeFitsMetadataCollection()

    def tearDown(self):
        cache.clear()
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

    def test_get_model_fits_bytes_uses_persisted_s3_metadata_after_first_probe(self):
        s3_client = MagicMock()
        s3_client.head_object.side_effect = [
            ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'missing'}}, 'GetObject'),
            {},
        ]
        s3_client.get_object.return_value = {'Body': MagicMock(read=MagicMock(return_value=build_test_fits_bytes()))}

        with patch('euv_spectra_app.fits_storage.os.path.isfile', return_value=False), patch(
            'euv_spectra_app.fits_storage._get_s3_client', return_value=s3_client
        ), patch(
            'euv_spectra_app.fits_storage._metadata_collection', return_value=self.metadata_collection
        ):
            fits_bytes = fits_storage.get_model_fits_bytes(
                'M0',
                'PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits',
            )
            fits_bytes_second = fits_storage.get_model_fits_bytes(
                'M0',
                'PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits',
            )

        self.assertIsInstance(fits_bytes, bytes)
        self.assertIsInstance(fits_bytes_second, bytes)
        self.assertEqual(s3_client.head_object.call_args_list[0].kwargs['Key'], 'M0/PEGASUS.M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits')
        self.assertEqual(s3_client.head_object.call_args_list[1].kwargs['Key'], 'M0/M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits')
        self.assertEqual(len(s3_client.head_object.call_args_list), 2)
        self.assertEqual(s3_client.get_object.call_args_list[0].kwargs['Key'], 'M0/M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits')
        self.assertEqual(s3_client.get_object.call_args_list[1].kwargs['Key'], 'M0/M0.Teff=3850.logg=4.78.TRgrad=9.cmtop=6.cmin=4.fits')

    def test_fits_asset_exists_reuses_persisted_unavailable_metadata(self):
        s3_client = MagicMock()
        s3_client.head_object.side_effect = [
            ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'missing'}}, 'HeadObject'),
            ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'missing'}}, 'HeadObject'),
        ]

        with patch('euv_spectra_app.fits_storage.os.path.isfile', return_value=False), patch(
            'euv_spectra_app.fits_storage._get_s3_client', return_value=s3_client
        ), patch(
            'euv_spectra_app.fits_storage._metadata_collection', return_value=self.metadata_collection
        ):
            self.assertFalse(fits_storage.fits_asset_exists('M0', 'PEGASUS.M0.synthetic.fits'))
            self.assertFalse(fits_storage.fits_asset_exists('M0', 'PEGASUS.M0.synthetic.fits'))

        self.assertEqual(len(s3_client.head_object.call_args_list), 2)


if __name__ == '__main__':
    unittest.main()