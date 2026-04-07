from euv_spectra_app.extensions import *


LOOKUP_CACHE_TIMEOUT_SECONDS = app.config.get('LOOKUP_CACHE_TIMEOUT', app.config.get('CACHE_DEFAULT_TIMEOUT', 86400))


def _grid_lookup_cache_key(prefix, teff, logg, mass):
    return f'{prefix}:{float(teff):.6f}:{float(logg):.6f}:{float(mass):.6f}'

def get_matching_subtype(teff, logg, mass):
    """Matches to a subtype in the PEGASUS grid.

    Searches the PEGASUS grid for stellar subtype match using stellar effective 
    temperature, surface gravity, and mass. Temperature is weighted higher than
    surface gravity, surface gravity is weighted higher than mass. The weights are
    10, 5, and 2, respectively.

    Args:
        teff: Stellar effective temperature of the user's stellar target.
        logg: Surface gravity of the user's stellar target.
        mass: Mass of the user's stellar target.

    Returns:
        One MongoDB document from the model_parameter_grid collection corresponding to 
        the stellar subtype that best matches the user's target based on temperature, 
        surface gravity, and mass.
    """
    cache_key = _grid_lookup_cache_key('matching_subtype', teff, logg, mass)
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    matching_subtype = model_parameter_grid.aggregate([
        {
            "$addFields": {
                "diff_teff": { "$abs": { "$subtract": [ teff, "$teff" ] } },
                "diff_logg": { "$abs": { "$subtract": [ logg, "$logg" ] } },
                "diff_mass": { "$abs": { "$subtract": [ mass, "$mass" ] } },
            }
        },
        {
            "$addFields" : {
                "diff_sum": { 
                    "$add": [
                        { "$multiply": [ "$diff_teff", 10 ] },
                        { "$multiply": [ "$diff_logg", 2 ] },
                        { "$multiply": [ "$diff_mass", 5 ] }
                    ]
                }
            }
        },
        { "$sort": { "diff_sum": 1 } },
        { "$limit": 1 },
    ])
    result = list(matching_subtype)[0]
    cache.set(cache_key, result, timeout=LOOKUP_CACHE_TIMEOUT_SECONDS)
    return result


def get_matching_photosphere(teff, logg, mass):
    """Matches to a PHOENIX photosphere model.

    Searches a grid of custom PHOENIX calculated photosphere models for best match
    on stellar effective temperature, surface gravity and mass. This will be used
    in later functions to subtract photospheric contributions in the GALEX FUV and
    NUV flux densities.

    Args:
        teff: Stellar effective temperature of the user's stellar target.
        logg: Surface gravity of the user's stellar target.
        mass: Mass of the user's stellar target.

    Returns:
        One MongoDB document from the photosphere_models collection corresponding to 
        the photosphere that best matches the user's target based on temperature,
        surface gravity, and mass.
    """
    cache_key = _grid_lookup_cache_key('matching_photosphere', teff, logg, mass)
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    matching_photosphere_model = photosphere_models.aggregate([
        {
            "$addFields": {
                "diff_teff": { "$abs": { "$subtract": [ teff, "$teff" ] } },
                "diff_logg": { "$abs": { "$subtract": [ logg, "$logg" ] } },
                "diff_mass": { "$abs": { "$subtract": [ mass, "$mass" ] } },
            }
        },
        { "$sort": { "diff_teff": 1, "diff_logg": 1, "diff_mass": 1 } },
        { "$limit": 1 },
    ])
    result = list(matching_photosphere_model)[0]
    cache.set(cache_key, result, timeout=LOOKUP_CACHE_TIMEOUT_SECONDS)
    return result

