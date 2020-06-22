# Python built in modules
import copy
import glob # File searching
import os # Making directories
import importlib.util # importing other modules from files
import warnings # ignore warnings
import sys # sys utils
import pickle
from sys import platform # plotting backend
from pdb import set_trace as stop # debugging

# Graphics
import matplotlib # to set the backend
import matplotlib.pyplot as plt # Plotting
import pychell
plt.style.use(os.path.dirname(pychell.__file__) + os.sep + "gadfly_stylesheet.mplstyle")

# Science/math
from scipy import constants as cs # cs.c = speed of light in m/s
import numpy as np # Math, Arrays
import torch
import scipy.interpolate # Cubic interpolation, Akima interpolation

# llvm
from numba import njit, jit, prange

# Pychell modules
import pychell.config as pcconfig
import pychell.maths as pcmath # mathy equations
import pychell.rvs.forward_models as pcforwardmodels # the various forward model implementations
import pychell.rvs.data1d as pcdata # the data objects
import pychell.rvs.model_components as pcmodelcomponents # the data objects
import pychell.rvs.target_functions as pctargetfuns
import pychell.utils as pcutils
import pychell.rvs.rvcalc as pcrvcalc


def cubic_spline_lsq(forward_models, iter_num=None, nights_for_template=None):
    """Augments the stellar template by fitting the residuals with cubic spline least squares regression. The knot-points are spaced roughly according to the detector grid. The weighting scheme includes (possible inversly) the rms of the fit, the amount of telluric absorption. Weights are also applied such that the barycenter sampling is approximately uniform from vmin to vmax.

    Args:
        forward_models (ForwardModels): The list of forwad model objects
        iter_num (int): The iteration to use.
        nights_for_template (str or list): The nights to consider for averaging residuals to update the stellar template. Options are 'best' to use the night with the highest co-added S/N, a list of indices for specific nights, or an empty list to use all nights. defaults to [] for all nights.
    """
    if nights_for_template is None:
        nights_for_template = forward_models.nights_for_template
        
    if iter_num is None:
        iter_num = len(forward_models[0].best_fit_pars)
    
    # k1 = index for forward model array access
    # k2 = Plot names for forward model objects
    # k3 = index for RV array access
    # k4 = RV plot names
    k1, k2, k3, k4 = forward_models[0].iteration_indices(iter_num)

    current_stellar_template = np.copy(forward_models.templates_dict['star'])
    
    # Storage Arrays for the low res grid
    # This is for the low res reiduals where the star is constructed via a least squares cubic spline.
    # Before the residuals are added, they are normalized.
    waves_shifted_lr = np.empty(shape=(forward_models[0].data.flux.size, forward_models.n_spec), dtype=np.float64)
    residuals_lr = np.empty(shape=(forward_models[0].data.flux.size, forward_models.n_spec), dtype=np.float64)
    tot_weights_lr = np.empty(shape=(forward_models[0].data.flux.size, forward_models.n_spec), dtype=np.float64)
    
    # Weight by 1 / rms^2
    rms = np.array([forward_models[ispec].opt[k1][0] for ispec in range(forward_models.n_spec)])
    rms_weights = 1 / rms**2
    if forward_models[0].models_dict['star'].enabled:
        bad = np.where(rms_weights < 100)[0]
        if bad.size > 0:
            rms_weights[bad] = 0

    # All nights
    if nights_for_template is None or len(nights_for_template) == 0:
        template_spec_indices = np.arange(forward_models.n_spec).astype(int)
    # Night with highest co-added S/N
    if nights_for_template == 'best':
        night_index = determine_best_night(rms, forward_models.n_obs_nights)
        template_spec_indices = list(forward_models.get_all_spec_indices_from_night(night_index, forward_models.n_obs_nights))
    # User specified nights
    else:
        template_spec_indices = []
        for night in nights_for_template:
            template_spec_indices += list(forward_models.get_all_spec_indices_from_night(night - 1, forward_models.n_obs_nights))
            
    # Loop over spectra
    for ispec in range(forward_models.n_spec):

        # De-shift residual wavelength scale according to the barycenter correction
        # Or best doppler shift if using a non flat initial template
        if forward_models[0].models_dict['star'].from_synthetic:
            waves_shifted_lr[:, ispec] = forward_models[ispec].wavelength_solutions[-1] * np.exp(-1 * forward_models[ispec].best_fit_pars[-1][forward_models[ispec].models_dict['star'].par_names[0]].value / cs.c)
        else:
            waves_shifted_lr[:, ispec] = forward_models[ispec].wavelength_solutions[-1] * np.exp(forward_models[ispec].data.bc_vel / cs.c)
            
        residuals_lr[:, ispec] = np.copy(forward_models[ispec].residuals[-1])
        

        # Telluric weights
        tell_flux_hr = forward_models[ispec].models_dict['tellurics'].build(forward_models[ispec].best_fit_pars[k1], forward_models.templates_dict['tellurics'], current_stellar_template[:, 0])
        tell_flux_hr_convolved = forward_models[ispec].models_dict['lsf'].convolve_flux(tell_flux_hr, pars=forward_models[ispec].best_fit_pars[-1])
        tell_flux_lr_convolved = np.interp(forward_models[ispec].wavelength_solutions[-1], current_stellar_template[:, 0], tell_flux_hr_convolved, left=np.nan, right=np.nan)
        tell_weights = tell_flux_lr_convolved**2
        
        tot_weights_lr[:, ispec] = forward_models[ispec].data.badpix * rms_weights[ispec]
        
        # Final weights
        if len(nights_for_template) != 1:
            tot_weights_lr[:, ispec] = tot_weights_lr[:, ispec] * tell_weights
            
        
    # Generate the histogram
    bc_vels = np.array([forward_models[ispec].data.bc_vel for ispec in range(forward_models.n_spec)], dtype=float)
    hist_counts, histx = np.histogram(bc_vels, bins=int(np.min([forward_models.n_spec, 10])), range=(np.min(bc_vels)-1, np.max(bc_vels)+1))
    
    # Check where we have no spectra (no observations in this bin)
    hist_counts = hist_counts.astype(np.float64)
    bad = np.where(hist_counts == 0)[0]
    if bad.size > 0:
        hist_counts[bad] = np.nan
    number_weights = 1 / hist_counts
    number_weights = number_weights / np.nansum(number_weights)

    # Loop over spectra and also weight spectra according to the barycenter sampling
    # Here we explicitly use a multiplicative combination of weights.
    if len(nights_for_template) == forward_models.n_nights:
        for ispec in range(forward_models.n_spec):
            vbc = forward_models[ispec].data.bc_vel
            y = np.where(histx >= vbc)[0][0] - 1
            tot_weights_lr[:, ispec] = tot_weights_lr[:, ispec] * number_weights[y]
            
    # If started from a synthetic template, try and correct the blaze.
    if iter_num == 0 and not forward_models[0].models_dict['star'].from_synthetic:
        for ispec in range(forward_models.n_spec):
            continuum = estimate_continuum(waves_shifted_lr[:, ispec], residuals_lr[:, ispec], width=7, n_knots=5, cont_val=0.9)
            residuals_lr[:, ispec] = residuals_lr[:, ispec] - continuum
            
    # Now to co-add residuals according to a least squares cubic spline
    # Flatten the arrays
    waves_shifted_lr_flat = waves_shifted_lr.flatten()
    residuals_lr_flat = residuals_lr.flatten()
    tot_weights_lr_flat = tot_weights_lr.flatten()
    
    # Remove all bad pixels.
    good = np.where(np.isfinite(waves_shifted_lr_flat) & np.isfinite(residuals_lr_flat) & (tot_weights_lr_flat > 0))[0]
    waves_shifted_lr_flat, residuals_lr_flat, tot_weights_lr_flat = waves_shifted_lr_flat[good], residuals_lr_flat[good], tot_weights_lr_flat[good]

    # Sort the wavelengths
    sorted_inds = np.argsort(waves_shifted_lr_flat)
    waves_shifted_lr_flat, residuals_lr_flat, tot_weights_lr_flat = waves_shifted_lr_flat[sorted_inds], residuals_lr_flat[sorted_inds], tot_weights_lr_flat[sorted_inds]
    
    # Knot points are roughly the detector grid.
    knots_init = np.linspace(waves_shifted_lr_flat[0]+0.01, waves_shifted_lr_flat[-1]-0.01, num=forward_models[0].data.flux.size)
    bad_knots = []
    for iknot in range(len(knots_init) - 1):
        n = np.where((waves_shifted_lr_flat > knots_init[iknot]) & (waves_shifted_lr_flat < knots_init[iknot+1]))[0].size
        if n == 0:
            bad_knots.append(iknot)
    bad_knots = np.array(bad_knots)
    knots = np.delete(knots_init, bad_knots)
    

    # Do the fit
    tot_weights_lr_flat /= np.nansum(tot_weights_lr_flat)
    spline_fitter = scipy.interpolate.LSQUnivariateSpline(waves_shifted_lr_flat, residuals_lr_flat, t=knots[1:-1], w=tot_weights_lr_flat, k=3, ext=1, bbox=[waves_shifted_lr_flat[0], waves_shifted_lr_flat[-1]], check_finite=True)
    
    # Use the fit to determine the hr residuals to add
    residuals_hr_fit = spline_fitter(current_stellar_template[:, 0])

    # Remove bad regions
    bad = np.where((current_stellar_template[:, 0] <= knots[0]) | (current_stellar_template[:, 0] >= knots[-1]))[0]
    if bad.size > 0:
        residuals_hr_fit[bad] = 0

    # Augment the template
    new_flux = current_stellar_template[:, 1] + residuals_hr_fit
    
    bad = np.where(new_flux > 1)[0]
    if bad.size > 0:
        new_flux[bad] = 1

    forward_models.templates_dict['star'][:, 1] = new_flux
    
    
    
