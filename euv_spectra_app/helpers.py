import json
import logging
from astropy.io import fits
import plotly.graph_objects as go
from euv_spectra_app.extensions import *
from euv_spectra_app.models import StellarObject, ProperMotionData, GalexFluxes


logger = logging.getLogger(__name__)


def build_flux_context(stellar_object):
    """Keep only the stellar fields needed by flux processing across requests."""
    return {
        'teff': getattr(stellar_object, 'teff', None),
        'logg': getattr(stellar_object, 'logg', None),
        'mass': getattr(stellar_object, 'mass', None),
        'dist': getattr(stellar_object, 'dist', None),
        'rad': getattr(stellar_object, 'rad', None),
        'stellar_subtype': getattr(stellar_object, 'stellar_subtype', None),
    }


def remove_objs_from_obj_dict(obj_dict):
            del obj_dict['fluxes']
            del obj_dict['pm_data']
            return obj_dict


def insert_data_into_form(obj, form):
    attrs = vars(obj)
    for attr_name, attr_value in attrs.items():
        if attr_name == 'fluxes':
            # is an object, go again
            insert_data_into_form(attr_value, form)
        elif hasattr(form, attr_name):
            # is not an object, check if it exists in form and if True, add to form data
            radio_input = getattr(form, attr_name)
            radio_input.choices.insert(
                0, (attr_value, attr_value))
            

def to_json(obj):
    # Check if the object is a simple data type
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # Check if the object is a dictionary
    if isinstance(obj, dict):
        # Recursively call to_json on each value in the dictionary
        return {key: to_json(value) for key, value in obj.items()}

    # Check if the object is a list or tuple
    if isinstance(obj, (list, tuple)):
        # Recursively call to_json on each element in the list or tuple
        return [to_json(element) for element in obj]

    # If the object has a __dict__ attribute, it's probably a custom object
    if hasattr(obj, '__dict__'):
        # Recursively call to_json on each attribute of the object
        return to_json(obj.__dict__)

    # If all else fails, raise a TypeError
    logger.warning('Encountered non-serializable object of type %s', type(obj).__name__)
    raise TypeError(f'Object of type {type(obj)} is not JSON serializable')


def serialize_stellar_object(stellar_object):
    payload = to_json(stellar_object)
    payload.pop('modal_error_msgs', None)
    payload.pop('modal_page_error_msg', None)

    fluxes = payload.get('fluxes')
    if isinstance(fluxes, dict):
        # The top-level stellar fields are enough to reconstruct the flux context later.
        fluxes.pop('stellar_obj', None)

    return json.dumps(payload)


def from_json(json_str):
    # Deserialize the JSON formatted string back into an object
    if json_str is not None:
        data = json.loads(json_str)
        stellar_target_obj = StellarObject()
        proper_motion_obj = ProperMotionData()
        galex_fluxes_obj = GalexFluxes()
        for key, value in data.items():
            if key == 'pm_data' and value is not None:
                proper_motion_dict = value
                for pm_key, pm_value in proper_motion_dict.items():
                    setattr(proper_motion_obj, pm_key, pm_value)
            elif key == 'fluxes' and value is not None:
                galex_fluxes_dict = value
                for flux_key, flux_value in galex_fluxes_dict.items():
                    setattr(galex_fluxes_obj, flux_key, flux_value)
            setattr(stellar_target_obj, key, value)
        stellar_target_obj.pm_data = proper_motion_obj
        stellar_target_obj.fluxes = galex_fluxes_obj
        return stellar_target_obj
    else:
        # if there is no json string, that means the session timed out, return an empty stellar object
        return StellarObject()


def deserialize_stellar_object(json_str):
    stellar_object = from_json(json_str)
    if hasattr(stellar_object, 'fluxes') and stellar_object.fluxes is not None:
        stellar_object.fluxes.stellar_obj = build_flux_context(stellar_object)
    return stellar_object


