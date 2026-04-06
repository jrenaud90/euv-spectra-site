"""Compatibility exports for the Pegasus application package.

The runtime Flask app is defined in euv_spectra_app.extensions. Keeping the package
root side-effect free avoids constructing a second Flask app during import.
"""

__all__ = ["app", "cache", "client", "db", "mail", "session_manager"]


def __getattr__(name):
	if name in __all__:
		from euv_spectra_app import extensions

		return getattr(extensions, name)
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")