def cubic_spline_lsq_nobcweights(forward_models, iter_num=None, nights_for_template=None):
    """Augments the stellar template by fitting the residuals with cubic spline least squares regression. The knot-points are spaced roughly according to the detector grid. This function is identical to cubic_spline_lsq but does not include barycenter weighting.

    Args:
        forward_models (ForwardModels): The list of forwad model objects
        iter_num (int): The iteration to use.
        nights_for_template (str or list): The nights to consider for averaging residuals to update the stellar template. Options are 'best' to use the night with the highest co-added S/N, a list of indices for specific nights, or an empty list to use all nights. defaults to [] for all nights.
    """
    if nights_for_template is None:
        nights_for_template = forward_models.nights_for_template
        
    if iter_num is None:
        iter_num = len(forward_models[0].best_fit_pars)
    
    # k1 = index for forward model array access
    # k2 = Plot names for forward model objects
    # k3 = index for RV array access
    # k4 = RV plot names
    k1, k2, k3, k4 = forward_models[0].iteration_indices(iter_num)

    current_stellar_template = np.copy(forward_models.templates_dict['star'])
    
    # Storage Arrays for the low res grid
    # This is for the low res reiduals where the star is constructed via a least squares cubic spline.
    # Before the residuals are added, they are normalized.
    waves_shifted_lr = np.empty(shape=(forward_models[0].data.flux.size, forward_models.n_spec), dtype=np.float64)
    residuals_lr = np.empty(shape=(forward_models[0].data.flux.size, forward_models.n_spec), dtype=np.float64)
    tot_weights_lr = np.empty(shape=(forward_models[0].data.flux.size, forward_models.n_spec), dtype=np.float64)
    
    # Weight by 1 / rms^2
    rms = np.array([forward_models[ispec].opt[k1][0] for ispec in range(forward_models.n_spec)])
    rms_weights = 1 / rms**2
    if forward_models[0].models_dict['star'].enabled:
        bad = np.where(rms_weights < 100)[0]
        if bad.size > 0:
            rms_weights[bad] = 0

    # All nights
    if nights_for_template is None or len(nights_for_template) == 0:
        template_spec_indices = np.arange(forward_models.n_spec).astype(int)
    # Night with highest co-added S/N
    if nights_for_template == 'best':
        night_index = determine_best_night(rms, forward_models.n_obs_nights)
        template_spec_indices = list(forward_models.get_all_spec_indices_from_night(night_index, forward_models.n_obs_nights))
    # User specified nights
    else:
        template_spec_indices = []
        for night in nights_for_template:
            template_spec_indices += list(forward_models.get_all_spec_indices_from_night(night - 1, forward_models.n_obs_nights))
            
    # Loop over spectra
    for ispec in range(forward_models.n_spec):

        # De-shift residual wavelength scale according to the barycenter correction
        # Or best doppler shift if using a non flat initial template
        if forward_models[0].models_dict['star'].from_synthetic:
            waves_shifted_lr[:, ispec] = forward_models[ispec].wavelength_solutions[-1] * np.exp(-1 * forward_models[ispec].best_fit_pars[-1][forward_models[ispec].models_dict['star'].par_names[0]].value / cs.c)
        else:
            waves_shifted_lr[:, ispec] = forward_models[ispec].wavelength_solutions[-1] * np.exp(forward_models[ispec].data.bc_vel / cs.c)
            
        residuals_lr[:, ispec] = np.copy(forward_models[ispec].residuals[-1])
        

        # Telluric weights
        tell_flux_hr = forward_models[ispec].models_dict['tellurics'].build(forward_models[ispec].best_fit_pars[k1], forward_models.templates_dict['tellurics'], current_stellar_template[:, 0])
        tell_flux_hr_convolved = forward_models[ispec].models_dict['lsf'].convolve_flux(tell_flux_hr, pars=forward_models[ispec].best_fit_pars[-1])
        tell_flux_lr_convolved = np.interp(forward_models[ispec].wavelength_solutions[-1], current_stellar_template[:, 0], tell_flux_hr_convolved, left=np.nan, right=np.nan)
        tell_weights = tell_flux_lr_convolved**2
        
        tot_weights_lr[:, ispec] = forward_models[ispec].data.badpix * rms_weights[ispec]
        
        # Final weights
        if len(nights_for_template) != 1:
            tot_weights_lr[:, ispec] = tot_weights_lr[:, ispec] * tell_weights
            
    # If started from a synthetic template, try and correct the blaze.
    if iter_num == 0 and not forward_models[0].models_dict['star'].from_synthetic:
        for ispec in range(forward_models.n_spec):
            continuum = estimate_continuum(waves_shifted_lr[:, ispec], residuals_lr[:, ispec], width=7, n_knots=5, cont_val=0.9)
            residuals_lr[:, ispec] = residuals_lr[:, ispec] - continuum
            
    # Now to co-add residuals according to a least squares cubic spline
    # Flatten the arrays
    waves_shifted_lr_flat = waves_shifted_lr.flatten()
    residuals_lr_flat = residuals_lr.flatten()
    tot_weights_lr_flat = tot_weights_lr.flatten()
    
    # Remove all bad pixels.
    good = np.where(np.isfinite(waves_shifted_lr_flat) & np.isfinite(residuals_lr_flat) & (tot_weights_lr_flat > 0))[0]
    waves_shifted_lr_flat, residuals_lr_flat, tot_weights_lr_flat = waves_shifted_lr_flat[good], residuals_lr_flat[good], tot_weights_lr_flat[good]

    # Sort the wavelengths
    sorted_inds = np.argsort(waves_shifted_lr_flat)
    waves_shifted_lr_flat, residuals_lr_flat, tot_weights_lr_flat = waves_shifted_lr_flat[sorted_inds], residuals_lr_flat[sorted_inds], tot_weights_lr_flat[sorted_inds]
    
    # Knot points are roughly the detector grid.
    knots_init = np.linspace(waves_shifted_lr_flat[0]+0.01, waves_shifted_lr_flat[-1]-0.01, num=forward_models[0].data.flux.size)
    bad_knots = []
    for iknot in range(len(knots_init) - 1):
        n = np.where((waves_shifted_lr_flat > knots_init[iknot]) & (waves_shifted_lr_flat < knots_init[iknot+1]))[0].size
        if n == 0:
            bad_knots.append(iknot)
    bad_knots = np.array(bad_knots)
    knots = np.delete(knots_init, bad_knots)
    

    # Do the fit
    tot_weights_lr_flat /= np.nansum(tot_weights_lr_flat)
    spline_fitter = scipy.interpolate.LSQUnivariateSpline(waves_shifted_lr_flat, residuals_lr_flat, t=knots[1:-1], w=tot_weights_lr_flat, k=3, ext=1, bbox=[waves_shifted_lr_flat[0], waves_shifted_lr_flat[-1]], check_finite=True)
    
    # Use the fit to determine the hr residuals to add
    residuals_hr_fit = spline_fitter(current_stellar_template[:, 0])

    # Remove bad regions
    bad = np.where((current_stellar_template[:, 0] <= knots[0]) | (current_stellar_template[:, 0] >= knots[-1]))[0]
    if bad.size > 0:
        residuals_hr_fit[bad] = 0

    # Augment the template
    new_flux = current_stellar_template[:, 1] + residuals_hr_fit
    
    bad = np.where(new_flux > 1)[0]
    if bad.size > 0:
        new_flux[bad] = 1

    forward_models.templates_dict['star'][:, 1] = new_flux

            
