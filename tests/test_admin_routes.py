import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from bson import json_util

from app import app as flask_app
from euv_spectra_app import admin_utils


class AdminRoutesTestCase(unittest.TestCase):
    def setUp(self):
        archive_file = tempfile.NamedTemporaryFile(delete=False)
        archive_file.write(b'archive-bytes')
        archive_file.close()
        self.archive_path = archive_file.name

        flask_app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            ADMIN_PUBLIC_KEY='test-public-key',
            ADMIN_ALLOWED_COLLECTIONS='m0_grid',
            MONGODB_ARCHIVE_DOWNLOAD_PATH=self.archive_path,
        )
        self.client = flask_app.test_client()

    def tearDown(self):
        if os.path.exists(self.archive_path):
            os.unlink(self.archive_path)

    def _authenticate_admin_session(self):
        with self.client.session_transaction() as session_state:
            session_state[admin_utils.ADMIN_AUTHENTICATED_KEY] = True
            session_state[admin_utils.ADMIN_AUTHENTICATED_AT_KEY] = 4102444800

    @patch('euv_spectra_app.main.routes.render_template', side_effect=lambda template_name, **context: template_name)
    @patch('euv_spectra_app.main.routes.get_collection_summaries', return_value=[])
    @patch('euv_spectra_app.main.routes.get_allowed_collection_names', return_value=['m0_grid'])
    @patch('euv_spectra_app.main.routes.db.get_collection')
    def test_admin_upload_replace_requires_confirmation(
        self,
        mock_get_collection,
        mock_allowed_names,
        mock_collection_summaries,
        mock_render_template,
    ):
        self._authenticate_admin_session()
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        response = self.client.post(
            '/admin',
            data={
                'upload-collection': 'm0_grid',
                'upload-mode': 'replace',
                'upload-confirm_replace': 'WRONG',
                'upload-payload_file': (io.BytesIO(b'{"name": "example"}'), 'payload.json'),
                'upload-submit': '1',
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'admin-panel.html')
        mock_collection.delete_many.assert_not_called()
        mock_collection.insert_many.assert_not_called()

    @patch('euv_spectra_app.main.routes.render_template', side_effect=lambda template_name, **context: template_name)
    @patch('euv_spectra_app.main.routes.get_collection_summaries', return_value=[])
    @patch('euv_spectra_app.main.routes.get_allowed_collection_names', return_value=['m0_grid'])
    @patch('euv_spectra_app.main.routes.db.get_collection')
    def test_admin_delete_matching_rejects_empty_filter(
        self,
        mock_get_collection,
        mock_allowed_names,
        mock_collection_summaries,
        mock_render_template,
    ):
        self._authenticate_admin_session()
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        response = self.client.post(
            '/admin',
            data={
                'delete-collection': 'm0_grid',
                'delete-delete_scope': 'matching',
                'delete-filter_json': '{}',
                'delete-confirm_collection': '',
                'delete-submit': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'admin-panel.html')
        mock_collection.delete_many.assert_not_called()

    @patch('euv_spectra_app.main.routes.get_allowed_collection_names', return_value=['m0_grid'])
    @patch('euv_spectra_app.main.routes.db.get_collection')
    def test_admin_sample_json_downloads_attachment(self, mock_get_collection, mock_allowed_names):
        self._authenticate_admin_session()
        mock_collection = MagicMock()
        mock_cursor = MagicMock()
        sample_documents = [{'_id': 1, 'name': 'example'}]
        mock_cursor.limit.return_value = sample_documents
        mock_collection.find.return_value = mock_cursor
        mock_get_collection.return_value = mock_collection

        response = self.client.get('/admin/sample-json?collection=m0_grid')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/json')
        self.assertIn('attachment; filename=m0_grid_sample.json', response.headers['Content-Disposition'])
        self.assertEqual(json_util.loads(response.get_data(as_text=True)), sample_documents)
        mock_get_collection.assert_called_once_with('m0_grid')

    def test_admin_archive_downloads_attachment(self):
        self._authenticate_admin_session()

        response = self.client.get('/admin/download-archive')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/octet-stream')
        self.assertIn(
            f'attachment; filename={os.path.basename(self.archive_path)}',
            response.headers['Content-Disposition'],
        )
        self.assertEqual(response.get_data(), b'archive-bytes')


if __name__ == '__main__':
    unittest.main()