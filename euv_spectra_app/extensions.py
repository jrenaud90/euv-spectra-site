from flask import Flask
from flask_mail import Mail
from flask_caching import Cache
from flask_session import Session
from pymongo import MongoClient
import logging
import os
from os import environ
import tempfile
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from euv_spectra_app.config import Config

cache = Cache()
session_manager = Session()
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config.get('SECRET_KEY')

app.config['APPLICATION_ROOT'] = environ.get('APPLICATION_ROOT', '/apps/pegasus')
app.config['PREFERRED_URL_SCHEME'] = environ.get('PREFERRED_URL_SCHEME', 'https')


def _resolve_log_level(level_name):
    return getattr(logging, str(level_name).upper(), logging.DEBUG)


def _init_logging():
    log_level = _resolve_log_level(app.config.get('LOG_LEVEL', 'DEBUG'))

    gunicorn_error_logger = logging.getLogger('gunicorn.error')
    root_logger = logging.getLogger()

    if gunicorn_error_logger.handlers:
        app.logger.handlers = gunicorn_error_logger.handlers
        root_logger.handlers = gunicorn_error_logger.handlers

    app.logger.setLevel(log_level)
    app.logger.propagate = False
    root_logger.setLevel(log_level)
    gunicorn_error_logger.setLevel(log_level)

    logger.setLevel(log_level)
    logger.propagate = False
    app.logger.info('Pegasus logging initialized at level %s.', logging.getLevelName(log_level))

cache_dir = app.config.get('CACHE_DIR')
if cache_dir:
    os.makedirs(cache_dir, exist_ok=True)

_init_logging()

cache.init_app(app)
session_manager.init_app(app)
mail = Mail(app)
app.jinja_env.filters['zip'] = zip

def _build_dashboard_config_file():
    config_path = app.config.get('DASHBOARD_CONFIG_PATH')
    if config_path:
        return config_path

    required_values = {
        'username': app.config.get('DASHBOARD_USERNAME'),
        'password': app.config.get('DASHBOARD_PASSWORD'),
        'security_token': app.config.get('DASHBOARD_SECURITY_TOKEN'),
    }
    missing_values = [name for name, value in required_values.items() if not value]
    if missing_values:
        logger.warning('Dashboard is enabled but missing required settings: %s', ', '.join(missing_values))
        return None

    config_lines = [
        'APP_VERSION=1.0',
        f"CUSTOM_LINK={app.config['DASHBOARD_CUSTOM_LINK']}",
        f"MONITOR_LEVEL={app.config['DASHBOARD_MONITOR_LEVEL']}",
        f"OUTLIER_DETECTION_CONSTANT={app.config['DASHBOARD_OUTLIER_DETECTION_CONSTANT']}",
        f"USERNAME={app.config['DASHBOARD_USERNAME']}",
        f"PASSWORD={app.config['DASHBOARD_PASSWORD']}",
        f"GUEST_USERNAME={app.config['DASHBOARD_GUEST_USERNAME']}",
        f"GUEST_PASSWORD={app.config['DASHBOARD_GUEST_PASSWORDS']}",
        f"SECURITY_TOKEN={app.config['DASHBOARD_SECURITY_TOKEN']}",
        f"DATABASE={app.config['DASHBOARD_DATABASE_URI']}",
        f"TIMEZONE={app.config['DASHBOARD_TIMEZONE']}",
        f"COLORS={app.config['DASHBOARD_COLORS']}",
    ]

    fd, generated_path = tempfile.mkstemp(prefix='pegasus_dashboard_', suffix='.cfg')
    with os.fdopen(fd, 'w', encoding='utf-8') as config_file:
        config_file.write('\n'.join(config_lines) + '\n')
    return generated_path


def _init_dashboard():
    if not app.config.get('DASHBOARD_ENABLED'):
        logger.info('Flask Monitoring Dashboard is disabled for this deployment.')
        return

    import flask_monitoringdashboard as dashboard
    from flask_monitoringdashboard.database import Base, engine

    config_file = _build_dashboard_config_file()
    if not config_file:
        return

    dashboard.config.init_from(file=config_file)
    dashboard.config.blueprint_url_prefix = '/apps/pegasus'

    try:
        Base.metadata.create_all(engine, checkfirst=True)
    except Exception as exc:
        logger.warning('Dashboard DB init warning (non-fatal): %s', exc)
    dashboard.bind(app)


_init_dashboard()




# ======= DB Setup ==========
uri = environ.get('MONGODB_URI')
my_db = environ.get('MONGODB_DATABASE')


def _ensure_auth_source(mongo_uri, db_name):
    """Add authSource=<db_name> if credentials are present and authSource is missing."""
    if not mongo_uri:
        return mongo_uri
    parsed = urlparse(mongo_uri)
    if not parsed.username or not db_name:
        return mongo_uri
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if 'authSource' in query:
        return mongo_uri
    query['authSource'] = db_name
    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


uri = _ensure_auth_source(uri, my_db)
client = MongoClient(
    uri,
    serverSelectionTimeoutMS=10000,   # 10s to find a server
    connectTimeoutMS=10000,            # 10s to establish connection
    socketTimeoutMS=60000,             # 60s for individual operations
)
db = client.get_database(my_db)

# ======= Collections ==========
model_parameter_grid = db.model_parameter_grid
photosphere_models = db.photosphere_models
mast_galex_times = db.mast_galex_times
fits_metadata = db.fits_metadata
m0_grid = db.m0_grid
m1_grid = db.m1_grid
m2_grid = db.m2_grid
m3_grid = db.m3_grid
m4_grid = db.m4_grid
m5_grid = db.m5_grid
m6_grid = db.m6_grid
m7_grid = db.m7_grid
m8_grid = db.m8_grid
