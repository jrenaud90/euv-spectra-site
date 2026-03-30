from flask import Flask
from flask_mail import Mail
from flask_caching import Cache
from pymongo import MongoClient
from os import environ
from euv_spectra_app.config import Config
import flask_monitoringdashboard as dashboard

cache = Cache()

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = environ.get('SECRET_KEY')

app.config['APPLICATION_ROOT'] = environ.get('APPLICATION_ROOT', '/apps/pegasus')
app.config['PREFERRED_URL_SCHEME'] = environ.get('PREFERRED_URL_SCHEME', 'https')

cache.init_app(app)
mail = Mail(app)
app.jinja_env.filters['zip'] = zip

dashboard.config.init_from(file='/config.py')
dashboard.config.blueprint_url_prefix = '/apps/pegasus'
dashboard.bind(app)

# hello!


#test number 2!

# ======= DB Setup ==========
uri = environ.get('MONGODB_URI')
client = MongoClient(
    uri,
    serverSelectionTimeoutMS=10000,   # 10s to find a server
    connectTimeoutMS=10000,            # 10s to establish connection
    socketTimeoutMS=60000,             # 60s for individual operations
)
my_db = environ.get('MONGODB_DATABASE')
db = client.get_database(my_db)

# ======= Collections ==========
model_parameter_grid = db.model_parameter_grid
photosphere_models = db.photosphere_models
mast_galex_times = db.mast_galex_times
m0_grid = db.m0_grid
m1_grid = db.m1_grid
m2_grid = db.m2_grid
m3_grid = db.m3_grid
m4_grid = db.m4_grid
m5_grid = db.m5_grid
m6_grid = db.m6_grid
m7_grid = db.m7_grid
m8_grid = db.m8_grid
