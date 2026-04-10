import os
import logging
from functools import lru_cache
from time import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app

from euv_spectra_app.extensions import cache, db


logger = logging.getLogger(__name__)


FITS_METADATA_CACHE_INDEX_KEY = 'fits_metadata:index'


def _fits_metadata_cache_timeout():
    return current_app.config.get('FITS_METADATA_CACHE_TIMEOUT', current_app.config.get('CACHE_DEFAULT_TIMEOUT', 86400))


def _metadata_cache_key(model_subtype, fits_filename):
    subtype = (model_subtype or 'unknown').strip().upper()
    filename = (fits_filename or '').strip()
    return f'fits_metadata:{subtype}:{filename}'


def _remember_metadata_cache_key(cache_key):
    existing_keys = list(cache.get(FITS_METADATA_CACHE_INDEX_KEY) or [])
    if cache_key not in existing_keys:
        existing_keys.append(cache_key)
        cache.set(FITS_METADATA_CACHE_INDEX_KEY, existing_keys, timeout=_fits_metadata_cache_timeout())


def _write_metadata_cache(record):
    cache_key = _metadata_cache_key(record.get('model_subtype'), record.get('fits_filename'))
    cache.set(cache_key, record, timeout=_fits_metadata_cache_timeout())
    _remember_metadata_cache_key(cache_key)


def _metadata_collection():
    return db.get_collection('fits_metadata')


def _load_metadata_record(model_subtype, fits_filename):
    cache_key = _metadata_cache_key(model_subtype, fits_filename)
    cached_record = cache.get(cache_key)
    if cached_record is not None:
        return cached_record

    record = _metadata_collection().find_one(
        {
            'model_subtype': (model_subtype or '').strip().upper(),
            'fits_filename': fits_filename,
        },
        {'_id': 0},
    )
    if record is not None:
        _write_metadata_cache(record)
    return record


def _store_metadata_record(model_subtype, fits_filename, *, available, storage_backend=None, storage_key=None, checked_at=None):
    record = {
        'model_subtype': (model_subtype or '').strip().upper(),
        'fits_filename': fits_filename,
        'available': bool(available),
        'storage_backend': storage_backend,
        'storage_key': storage_key,
        'checked_at': checked_at or time(),
    }
    _metadata_collection().update_one(
        {
            'model_subtype': record['model_subtype'],
            'fits_filename': record['fits_filename'],
        },
        {'$set': record},
        upsert=True,
    )
    _write_metadata_cache(record)
    return record


def clear_fits_metadata_state():
    for cache_key in cache.get(FITS_METADATA_CACHE_INDEX_KEY) or []:
        cache.delete(cache_key)
    cache.delete(FITS_METADATA_CACHE_INDEX_KEY)
    delete_result = _metadata_collection().delete_many({})
    logger.info('Cleared FITS metadata state. deleted_documents=%s', delete_result.deleted_count)
    return delete_result.deleted_count


def get_fits_metadata_summary():
    latest_record = _metadata_collection().find_one(sort=[('checked_at', -1)], projection={'_id': 0, 'checked_at': 1})
    return {
        'documents': _metadata_collection().count_documents({}),
        'last_checked_at': latest_record.get('checked_at') if latest_record else None,
    }


def is_test_fits_filename(filename):
    return 'test' in (filename or '')


def infer_model_subtype_from_filename(filename):
    if not filename:
        return None
    normalized = filename
    if normalized.startswith('PEGASUS.'):
        normalized = normalized[len('PEGASUS.'):]
    subtype = normalized.split('.', 1)[0]
    if subtype.startswith('M') and subtype[1:].isdigit():
        return subtype
    return None


def get_local_fits_path(model_subtype, fits_filename):
    return os.path.join(current_app.root_path, current_app.config['FITS_FOLDER'], model_subtype, fits_filename)


def get_local_test_fits_path(filename):
    return os.path.join(current_app.root_path, current_app.config['FITS_FOLDER'], 'test', filename)


