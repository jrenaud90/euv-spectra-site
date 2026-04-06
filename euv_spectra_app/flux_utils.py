FUV_WAVELENGTH = 1542.3
NUV_WAVELENGTH = 2274.4
FLUX_WAVELENGTHS = {
    'fuv': FUV_WAVELENGTH,
    'nuv': NUV_WAVELENGTH,
}


def convert_microjanskies_to_flux_density(flux, wavelength):
    return (((3e-5) * (float(flux) * 10 ** -6)) / pow(wavelength, 2))


def calculate_surface_scale(dist, rad):
    return (((float(dist) * 3.08567758e18) ** 2) / ((float(rad) * 6.9e10) ** 2))


def scale_flux_to_surface(flux_density, dist, rad):
    return float(flux_density) * calculate_surface_scale(dist, rad)


def subtract_photospheric_flux(flux_density, photo_flux):
    return float(flux_density) - float(photo_flux)


def average_error_from_limits(center_value, upper_value, lower_value):
    new_upper_err = upper_value - center_value
    new_lower_err = center_value - lower_value
    return (new_upper_err + new_lower_err) / 2


def process_galex_flux(flux, photo_flux, dist, rad, wavelength):
    converted_flux = convert_microjanskies_to_flux_density(flux, wavelength)
    scaled_flux = scale_flux_to_surface(converted_flux, dist, rad)
    return subtract_photospheric_flux(scaled_flux, photo_flux)


def process_galex_flux_with_error(flux, flux_err, photo_flux, dist, rad, wavelength):
    processed_flux = process_galex_flux(flux, photo_flux, dist, rad, wavelength)
    if flux_err is None:
        return processed_flux, None

    upper_processed = process_galex_flux(float(flux) + float(flux_err), photo_flux, dist, rad, wavelength)
    lower_processed = process_galex_flux(float(flux) - float(flux_err), photo_flux, dist, rad, wavelength)
    processed_err = average_error_from_limits(processed_flux, upper_processed, lower_processed)
    return processed_flux, processed_err