def create_plotly_graph(files):
    """Creates a plotly graph with data from FITS files.
    
    Args:
        files: A dictionary of dictionaries with FITS files to pull data from and a file tag to include in the legend.
    
    Returns:
        A plotly figure. Will then be json serialized and sent to the front end.
    """
    # TODO: Make a smooth plot function where there is a JS option to toggle vis of smoothed and non-smoothed graph
    # STEP 1: initialize figure
    fig = go.Figure()
    colors = ['#2E42FC', '#EE26DB', '#FF79AE', '#FE6201', '#FFBC28', '#DB2681', '#BBBBBB', '#00E4B0', '#7FFF1D']
    all_buttons = []
    model_buttons = []
    flux_buttons = []
    # STEP 2: for each file, add new trace with data
    for key, value in files.items():
        if 'model' in key:
            # get model data from fits file
            hst = fits.open(value['filepath'])
            data = hst[1].data
            w_obs = data['WAVELENGTH'][0]
            f_obs = data['FLUX'][0]
            # get final model name by checking for flags or index #
            model_name = f"<b>Model {value['index'] + 1} Spectrum</b>"
            if value['index'] == 0:
                if 'flag' in value:
                    value['flag'] += ',<br> Best Match'
                else:
                    value['flag'] = 'Best Match'
            if 'flag' in value:
                model_name = f"<b>Model {value['index'] + 1} Spectrum<br> ({value['flag']})</b>"
            # Plot model
            fig.add_trace(go.Scatter(
                x=w_obs, y=f_obs, name=model_name, line=dict(color=colors[value['index']], width=1)))
            all_buttons.append(True)
            model_buttons.append(True)
            flux_buttons.append(False)
            # Group NUV, FUV, and EUV data points
            fig.add_trace(go.Scatter(
                x=[2315, 1542, 500], 
                y=[value['nuv'], value['fuv'], value['euv']],
                name=f'Model {value["index"] + 1} Fluxes',
                mode='markers',
                marker=dict(color=colors[value['index']], line=dict(color="Black", width=2), size=12),
                hovertemplate='<b>%{text}</b>: %{y:.2f}<extra></extra>',
                text=['NUV', 'FUV', 'EUV'],
                legendgroup=f'Model {value["index"] + 1} Fluxes',
            ))
            all_buttons.append(True)
            model_buttons.append(False)
            flux_buttons.append(True)
    for key, value in files.items():
        if 'galex' in key:
            symbol = 'circle'
            hovertemplate = '<b>%{text}</b>: %{y:.2f} <extra></extra>'
            err = [None]
            err_visible = False
            if 'flag' in value and value['flag'] == 'saturated':
                symbol = 'arrow-up'
                value['name'] += '<sup>[3]</sup>'
            elif 'flag' in value and value['flag'] == 'upper_limit':
                symbol = 'arrow-down'
                value['name'] += '<sup>[4]</sup>'
            if 'flux_density_err' in value:
                err = [value['flux_density_err']]
                err_visible = True
                hovertemplate = '<b>%{text}</b>: %{y:.2f} ± %{customdata:.2f} <extra></extra>'
            fig.add_trace(go.Scatter(
                x=[value['wavelength']], y=[value['flux_density']], name=value['name'], mode='markers', 
                marker=dict(color='Black', symbol=symbol, size=10),
                error_y=dict(type='data', array=err, visible=err_visible, color='Black', thickness=1.5),
                hovertemplate=hovertemplate,
                customdata = err,
                text=[value['name']]
            ))
            all_buttons.append(True)
            model_buttons.append(False)
            flux_buttons.append(True)
    # Generate the menu buttons dynamically
    buttons = list([
        dict(label="View All", method="update", args=[{"visible": all_buttons}, {"title": "All"}]),
        dict(label="View All Models", method="update", args=[{"visible": model_buttons}, {"title": "All Models"}]),
        dict(label="View All Fluxes", method="update", args=[{"visible": flux_buttons}, {"title": "All Fluxes"}])
    ])
    # STEP 3: Add additional styling
    fig.update_layout(
        xaxis=dict(title='Wavelength (Å)', range=[10, 3000]), # Set x axis constraints for first load
        yaxis=dict(title='Flux Density (erg/cm2/s/Å)', type='log', range=[-4, 7], tickformat='.0e'), # Set y axis constraints for first load and scale logarithmically
        showlegend=True, # Show the legend
        updatemenus=[
            go.layout.Updatemenu(
                buttons=buttons, # Add true false button dicts for each menu option
                direction="down", # Set to a dropdown menu
                pad={"r": 10, "t": 10},
                showactive=True, # Show the active menu option
                x=0.5,  # Set x value to 0.5 for center alignment
                xanchor="center",  # Set xanchor to "center" for center alignment
                y=1.1,
                yanchor="top"
            ),
        ]
    )
    return fig
