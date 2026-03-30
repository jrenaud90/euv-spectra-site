from euv_spectra_app.extensions import app
from euv_spectra_app.main.routes import main
from euv_spectra_app.api.routes import api
from werkzeug.middleware.proxy_fix import ProxyFix  # ← ADD THIS

app.register_blueprint(main)
app.register_blueprint(api)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

if __name__ == "__main__":
    app.run(port=5002, host='0.0.0.0')