def weighted_median(forward_models, iter_num=None, nights_for_template=None):
    """Augments the stellar template by considering the weighted median of the residuals on a common high resolution grid.

    Args:
        forward_models (ForwardModels): The list of forwad model objects
        iter_num (int): The iteration to use.
        nights_for_template (str or list): The nights to consider for averaging residuals to update the stellar template. Options are 'best' to use the night with the highest co-added S/N, a list of indices for specific nights, or an empty list to use all nights. defaults to [] for all nights.
    """
    current_stellar_template = np.copy(forward_models.templates_dict['star'])

    # Stores the shifted high resolution residuals (all on the star grid)
    residuals_hr = np.empty(shape=(forward_models.n_model_pix, forward_models.n_spec), dtype=np.float64)
    bad_pix_hr = np.empty(shape=(forward_models.n_model_pix, forward_models.n_spec), dtype=bool)
    tot_weights_hr = np.zeros(shape=(forward_models.n_model_pix, forward_models.n_spec), dtype=np.float64)
    
    # Stores the weighted median grid. Is set via loop, so pre-allocate.
    residuals_median = np.empty(forward_models.n_model_pix, dtype=np.float64)
    
    # These show the min and max of of the residuals for all observations, useful for plotting if desired.
    residuals_max = np.empty(forward_models.n_model_pix, dtype=np.float64)
    residuals_min = np.empty(forward_models.n_model_pix, dtype=np.float64)
    
    
    # Weight by 1 / rms^2
    rms = np.array([forward_models[ispec].opt[iter_num][0] for ispec in range(forward_models.n_spec)]) 
    rms_weights = 1 / rms**2
    
    # bc vels
    bc_vels = np.array([fwm.data.bc_vel for fwm in forward_models], dtype=np.float64)
    
    # All nights
    if nights_for_template is None or type(nights_for_template) is list and len(nights_for_template) == 0:
        template_spec_indices = np.arange(forward_models.n_spec).astype(int)
    # Night with highest co-added S/N
    elif nights_for_template == 'best':
        night_index = determine_best_night(rms, forward_models.n_obs_nights)
        template_spec_indices = list(forward_models.get_all_spec_indices_from_night(night_index, forward_models.n_obs_nights))
    # User specified nights
    else:
        template_spec_indices = []
        for night in nights_for_template:
            template_spec_indices += list(forward_models.get_all_spec_indices_from_night(night - 1, forward_models.n_obs_nights))

    # Loop over spectra
    for ispec in range(forward_models.n_spec):

        # De-shift residual wavelength scale according to the barycenter correction
        # Or best doppler shift if using a non flat initial template
        if forward_models[0].models_dict['star'].from_synthetic:
            wave_stellar_frame = forward_models[ispec].wavelength_solutions[-1] * np.exp(-1 * forward_models[ispec].best_fit_pars[-1][forward_models[ispec].models_dict['star'].par_names[0]].value / cs.c)
        else:
            wave_stellar_frame = forward_models[ispec].wavelength_solutions[-1] * np.exp(forward_models[ispec].data.bc_vel / cs.c)

        # Telluric Weights
        tell_flux_hr = forward_models[ispec].models_dict['tellurics'].build(forward_models[ispec].best_fit_pars[-1], forward_models.templates_dict['tellurics'], current_stellar_template[:, 0])
        tell_flux_hr_convolved = forward_models[ispec].models_dict['lsf'].convolve_flux(tell_flux_hr, pars=forward_models[ispec].best_fit_pars[-1])
        tell_weights_hr = tell_flux_hr_convolved**2

        # For the high res grid, we need to interpolate the bad pixel mask onto high res grid.
        # Any pixels not equal to 1 after interpolation are considered bad.
        bad_pix_hr[:, ispec] = np.interp(current_stellar_template[:, 0], wave_stellar_frame, forward_models[ispec].data.badpix, left=0, right=0)
        bad = np.where(bad_pix_hr[:, ispec] < 1)[0]
        if bad.size > 0:
            bad_pix_hr[bad, ispec] = 0

        # Weights for the high res residuals
        tot_weights_hr[:, ispec] = rms_weights[ispec] * bad_pix_hr[:, ispec] * tell_weights_hr

        # Only use finite values and known good pixels for interpolating up to the high res grid.
        # Even though bad pixels are ignored later when median combining residuals,
        # they will still affect interpolation in unwanted ways.
        good = np.where(np.isfinite(forward_models[ispec].residuals[-1]) & (forward_models[ispec].data.badpix == 1))
        residuals_interp_hr = scipy.interpolate.CubicSpline(wave_stellar_frame[good], forward_models[ispec].residuals[-1][good].flatten(), bc_type='not-a-knot', extrapolate=False)(current_stellar_template[:, 0])

        # Determine values with np.nans and set weights equal to zero
        bad = np.where(~np.isfinite(residuals_interp_hr))[0]
        if bad.size > 0:
            tot_weights_hr[bad, ispec] = 0
            bad_pix_hr[bad, ispec] = 0

        # Also ensure all bad pix in hr residuals are nans, even though they have zero weight
        bad = np.where(tot_weights_hr[:, ispec] == 0)[0]
        if bad.size > 0:
            residuals_interp_hr[bad] = np.nan

        # Pass to final storage array
        residuals_hr[:, ispec] = residuals_interp_hr

    # Additional Weights:
    # Up-weight spectra with poor BC sampling.
    # In other words, we weight by the inverse of the histogram values of the BC distribution
    # Generate the histogram
    hist_counts, histx = np.histogram(bc_vels, bins=int(np.min([forward_models.n_spec, 10])), range=(np.min(bc_vels)-1, np.max(bc_vels)+1))
    
    # Check where we have no spectra (no observations in this bin)
    hist_counts = hist_counts.astype(np.float64)
    bad = np.where(hist_counts == 0)[0]
    if bad.size > 0:
        hist_counts[bad] = np.nan
    number_weights = 1 / hist_counts
    number_weights = number_weights / np.nansum(number_weights)

    # Loop over spectra and check which bin an observation belongs to
    # Then update the weights accordingly.
    if len(nights_for_template) == 0:
        for ispec in range(forward_models.n_spec):
            vbc = forward_models[ispec].data.bc_vel
            y = np.where(histx >= vbc)[0][0] - 1
            tot_weights_hr[:, ispec] = tot_weights_hr[:, ispec] * number_weights[y]

    # Only use specified nights
    tot_weights_hr = tot_weights_hr[:, template_spec_indices]
    bad_pix_hr = bad_pix_hr[:, template_spec_indices]
    residuals_hr = residuals_hr[:, template_spec_indices]

    # Co-add residuals according to a weighted median crunch
    # 1. If all weights at a given pixel are zero, set median value to zero.
    # 2. If there's more than one spectrum, compute the weighted median
    # 3. If there's only one spectrum, use those residuals, unless it's nan.
    for ix in range(forward_models.n_model_pix):
        if np.nansum(tot_weights_hr[ix, :]) == 0:
            residuals_median[ix] = 0
        else:
            if forward_models.n_spec > 1:
                # Further flag any pixels larger than 3*wstddev from a weighted average, but use the weighted median.
                #wavg = pcmath.weighted_mean(residuals_hr[ix, :], tot_weights_hr[ix, :]/np.nansum(tot_weights_hr[ix, :]))
                #wstddev = pcmath.weighted_stddev(residuals_hr[ix, :], tot_weights_hr[ix, :]/np.nansum(tot_weights_hr[ix, :]))
                #diffs = np.abs(wavg - residuals_hr[ix, :])
                #bad = np.where(diffs > 3*wstddev)[0]
                #if bad.size > 0:
                    #tot_weights_hr[ix, bad] = 0
                    #bad_pix_hr[ix, bad] = 0
                residuals_median[ix] = pcmath.weighted_median(residuals_hr[ix, :], weights=tot_weights_hr[ix, :]/np.nansum(tot_weights_hr[ix, :]))
            elif np.isfinite(residuals_hr[ix, 0]):
                residuals_median[ix] = residuals_hr[ix, 0]
            else:
                residuals_median[ix] = 0

        # Store the min and max
        residuals_max[ix] = np.nanmax(residuals_hr[ix, :] * bad_pix_hr[ix, :])
        residuals_min[ix] = np.nanmin(residuals_hr[ix, :] * bad_pix_hr[ix, :])
        
    # Change any nans to zero
    bad = np.where(~np.isfinite(residuals_median))[0]
    if bad.size > 0:
        residuals_median[bad] = 0

    # Augment the template
    new_flux = current_stellar_template[:, 1] + residuals_median

    # Force the max to be less than 1.
    bad = np.where(new_flux > 1)[0]
    if bad.size > 0:
        new_flux[bad] = 1.0
        
    forward_models.templates_dict['star'][:, 1] = new_flux