def search_db(model_collection, fuv, nuv):
    # NORMAL SEARCH: fuv, fuv_err, nuv, and nuv_err are all there, search within limits
    # DETECTION ONLY SEARCH: fuv and nuv are there but no errors, search for closest match
    # SATURATED SEARCH 
        # (w/ normal flux): one flux is saturated, search for anything above it and grow error bars of other flux by 3, then by 5
        # (w/ detection only flux): one flux is saturated, the other is a detection only (no error), search for anything above saturated value and closest match to detection
        # (w/ saturated flux): both fluxes are saturated, search for anything above fluxes and return model w/ lowest chi-squared val
        # (w/ upper limit): one flux is saturated, one is upper limit, search for anything above sat value and below upper lim value, return model with lowest chi-squared val
    # UPPER LIMIT SEARCH 
        # (w/ normal flux): one flux is an upper limit, search for anything below it and grow error bars of other flux by 3, then by 5
        # (w/ detection only flux): one flux is saturated, the other is a detection only (no error), search for anything above saturated value and closest match to detection
        # (w/ saturated flux): both fluxes are saturated, search for anything above fluxes and return model w/ lowest chi-squared val
        # (w/ upper limit): one flux is saturated, one is upper limit, search for anything above sat value and below upper lim value, return model with lowest chi-squared val
    pipeline = []
    # get the query stages for fuv and nuv
    fuv_query = construct_flux_query('fuv', fuv['flag'], fuv['value'], fuv['error'])
    nuv_query = construct_flux_query('nuv', nuv['flag'], nuv['value'], nuv['error'])
    # add stages to the pipeline
    pipeline.append(fuv_query)
    pipeline.append(nuv_query)
    # add the chi squared stage if needed
    chi_squared_stage = { "$addFields": { "chi_squared": { "$round": [ {"$add": [
        {"$divide": [{"$pow": [{"$subtract": ["$nuv", nuv['value']]}, 2]}, nuv['value']]},
        {"$divide": [{"$pow": [{"$subtract": ["$fuv", fuv['value']]}, 2]}, fuv['value']]}
    ]}, 2]}}}
    pipeline.append(chi_squared_stage)
    sort_by_diff_flux_stage = {'$sort': {'diff_flux': 1}}
    sort_by_chi_squared_stage = {'$sort': {'chi_squared': 1}}
    if fuv['flag'] == 'detection_only' or nuv['flag'] == 'detection_only':
        pipeline.append(sort_by_diff_flux_stage)
    else:
        pipeline.append(sort_by_chi_squared_stage)
    models = db.get_collection(model_collection).aggregate(pipeline)
    return models

def construct_flux_query(fieldname, flux_flag, flux_value, flux_err):
    if flux_flag == "normal":
        query = {'$match': {fieldname: {"$gte": flux_value - flux_err, "$lte": flux_value + flux_err}}}
    elif flux_flag == "saturated":
        query = {'$match': {fieldname: {"$gte": flux_value}}}
    elif flux_flag == "upper_limit":
        query = {'$match': {fieldname: {"$lte": flux_value}}}
    elif flux_flag == "detection_only":
        query = {'$addFields': {'diff_flux': {'$abs': {'$subtract': [flux_value, f"${fieldname}"]}}}}
    else:
        query = {}
    return query

def get_models_with_chi_squared(corrected_nuv, corrected_fuv, model_collection):
    """Calculates chi square (χ2) values.

    Calculates the chi square values of FUV and NUV flux densities of each model in
    the stellar subgrid compared to the FUV and NUV flux densities of the user's 
    inputted stellar object.

    Args:
        corrected_nuv: The GALEX NUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        corrected_fuv: The GALEX FUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        model_collection: The name of the MongoDB collection representing the matched 
         stellar subtype.

    Returns:
        The matching MongoDB model collection with all documents containing an 
        additional field, 'chi_squared', that has the calculated chi sqaure value using
        the equation:

        ((model_nuv - galex_nuv) ** 2 / galex_nuv) + ((model_fuv - galex_fuv) ** 2 / galex_fuv)

        The returned collection is sorted from lowest to highest chi squared value.
    """
    models_with_chi_squared = db.get_collection(model_collection).aggregate([
        {"$addFields": 
            {"chi_squared": 
                {"$round": 
                    [ 
                        { "$add": 
                            [ 
                                { "$divide": [ { "$pow": [ { "$subtract": [ "$nuv", corrected_nuv ] }, 2 ] }, corrected_nuv ] },
                                { "$divide": [ { "$pow": [ { "$subtract": [ "$fuv", corrected_fuv ] }, 2 ] }, corrected_fuv ] } 
                            ]
                        }, 
                        2 
                    ]
                } 
            } 
        },
        { "$sort": { "chi_squared": 1 } }
    ])
    return models_with_chi_squared

