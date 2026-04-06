# configuring environment variables
import os
from dotenv import load_dotenv
load_dotenv()


class Config(object):
    SECRET_KEY = os.getenv("SECRET_KEY")
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