def _s3_enabled():
    return current_app.config.get('FITS_STORAGE_BACKEND') in {'s3', 'hybrid'}


@lru_cache(maxsize=4)
def _build_s3_client(region_name):
    return boto3.client('s3', region_name=region_name)


def _get_s3_client():
    return _build_s3_client(current_app.config.get('FITS_S3_REGION'))


def _get_s3_bucket():
    return current_app.config.get('FITS_S3_BUCKET')


def build_s3_key_candidates(model_subtype, fits_filename):
    if not model_subtype or not fits_filename:
        return []

    prefix = current_app.config.get('FITS_S3_PREFIX', '')
    name_candidates = [fits_filename]
    if fits_filename.startswith('PEGASUS.'):
        name_candidates.append(fits_filename[len('PEGASUS.'):])

    keys = []
    for name in name_candidates:
        path_parts = []
        if prefix:
            path_parts.append(prefix)
        path_parts.append(model_subtype)
        path_parts.append(name)
        key = '/'.join(path_parts)
        if key not in keys:
            keys.append(key)
    return keys


def _read_local_bytes(path):
    with open(path, 'rb') as fits_file:
        return fits_file.read()


def _probe_model_fits_location(model_subtype, fits_filename):
    local_path = get_local_fits_path(model_subtype, fits_filename)
    if os.path.isfile(local_path):
        logger.info('Indexed PEGASUS FITS on local disk: subtype=%s filename=%s', model_subtype, fits_filename)
        return _store_metadata_record(
            model_subtype,
            fits_filename,
            available=True,
            storage_backend='local',
            storage_key=f'{model_subtype}/{fits_filename}',
        )

    if not _s3_enabled():
        logger.info('Indexed PEGASUS FITS as unavailable because S3 backend is disabled: subtype=%s filename=%s', model_subtype, fits_filename)
        return _store_metadata_record(model_subtype, fits_filename, available=False)

    bucket = _get_s3_bucket()
    if not bucket:
        logger.warning('FITS S3 backend is enabled but FITS_S3_BUCKET is not configured.')
        return None

    s3_client = _get_s3_client()
    for key in build_s3_key_candidates(model_subtype, fits_filename):
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            logger.info('Indexed PEGASUS FITS in S3: s3://%s/%s', bucket, key)
            return _store_metadata_record(
                model_subtype,
                fits_filename,
                available=True,
                storage_backend='s3',
                storage_key=key,
            )
        except ClientError as exc:
            error_code = exc.response.get('Error', {}).get('Code')
            if error_code in {'404', 'NoSuchKey', 'NotFound'}:
                continue
            logger.warning('Unable to inspect FITS object s3://%s/%s: %s', bucket, key, exc)
            return None
        except BotoCoreError as exc:
            logger.warning('Unable to inspect FITS object s3://%s/%s: %s', bucket, key, exc)
            return None

    logger.info('Indexed PEGASUS FITS as unavailable after checking configured backends: subtype=%s filename=%s', model_subtype, fits_filename)
    return _store_metadata_record(model_subtype, fits_filename, available=False)


def _get_or_probe_model_fits_metadata(model_subtype, fits_filename, *, refresh=False):
    if not model_subtype or not fits_filename:
        return None

    if not refresh:
        cached_record = _load_metadata_record(model_subtype, fits_filename)
        if cached_record is not None:
            return cached_record

    return _probe_model_fits_location(model_subtype, fits_filename)


def get_test_fits_bytes(filename):
    path = get_local_test_fits_path(filename)
    if not os.path.isfile(path):
        logger.info('Test FITS file not found on local disk: %s', filename)
        return None
    logger.info('Loading test FITS file from local disk: %s', filename)
    return _read_local_bytes(path)