def get_models_with_weighted_fuv(corrected_nuv, corrected_fuv, model_collection):
    """Calculates chi square value with weighted preference on FUV flux.

    Calculates the chi square values of FUV and NUV flux densities of each model in
    the stellar subgrid compared to the FUV and NUV flux densities of the user's 
    inputted stellar object. Preference is given to FUV by only returning documents
    in the collection that have a chi square value of FUV greater than the chi
    square value of NUV.

    Args:
        corrected_nuv: The GALEX NUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        corrected_fuv: The GALEX FUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        model_collection: The name of the MongoDB collection representing the matched 
         stellar subtype.

    Returns:
        The matching MongoDB model collection with all documents having a FUV chi 
        square value less than the NUV chi square value. All documents contain an 
        additional field, 'chi_squared', that has the calculated chi square value and 
        FUV and NUV combined using the equation:

        ((model_nuv - galex_nuv) ** 2 / galex_nuv) + ((model_fuv - galex_fuv) ** 2 / galex_fuv)

        The returned collection is sorted from lowest to highest chi squared value.
    """
    models_with_fuv_less_than_nuv = db.get_collection(model_collection).aggregate([
        {"$addFields": {
            "chi_squared_fuv": {"$round": [{"$divide": [{"$pow": [{"$subtract": ["$fuv", corrected_fuv]}, 2]}, corrected_fuv]}, 2]},
            "chi_squared_nuv": {"$round": [{"$divide": [{"$pow": [{"$subtract": ["$nuv", corrected_nuv]}, 2]}, corrected_nuv]}, 2]},
            "chi_squared": {"$round": [{"$add": [
                {"$divide": [{"$pow": [{"$subtract": [
                    "$nuv", corrected_nuv]}, 2]}, corrected_nuv]},
                {"$divide": [{"$pow": [{"$subtract": ["$fuv", corrected_fuv]}, 2]}, corrected_fuv]}]
            }, 2]}
        }},
        {"$sort": {"chi_squared": 1}}
    ])
    final_models = []
    for model in list(models_with_fuv_less_than_nuv):
        if model['chi_squared_fuv'] < model['chi_squared_nuv']:
            final_models.append(model)
    return final_models

def get_flux_ratios(corrected_nuv, corrected_fuv, model_collection):
    """TESTING: Computes the chi square value of flux ratios.

    Computes the chi square value of the model NUV to FUV flux ratio compared to
    the GALEX NUV to FUV flux ratio.

    Args:
        corrected_nuv: The GALEX NUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        corrected_fuv: The GALEX FUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        model_collection: The name of the MongoDB collection representing the matched 
         stellar subtype.

    Returns:
        The matching MongoDB collection with an additional field, 'chi_squared',
        that is calculated with the equation:

        ((((model_nuv / model_fuv) - (galex_nuv / galex_fuv)) ** 2) / (galex_nuv / galex_fuv))

        The collection is returned from lowest value of chi_squared to highest.
    """
    models_with_ratio = db.get_collection(model_collection).aggregate([
        {  
            "$addFields": {
                "galex_flux_ratio": {"$divide": [corrected_nuv, corrected_fuv]},
                "model_flux_ratio": {"$divide": ["$nuv", "$fuv"]}
            }
        },
        {
            "$addFields": {
                "chi_squared": {
                    "$divide": [
                        { "$pow": [ { "$subtract": [ "$model_flux_ratio", "$galex_flux_ratio" ] }, 2 ] },
                        "$galex_flux_ratio"
                    ]
                }
            }
        },
        {"$sort": {"chi_squared": 1}}
    ])
    return models_with_ratio

def get_models_within_limits(corrected_nuv, corrected_fuv, corrected_nuv_err, corrected_fuv_err, model_collection):
    """Searches for models within limits of GALEX FUV and NUV flux densities.

    Args:
        corrected_nuv: The GALEX NUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        corrected_nuv_err: The GALEX NUV flux density error (scaled, converted, and 
         photosphere subtracted) of the user's stellar target.
        corrected_fuv: The GALEX FUV flux density (scaled, converted, and photosphere
         subtracted) of the user's stellar target.
        corrected_fuv_err: The GALEX FUV flux density error (scaled, converted, and 
         photosphere subtracted) of the user's stellar target.
        model_collection: The name of the MongoDB collection representing the matched 
         stellar subtype.

    Returns:
        MongoDB documents in the collection that have an FUV flux density value within 
        the upper and lower limits of the GALEX FUV flux density and an NUV flux 
        density value within the upper and lower limits of the GALEX NUV flux density.
    """
    fuv_lower_lim = corrected_fuv - corrected_fuv_err
    fuv_upper_lim = corrected_fuv + corrected_fuv_err
    nuv_lower_lim = corrected_nuv - corrected_nuv_err
    nuv_upper_lim = corrected_nuv + corrected_nuv_err
    models_within_limits = db.get_collection(model_collection).aggregate([
        {
            '$match': {
                'fuv': { '$gte': fuv_lower_lim, '$lte': fuv_upper_lim },
                'nuv': { '$gte': nuv_lower_lim, '$lte': nuv_upper_lim },
            }
        },
        {
            "$addFields": {
                "chi_squared": {
                    "$round": [ 
                        { "$add": 
                            [ 
                                { "$divide": [ { "$pow": [ { "$subtract": [ "$nuv", corrected_nuv ] }, 2 ] }, corrected_nuv ] },
                                { "$divide": [ { "$pow": [ { "$subtract": [ "$fuv", corrected_fuv ] }, 2 ] }, corrected_fuv ] } 
                            ]
                        }, 
                        2 
                    ]
                } 
            } 
        },
        { "$sort": { "chi_squared": 1 } }
    ])
    return models_within_limits