def weighted_average(forward_models, iter_num=None, nights_for_template=None):
    """Augments the stellar template by considering the weighted average of the residuals on a common high resolution grid.

    Args:
        forward_models (ForwardModels): The list of forwad model objects
        iter_num (int): The iteration to use.
        nights_for_template (str or list): The nights to consider for averaging residuals to update the stellar template. Options are 'best' to use the night with the highest co-added S/N, a list of indices for specific nights, or an empty list to use all nights. defaults to [] for all nights.
    """
    current_stellar_template = np.copy(forward_models.templates_dict['star'])

    # Stores the shifted high resolution residuals (all on the star grid)
    residuals_hr = np.empty(shape=(forward_models.n_model_pix, forward_models.n_spec), dtype=np.float64) + np.nan
    bad_pix_hr = np.empty(shape=(forward_models.n_model_pix, forward_models.n_spec), dtype=bool)
    tot_weights_hr = np.zeros(shape=(forward_models.n_model_pix, forward_models.n_spec), dtype=np.float64)
    
    # Stores the weighted median grid. Is set via loop, so pre-allocate.
    residuals_average = np.empty(forward_models.n_model_pix, dtype=np.float64) + np.nan
    
    # These show the min and max of of the residuals for all observations, useful for plotting if desired.
    residuals_max = np.empty(forward_models.n_model_pix, dtype=np.float64) + np.nan
    residuals_min = np.empty(forward_models.n_model_pix, dtype=np.float64) + np.nan
    
    # Weight by 1 / rms^2
    rms = np.array([forward_models[ispec].opt[iter_num][0] for ispec in range(forward_models.n_spec)]) 
    rms_weights = 1 / rms**2
    
    # bc vels
    bc_vels = np.array([fwm.data.bc_vel for fwm in forward_models], dtype=np.float64)
    
    # All nights
    if nights_for_template is None or type(nights_for_template) is list and len(nights_for_template) == 0:
        template_spec_indices = np.arange(forward_models.n_spec).astype(int)
    # Night with highest co-added S/N
    elif nights_for_template == 'best':
        night_index = determine_best_night(rms, forward_models.n_obs_nights)
        template_spec_indices = list(forward_models.get_all_spec_indices_from_night(night_index, forward_models.n_obs_nights))
    # User specified nights
    else:
        template_spec_indices = []
        for night in nights_for_template:
            template_spec_indices += list(forward_models.get_all_spec_indices_from_night(night - 1, forward_models.n_obs_nights))

    # Loop over spectra
    for ispec in range(forward_models.n_spec):

        # De-shift residual wavelength scale according to the barycenter correction
        # Or best doppler shift if using a non flat initial template
        if forward_models[0].models_dict['star'].from_synthetic:
            wave_stellar_frame = forward_models[ispec].wavelength_solutions[-1] * np.exp(-1 * forward_models[ispec].best_fit_pars[-1][forward_models[ispec].models_dict['star'].par_names[0]].value / cs.c)
        else:
            wave_stellar_frame = forward_models[ispec].wavelength_solutions[-1] * np.exp(forward_models[ispec].data.bc_vel / cs.c)

        # Telluric Weights
        tell_flux_hr = forward_models[ispec].models_dict['tellurics'].build(forward_models[ispec].best_fit_pars[-1], forward_models.templates_dict['tellurics'], current_stellar_template[:, 0])
        tell_flux_hr_convolved = forward_models[ispec].models_dict['lsf'].convolve_flux(tell_flux_hr, pars=forward_models[ispec].best_fit_pars[-1])
        tell_weights_hr = tell_flux_hr_convolved**2

        # For the high res grid, we need to interpolate the bad pixel mask onto high res grid.
        # Any pixels not equal to 1 after interpolation are considered bad.
        bad_pix_hr[:, ispec] = np.interp(current_stellar_template[:, 0], wave_stellar_frame, forward_models[ispec].data.badpix, left=0, right=0)
        bad = np.where(bad_pix_hr[:, ispec] < 1)[0]
        if bad.size > 0:
            bad_pix_hr[bad, ispec] = 0

        # Weights for the high res residuals
        tot_weights_hr[:, ispec] = rms_weights[ispec] * bad_pix_hr[:, ispec] * tell_weights_hr

        # Only use finite values and known good pixels for interpolating up to the high res grid.
        # Even though bad pixels are ignored later when median combining residuals,
        # they will still affect interpolation in unwanted ways.
        good = np.where(np.isfinite(forward_models[ispec].residuals[-1]) & (forward_models[ispec].data.badpix == 1))
        residuals_interp_hr = scipy.interpolate.CubicSpline(wave_stellar_frame[good], forward_models[ispec].residuals[-1][good].flatten(), bc_type='not-a-knot', extrapolate=False)(current_stellar_template[:, 0])

        # Determine values with np.nans and set weights equal to zero
        bad = np.where(~np.isfinite(residuals_interp_hr))[0]
        if bad.size > 0:
            tot_weights_hr[bad, ispec] = 0
            bad_pix_hr[bad, ispec] = 0

        # Also ensure all bad pix in hr residuals are nans, even though they have zero weight
        bad = np.where(tot_weights_hr[:, ispec] == 0)[0]
        if bad.size > 0:
            residuals_interp_hr[bad] = np.nan

        # Pass to final storage array
        residuals_hr[:, ispec] = residuals_interp_hr

    # Additional Weights:
    # Up-weight spectra with poor BC sampling.
    # In other words, we weight by the inverse of the histogram values of the BC distribution
    # Generate the histogram
    hist_counts, histx = np.histogram(bc_vels, bins=int(np.min([forward_models.n_spec, 10])), range=(np.min(bc_vels)-1, np.max(bc_vels)+1))
    
    # Check where we have no spectra (no observations in this bin)
    hist_counts = hist_counts.astype(np.float64)
    bad = np.where(hist_counts == 0)[0]
    if bad.size > 0:
        hist_counts[bad] = np.nan
    number_weights = 1 / hist_counts
    number_weights = number_weights / np.nansum(number_weights)

    # Loop over spectra and check which bin an observation belongs to
    # Then update the weights accordingly.
    if len(nights_for_template) == 0:
        for ispec in range(forward_models.n_spec):
            vbc = forward_models[ispec].data.bc_vel
            y = np.where(histx >= vbc)[0][0] - 1
            tot_weights_hr[:, ispec] = tot_weights_hr[:, ispec] * number_weights[y]

    # Only use specified nights
    tot_weights_hr = tot_weights_hr[:, template_spec_indices]
    bad_pix_hr = bad_pix_hr[:, template_spec_indices]
    residuals_hr = residuals_hr[:, template_spec_indices]
    
    # Co-add residuals according to a weighted median crunch
    # 1. If all weights at a given pixel are zero, set median value to zero.
    # 2. If there's more than one spectrum, compute the weighted median
    # 3. If there's only one spectrum, use those residuals, unless it's nan.
    for ix in range(forward_models.n_model_pix):
        if np.nansum(tot_weights_hr[ix, :]) == 0:
            residuals_average[ix] = 0
        else:
            if forward_models.n_spec > 1:
                # Further flag any pixels larger than 3*wstddev from a weighted average.
                wavg = pcmath.weighted_mean(residuals_hr[ix, :], tot_weights_hr[ix, :])
                wstddev = pcmath.weighted_stddev(residuals_hr[ix, :], tot_weights_hr[ix, :])
                diffs = np.abs(wavg - residuals_hr[ix, :])
                bad = np.where(diffs > 3*wstddev)[0]
                if bad.size > 0:
                    tot_weights_hr[ix, bad] = 0
                    bad_pix_hr[ix, bad] = 0
                residuals_average[ix] = pcmath.weighted_mean(residuals_hr[ix, :], tot_weights_hr[ix, :])
            elif np.isfinite(residuals_hr[ix, 0]):
                residuals_average[ix] = residuals_hr[ix, 0]
            else:
                residuals_average[ix] = 0

        # Store the min and max
        residuals_max[ix] = np.nanmax(residuals_hr[ix, :] * bad_pix_hr[ix, :])
        residuals_min[ix] = np.nanmin(residuals_hr[ix, :] * bad_pix_hr[ix, :])
        
    # Change any nans to zero
    bad = np.where(~np.isfinite(residuals_average))[0]
    if bad.size > 0:
        residuals_average[bad] = 0

    # Augment the template
    new_flux = current_stellar_template[:, 1] + residuals_average

    # Force the max to be less than 1.
    bad = np.where(new_flux > 1)[0]
    if bad.size > 0:
        new_flux[bad] = 1.0
        
    forward_models.templates_dict['star'][:, 1] = new_flux