def get_model_fits_bytes(model_subtype, fits_filename):
    if not model_subtype or not fits_filename:
        logger.info('Skipping FITS load because subtype or filename is missing. subtype=%s filename=%s', model_subtype, fits_filename)
        return None

    metadata = _get_or_probe_model_fits_metadata(model_subtype, fits_filename)
    if metadata is None:
        logger.info('Skipping FITS load because metadata lookup failed for subtype=%s filename=%s', model_subtype, fits_filename)
        return None
    if not metadata.get('available'):
        logger.info('Skipping FITS load because metadata marks file unavailable: subtype=%s filename=%s', model_subtype, fits_filename)
        return None

    storage_backend = metadata.get('storage_backend')
    if storage_backend == 'local':
        local_path = get_local_fits_path(model_subtype, fits_filename)
        if os.path.isfile(local_path):
            logger.info('Loading PEGASUS FITS from local disk via metadata: subtype=%s filename=%s', model_subtype, fits_filename)
            return _read_local_bytes(local_path)
        logger.warning('FITS metadata pointed to a missing local file for subtype=%s filename=%s. Refreshing metadata.', model_subtype, fits_filename)
        refreshed = _get_or_probe_model_fits_metadata(model_subtype, fits_filename, refresh=True)
        if refreshed is None or not refreshed.get('available'):
            return None
        if refreshed.get('storage_backend') == 'local':
            local_path = get_local_fits_path(model_subtype, fits_filename)
            if os.path.isfile(local_path):
                return _read_local_bytes(local_path)

    if storage_backend == 's3':
        bucket = _get_s3_bucket()
        if not bucket:
            logger.warning('FITS metadata pointed to S3 but FITS_S3_BUCKET is not configured.')
            return None
        key = metadata.get('storage_key')
        if not key:
            logger.warning('FITS metadata is missing an S3 object key for subtype=%s filename=%s', model_subtype, fits_filename)
            return None
        try:
            logger.info('Loading PEGASUS FITS from S3 via metadata: s3://%s/%s', bucket, key)
            response = _get_s3_client().get_object(Bucket=bucket, Key=key)
            return response['Body'].read()
        except ClientError as exc:
            error_code = exc.response.get('Error', {}).get('Code')
            if error_code in {'404', 'NoSuchKey', 'NotFound'}:
                logger.warning('FITS metadata pointed to a missing S3 object for subtype=%s filename=%s. Refreshing metadata.', model_subtype, fits_filename)
                refreshed = _get_or_probe_model_fits_metadata(model_subtype, fits_filename, refresh=True)
                if refreshed is None or not refreshed.get('available') or refreshed.get('storage_backend') != 's3':
                    return None
                response = _get_s3_client().get_object(Bucket=bucket, Key=refreshed.get('storage_key'))
                return response['Body'].read()
            logger.warning('Unable to fetch FITS object s3://%s/%s: %s', bucket, key, exc)
            return None
        except BotoCoreError as exc:
            logger.warning('Unable to fetch FITS object s3://%s/%s: %s', bucket, key, exc)
            return None

    logger.info('PEGASUS FITS metadata was present but not usable: subtype=%s filename=%s backend=%s', model_subtype, fits_filename, storage_backend)
    return None


def fits_asset_exists(model_subtype, fits_filename):
    if is_test_fits_filename(fits_filename):
        exists = os.path.isfile(get_local_test_fits_path(fits_filename))
        logger.info('Checked test FITS availability: filename=%s exists=%s', fits_filename, exists)
        return exists

    if not model_subtype or not fits_filename:
        logger.info('Skipping FITS availability check because subtype or filename is missing. subtype=%s filename=%s', model_subtype, fits_filename)
        return False

    metadata = _get_or_probe_model_fits_metadata(model_subtype, fits_filename)
    if metadata is None:
        logger.info('Skipping FITS availability check because metadata lookup failed: subtype=%s filename=%s', model_subtype, fits_filename)
        return False

    exists = bool(metadata.get('available'))
    logger.info('Resolved FITS availability from metadata: subtype=%s filename=%s exists=%s backend=%s', model_subtype, fits_filename, exists, metadata.get('storage_backend'))
    return exists