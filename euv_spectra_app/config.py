# configuring environment variables
import os
from dotenv import load_dotenv
load_dotenv()


class Config(object):
    SECRET_KEY = os.getenv("SECRET_KEY")

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