# Uses pytorch to optimize the template
def global_fit(forward_models, iter_num=None, templates_to_optimize=['star'], nights_for_template=None):
    """Akin to Wobble, this will update the stellar template by performing a gradient-based optimization via ADAM in pytorch considering all observations. Here, the template is a parameter of thousands of points.

    Args:
        forward_models (ForwardModels): The list of forwad model objects
        iter_num (int): The iteration to use.
        templates_to_optimize: For now, only the star is able to be optimized. Future updates will include a lab-frame coherence  simultaneous fit.
        nights_for_template (str or list): The nights to consider for averaging residuals to update the stellar template. Options are 'best' to use the night with the highest co-added S/N, a list of indices for specific nights, or an empty list to use all nights. defaults to [] for all nights.
    """
    # The number of lsf points
    n_lsf_pts = forward_models[0].models_dict['lsf'].nx
    
    wave_hr_master = torch.from_numpy(forward_models.templates_dict['star'][:, 0])
    
    # Grids to optimize
    # Star
    if 'star' in templates_to_optimize:
        star_flux = torch.nn.Parameter(torch.from_numpy(forward_models.templates_dict['star'][:, 1].astype(np.float64)))
        
        # The current best fit stellar velocities
        if not forward_models[0].models_dict['star'].from_synthetic and iter_num == 0:
            star_vels = -1 * torch.from_numpy(np.array([forward_models[ispec].data.bc_vel for ispec in range(forward_models.n_spec)]).astype(np.float64))
        else:
            star_vels = torch.from_numpy(np.array([forward_models[ispec].best_fit_pars[-1][forward_models[ispec].models_dict['star'].par_names[0]].value for ispec in range(forward_models.n_spec)]).astype(np.float64))
    
    # The partial built forward model flux
    raw_models_partial = torch.empty((forward_models.templates_dict['star'][:, 0].size, forward_models.n_spec), dtype=torch.float64)
    
    # The best fit LSF for each spec
    if 'lsf' in forward_models[0].models_dict:
        lsf = torch.empty((n_lsf_pts, forward_models.n_spec), dtype=torch.float64)
    
    # The data flux
    data_flux = torch.empty((forward_models[0].data.flux.size, forward_models.n_spec), dtype=torch.float64)
    
    # Bad pixel arrays for the data
    badpix = torch.empty((forward_models[0].data.flux.size, forward_models.n_spec), dtype=torch.float64)
    
    # The wavelength solutions
    wave_lr = torch.empty((forward_models[0].data.flux.size, forward_models.n_spec), dtype=torch.float64)
    
    # Weights, may just be binary mask
    weights = torch.empty((forward_models[0].data.flux.size, forward_models.n_spec), dtype=torch.float64)

    # Loop over spectra and extract to the above arrays
    for ispec in range(forward_models.n_spec):

        # Get the pars for this iteration
        pars = copy.deepcopy(forward_models[ispec].best_fit_pars[-1])

        # Case 1. Only optimizing star
        if 'star' in templates_to_optimize:
            x, y = forward_models[ispec].build_hr_nostar(pars, iter_num)
            wave_lr[:, ispec], raw_models_partial[:, ispec] = torch.from_numpy(x), torch.from_numpy(y)
            
        # Case 2. Only optimizing lab frame
        #if 'star' in templates_to_optimize:
        #    wave_lr[:, ispec], raw_models_partial[:, ispec] = forward_models[ispec].build_hr_nostar(pars, iter_num)

        # Fetch lsf and flip for torch. As of now torch does not support the negative step
        # Zeroth index is not a typo.
        if 'lsf' in forward_models[0].models_dict:
            lsf[:, ispec] = torch.from_numpy(forward_models[ispec].models_dict['lsf'].build(pars))
            lsf[:, ispec] = torch.from_numpy(np.flip(lsf[:, ispec].numpy(), axis=0).copy())

        # The data and weights, change bad vals to nan
        data_flux[:, ispec] = torch.from_numpy(np.copy(forward_models[ispec].data.flux))
        weights[:, ispec] = torch.from_numpy(np.copy(forward_models[ispec].data.badpix))
        bad = np.where(~np.isfinite(data_flux[:, ispec].numpy()) | ~np.isfinite(weights[:, ispec].numpy()))[0]
        if bad.size > 0:
            data_flux[bad, ispec] = 0
            weights[bad, ispec] = 0

    if torch.cuda.is_available():
        torch.device('cuda')
    else:
        torch.device('cpu')

    # Create the Torch model object
    if 'star' in templates_to_optimize:
        model = StarSolver(star_flux, star_vels, raw_models_partial, wave_lr, weights, data_flux, wave_hr_master, lsf=lsf)

    # Create the Adam optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    print('Optimizing Stellar Template ...', flush=True)

    for epoch in range(400):

        optimizer.zero_grad()

        # Generate the model
        loss = model.forward()

        # Back propagation (gradient calculation)
        loss.backward()

        # Take a step in the best direction (steepest gradient)
        optimizer.step()

        if (epoch + 1) % 10 == 0:
            print('epoch {}, loss {}'.format(epoch + 1, loss.item()), flush=True)

    new_star_flux = model.star_flux.detach().numpy()

    locs = np.where(new_star_flux > 1.0)[0]
    if locs.size > 0:
        new_star_flux[locs] = 1.0
        
    forward_models.templates_dict['star'][:, 1] = new_star_flux

