import os
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app


logger = logging.getLogger(__name__)


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


def _get_s3_client():
    return boto3.client('s3', region_name=current_app.config.get('FITS_S3_REGION'))


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

    local_path = get_local_fits_path(model_subtype, fits_filename)
    if os.path.isfile(local_path):
        logger.info('Loading PEGASUS FITS from local disk: subtype=%s filename=%s', model_subtype, fits_filename)
        return _read_local_bytes(local_path)

    if not _s3_enabled():
        logger.info('PEGASUS FITS not found locally and S3 backend is disabled: subtype=%s filename=%s', model_subtype, fits_filename)
        return None

    bucket = _get_s3_bucket()
    if not bucket:
        logger.warning('FITS S3 backend is enabled but FITS_S3_BUCKET is not configured.')
        return None

    logger.info('Attempting PEGASUS FITS load from S3: subtype=%s filename=%s bucket=%s', model_subtype, fits_filename, bucket)
    s3_client = _get_s3_client()
    for key in build_s3_key_candidates(model_subtype, fits_filename):
        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            logger.info('Loaded PEGASUS FITS from S3: s3://%s/%s', bucket, key)
            return response['Body'].read()
        except ClientError as exc:
            error_code = exc.response.get('Error', {}).get('Code')
            if error_code in {'404', 'NoSuchKey', 'NotFound'}:
                continue
            logger.warning('Unable to fetch FITS object s3://%s/%s: %s', bucket, key, exc)
            return None
        except BotoCoreError as exc:
            logger.warning('Unable to fetch FITS object s3://%s/%s: %s', bucket, key, exc)
            return None
    logger.info('PEGASUS FITS was not found in any configured backend: subtype=%s filename=%s', model_subtype, fits_filename)
    return None


def fits_asset_exists(model_subtype, fits_filename):
    if is_test_fits_filename(fits_filename):
        exists = os.path.isfile(get_local_test_fits_path(fits_filename))
        logger.info('Checked test FITS availability: filename=%s exists=%s', fits_filename, exists)
        return exists

    if not model_subtype or not fits_filename:
        logger.info('Skipping FITS availability check because subtype or filename is missing. subtype=%s filename=%s', model_subtype, fits_filename)
        return False

    if os.path.isfile(get_local_fits_path(model_subtype, fits_filename)):
        logger.info('PEGASUS FITS is available on local disk: subtype=%s filename=%s', model_subtype, fits_filename)
        return True

    if not _s3_enabled():
        logger.info('PEGASUS FITS is not on local disk and S3 backend is disabled: subtype=%s filename=%s', model_subtype, fits_filename)
        return False

    bucket = _get_s3_bucket()
    if not bucket:
        logger.info('Skipping S3 FITS availability check because FITS_S3_BUCKET is unset.')
        return False

    logger.info('Checking PEGASUS FITS availability in S3: subtype=%s filename=%s bucket=%s', model_subtype, fits_filename, bucket)
    s3_client = _get_s3_client()
    for key in build_s3_key_candidates(model_subtype, fits_filename):
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            logger.info('PEGASUS FITS is available in S3: s3://%s/%s', bucket, key)
            return True
        except ClientError as exc:
            error_code = exc.response.get('Error', {}).get('Code')
            if error_code in {'404', 'NoSuchKey', 'NotFound'}:
                continue
            logger.warning('Unable to inspect FITS object s3://%s/%s: %s', bucket, key, exc)
            return False
        except BotoCoreError as exc:
            logger.warning('Unable to inspect FITS object s3://%s/%s: %s', bucket, key, exc)
            return False
    logger.info('PEGASUS FITS is not available in configured backends: subtype=%s filename=%s', model_subtype, fits_filename)
    return False