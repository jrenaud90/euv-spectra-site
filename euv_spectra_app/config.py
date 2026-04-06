# configuring environment variables
import os
from dotenv import load_dotenv
load_dotenv()


def _env_flag(name, default="0"):
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Config(object):
    SECRET_KEY = os.getenv("SECRET_KEY")
    DASHBOARD_ENABLED = _env_flag("DASHBOARD_ENABLED", "0")
    DASHBOARD_CONFIG_PATH = os.getenv("DASHBOARD_CONFIG_PATH")
    DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME")
    DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
    DASHBOARD_GUEST_USERNAME = os.getenv("DASHBOARD_GUEST_USERNAME", "guest")
    DASHBOARD_GUEST_PASSWORDS = os.getenv("DASHBOARD_GUEST_PASSWORDS", "[]")
    DASHBOARD_SECURITY_TOKEN = os.getenv("DASHBOARD_SECURITY_TOKEN")
    DASHBOARD_DATABASE_URI = os.getenv("DASHBOARD_DATABASE_URI", "sqlite:////flask_monitoringdashboard.db")
    DASHBOARD_CUSTOM_LINK = os.getenv("DASHBOARD_CUSTOM_LINK", "dashboard")
    DASHBOARD_MONITOR_LEVEL = os.getenv("DASHBOARD_MONITOR_LEVEL", "3")
    DASHBOARD_OUTLIER_DETECTION_CONSTANT = os.getenv("DASHBOARD_OUTLIER_DETECTION_CONSTANT", "2.")
    DASHBOARD_TIMEZONE = os.getenv("DASHBOARD_TIMEZONE", "UTC")
    DASHBOARD_COLORS = os.getenv("DASHBOARD_COLORS", "{'main':'[0,97,255]', 'static':'[255,153,0]'}")
    ADMIN_PUBLIC_KEY = os.getenv("ADMIN_PUBLIC_KEY")
    ADMIN_PUBLIC_KEY_PATH = os.getenv("ADMIN_PUBLIC_KEY_PATH")
    ADMIN_SESSION_MINUTES = int(os.getenv("ADMIN_SESSION_MINUTES", "30"))
    ADMIN_CHALLENGE_TTL_SECONDS = int(os.getenv("ADMIN_CHALLENGE_TTL_SECONDS", "300"))
    ADMIN_ALLOWED_COLLECTIONS = os.getenv(
        "ADMIN_ALLOWED_COLLECTIONS",
        "model_parameter_grid,photosphere_models,mast_galex_times,m0_grid,m1_grid,m2_grid,m3_grid,m4_grid,m5_grid,m6_grid,m7_grid,m8_grid",
    )

    # for flask sessions
    SESSION_PERMANENT = False
    SESSION_TYPE = "filesystem"

    # for flask mail
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = os.getenv("MAIL_PORT")
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_FAIL_SILENTLY = False

    # for downloads
    FITS_FOLDER = os.getenv("FITS_FOLDER_PATH")

    # for cache
    CACHE_TYPE = 'simple'
    CACHE_DEFAULT_TIMEOUT = 1800

    # for captcha
    RECAPTCHA_PUBLIC_KEY = os.getenv("RECAPTCHA_PUBLIC_KEY")
    RECAPTCHA_PRIVATE_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