# Class to optimize the forward model
class StarSolver(torch.nn.Module):

    def __init__(self, star_flux, star_vels, raw_model_no_star, wave_lr, weights, data_flux, wave_hr_master, lsf=None):
        super(StarSolver, self).__init__()

        # Parameters to optimize
        self.star_flux = star_flux # the stellar flux
        
        self.raw_model_no_star = raw_model_no_star
        self.wave_lr = wave_lr
        self.star_vels = star_vels
        self.weights = weights
        self.data_flux = data_flux
        self.nx_data, self.n_spec = self.data_flux.shape
        self.nx_lsf = lsf.shape[0]
        if lsf is not None:
            self.lsf = torch.ones(1, 1, self.nx_lsf, self.n_spec, dtype=torch.float64)
        else:
            self.lsf = lsf
        self.lsf[0, 0, :, :] = lsf
        self.nx_pad1 = int(self.nx_lsf / 2) - 1
        self.nx_pad2 = int(self.nx_lsf / 2)
        self.wave_hr_master = wave_hr_master
        self.nx_model = self.wave_hr_master.size()[0]

    def forward(self):
    
        models_lr = torch.empty((self.nx_data, self.n_spec), dtype=torch.float64)
        
        for ispec in range(self.n_spec):
            
            # Doppler shift the stellar wavelength grid used for this observation.
            wave_hr_star_shifted = self.wave_hr_master * torch.exp(self.star_vels[ispec] / cs.c)

            # Interpolate the stellar variable back to master grid
            star = self.Interp1d()(wave_hr_star_shifted, self.star_flux, self.wave_hr_master)
            
            # Convolution. Note: PyTorch convolution is a pain in the ass.
            # Also torch.cat seems to take up too much memory, so a workaround.
            if self.lsf is not None:
                model_p = torch.ones((1, 1, self.nx_model + self.nx_pad1 + self.nx_pad2), dtype=torch.float64)
                model_p[0, 0, self.nx_pad1:(-self.nx_pad2)] = star.flatten() * self.raw_model_no_star[:, ispec]
                conv = torch.nn.Conv1d(in_channels=1, out_channels=1, kernel_size=1, stride=1, padding=0, bias=False)
                conv.weight.data = self.lsf[:, :, :, ispec]
                model = conv(model_p).flatten()
            else:
                model = star.flatten() * self.raw_model_no_star[:, ispec]

            # Interpolate onto data grid
            models_lr[:, ispec] = self.Interp1d()(self.wave_hr_master, model, self.wave_lr[:, ispec])

        # Weighted RMS
        wdiffs2 = (models_lr - self.data_flux)**2 * self.weights
        loss = torch.sqrt(torch.sum(wdiffs2) / (torch.sum(self.weights)))

        return loss

    class Interp1d(torch.autograd.Function):
        def __call__(self, x, y, xnew, out=None):
            return self.forward(x, y, xnew, out)

        def forward(ctx, x, y, xnew, out=None):

            # making the vectors at least 2D
            is_flat = {}
            require_grad = {}
            v = {}
            device = []
            for name, vec in {'x': x, 'y': y, 'xnew': xnew}.items():
                assert len(vec.shape) <= 2, 'interp1d: all inputs must be '\
                                            'at most 2-D.'
                if len(vec.shape) == 1:
                    v[name] = vec[None, :]
                else:
                    v[name] = vec
                is_flat[name] = v[name].shape[0] == 1
                require_grad[name] = vec.requires_grad
                device = list(set(device + [str(vec.device)]))
            assert len(device) == 1, 'All parameters must be on the same device.'
            device = device[0]

            # Checking for the dimensions
            assert (v['x'].shape[1] == v['y'].shape[1]
                    and (
                         v['x'].shape[0] == v['y'].shape[0]
                         or v['x'].shape[0] == 1
                         or v['y'].shape[0] == 1
                        )
                    ), ("x and y must have the same number of columns, and either "
                        "the same number of row or one of them having only one "
                        "row.")

            reshaped_xnew = False
            if ((v['x'].shape[0] == 1) and (v['y'].shape[0] == 1)
               and (v['xnew'].shape[0] > 1)):
                # if there is only one row for both x and y, there is no need to
                # loop over the rows of xnew because they will all have to face the
                # same interpolation problem. We should just stack them together to
                # call interp1d and put them back in place afterwards.
                original_xnew_shape = v['xnew'].shape
                v['xnew'] = v['xnew'].contiguous().view(1, -1)
                reshaped_xnew = True

            # identify the dimensions of output and check if the one provided is ok
            D = max(v['x'].shape[0], v['xnew'].shape[0])
            shape_ynew = (D, v['xnew'].shape[-1])
            if out is not None:
                if out.numel() != shape_ynew[0]*shape_ynew[1]:
                    # The output provided is of incorrect shape.
                    # Going for a new one
                    out = None
                else:
                    ynew = out.reshape(shape_ynew)
            if out is None:
                ynew = torch.zeros(*shape_ynew, dtype=y.dtype, device=device)

            # moving everything to the desired device in case it was not there
            # already (not handling the case things do not fit entirely, user will
            # do it if required.)
            for name in v:
                v[name] = v[name].to(device)

            # calling searchsorted on the x values.
            #ind = ynew
            #searchsorted(v['x'].contiguous(), v['xnew'].contiguous(), ind)
            ind = np.searchsorted(v['x'].contiguous().numpy().flatten(), v['xnew'].contiguous().numpy().flatten())
            ind = torch.tensor(ind)
            # the `-1` is because searchsorted looks for the index where the values
            # must be inserted to preserve order. And we want the index of the
            # preceeding value.
            ind -= 1
            # we clamp the index, because the number of intervals is x.shape-1,
            # and the left neighbour should hence be at most number of intervals
            # -1, i.e. number of columns in x -2
            ind = torch.clamp(ind, 0, v['x'].shape[1] - 1 - 1).long()

            # helper function to select stuff according to the found indices.
            def sel(name):
                if is_flat[name]:
                    return v[name].contiguous().view(-1)[ind]
                return torch.gather(v[name], 1, ind)

            # activating gradient storing for everything now
            enable_grad = False
            saved_inputs = []
            for name in ['x', 'y', 'xnew']:
                if require_grad[name]:
                    enable_grad = True
                    saved_inputs += [v[name]]
                else:
                    saved_inputs += [None, ]
            # assuming x are sorted in the dimension 1, computing the slopes for
            # the segments
            is_flat['slopes'] = is_flat['x']
            # now we have found the indices of the neighbors, we start building the
            # output. Hence, we start also activating gradient tracking
            with torch.enable_grad() if enable_grad else contextlib.suppress():
                v['slopes'] = (
                        (v['y'][:, 1:]-v['y'][:, :-1])
                        /
                        (v['x'][:, 1:]-v['x'][:, :-1])
                    )

                # now build the linear interpolation
                ynew = sel('y') + sel('slopes')*(
                                        v['xnew'] - sel('x'))

                if reshaped_xnew:
                    ynew = ynew.view(original_xnew_shape)

            ctx.save_for_backward(ynew, *saved_inputs)
            return ynew

        @staticmethod
        def backward(ctx, grad_out):
            inputs = ctx.saved_tensors[1:]
            gradients = torch.autograd.grad(
                            ctx.saved_tensors[0],
                            [i for i in inputs if i is not None],
                            grad_out, retain_graph=True)
            result = [None, ] * 5
            pos = 0
            for index in range(len(inputs)):
                if inputs[index] is not None:
                    result[index] = gradients[pos]
                    pos += 1
            return (*result,)
        
        
def determine_best_night(rms, n_obs_nights):
    """Determines the night with the highest co-added S/N given the RMS of the fits.

    Args:
        rms (np.ndarray): The array of RMS values from fitting.
        n_obs_nights (np.ndarray): The number of observations on each night, has length = total number of nights.
        templates_to_optimize: For now, only the star is able to be optimized. Future updates will include a lab-frame coherence  simultaneous fit.
    """
    f = 0
    l = n_obs_nights[0]
    n_nights = len(n_obs_nights)
    nightly_snrs = np.empty(n_nights, dtype=float)
    for inight in range(n_nights):
        
        nightly_snrs[inight] = np.sqrt(np.nansum((1 / rms[f:l]**2)))
        
        if inight < n_nights - 1:
                f += n_obs_nights[inight]
                l += n_obs_nights[inight+1]
                
    best_night_index = np.nanargmax(nightly_snrs)
    return best_night_index

################################
#### More Helpful functions ####
################################


# This calculates the weighted median of a data set for rolling calculations
def estimate_continuum(x, y, width=7, n_knots=8, cont_val=0.9):
    nx = x.size

    continuum_coarse = np.ones(nx, dtype=np.float64)
    for ix in range(nx):
        use = np.where((x > x[ix]-width/2) & (x < x[ix]+width/2))[0]
        if np.all(~np.isfinite(y[use])):
            continuum_coarse[ix] = np.nan
        else:
            continuum_coarse[ix] = pcmath.weighted_median(y[use], weights=None, med_val=cont_val)
    good = np.where(np.isfinite(y))[0]
    knot_points = x[np.linspace(good[0], good[-1], num=n_knots).astype(int)]
    interp_fun = scipy.interpolate.CubicSpline(knot_points, continuum_coarse[np.linspace(good[0], good[-1], num=n_knots).astype(int)], extrapolate=False, bc_type='not-a-knot')
    continuum = interp_fun(x)
    return continuum