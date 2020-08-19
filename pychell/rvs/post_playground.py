import pychell.rvs.post_parser as parser
import pychell.rvs.rvcalc as pcrvcalc
import numpy as np
import matplotlib.pyplot as plt
import pychell
import pychell.rvs.forward_models as pcfoward_models
import os
import copy
import scipy.signal
plt.style.use(os.path.dirname(pychell.__file__) + os.sep + "gadfly_stylesheet.mplstyle")
import datetime
from pdb import set_trace as stop

def combine_rvs(output_path_root, bad_rvs_dict=None, do_orders=None, iter_index=None, templates=False, method=None, use_rms=False, debug=False, xcorr=False, phase_to=None, tc=None):
    """Combines RVs across orders through a weighted TFA scheme.

    Args:
        output_path_root (str): The full output path for this run.
        bad_rvs_dict (dict, optional): A bad rvs dictionary. Possible keys are 1. 'bad_spec' with an item being a list of bad bad spectra. These spectra for all orders are flagged. 2. 'bad_nights' where all observations on that night are flagged. Defaults to None.
        do_orders (list, optional): A list of which orders to work with. Defaults to None, including all orders.
        iter_index (int or str, optional): Which iteration index to use. Use 'best' for  the iteration with the lowest long term stddev. Defaults to the last index.
        templates (bool, optional): Whether or not to compute the rv content from the stellar template and consider that for weights. Defaults to None.
        method (str, optional): Which method in rvcalc to call. Defaults to combine_orders.
        use_rms (bool, optional): Whether or not to consider the rms of the fits as weights. Defaults to False.
        debug (bool, optional): If True, the code stops using pdb.set_trace() before exiting this function. Defaults to False.
        xcorr (bool, optional): Whether or not to use the xcorr RVs instead of the NM RVs. Defaults to False.
        phase_to (float, optional): The period to phase to for plotting the RVs.
        tc (float, optional): The tc to phase to for plotting the RVs.
    Returns:
        tuple: The results returned by the call to method.
    """
    # Get the orders
    if do_orders is None:
        do_orders = parser.get_orders(output_path_root)
    n_orders = len(do_orders)
    
    # The method to combine rvs with
    if method is None:
        rv_method = getattr(pcrvcalc, 'combine_orders_fast')
    else:
        rv_method = getattr(pcrvcalc, method)
    
    # Get the tag for this run
    fwms = []
    for o in do_orders:
        fwms.append(parser.parse_forward_model(output_path_root, o, 1))
    tag = fwms[0].tag + '_' + datetime.date.today().strftime("%d%m%Y")
    index_offset = int(not fwms[0].models_dict['star'].from_synthetic)
    star_name = fwms[0].star_name
    spectrograph = fwms[0].spectrograph
    
    # Parse the RVs
    rvs_dict = parser.parse_rvs(output_path_root, do_orders=do_orders)
    
    n_obs_nights = rvs_dict['n_obs_nights']
    
    # Mask rvs
    rvs_dict, mask = gen_rv_mask(rvs_dict, bad_rvs_dict)
    
    # Number of spectra and nights
    n_spec = np.sum(rvs_dict['n_obs_nights'])
    n_nights = len(rvs_dict['n_obs_nights'])
    n_iters = rvs_dict['rvs'].shape[2]

    # Parse the RMS and rvs, single iteration
    rms_all = parser.parse_rms(output_path_root, do_orders=do_orders)

    # Regenerate nightly rvs
    for o in range(n_orders):
        for jiter in range(n_iters):
            
            # NM RVs
            rvs_dict['rvs_nightly'][o, :, jiter], rvs_dict['unc_nightly'][o, :, jiter] = pcrvcalc.compute_nightly_rvs_single_order(rvs_dict['rvs'][o, :, jiter], 1 / rms_all[o, :, jiter + index_offset]**2, rvs_dict['n_obs_nights'], flag_outliers=False)
            
            # xcorr RVs
            if rvs_dict['do_xcorr']:
                rvs_dict['rvsx_nightly'][o, :, jiter], rvs_dict['uncx_nightly'][o, :, jiter] = pcrvcalc.compute_nightly_rvs_single_order(rvs_dict['rvs'][o, :, jiter], 1 / rms_all[o, :, jiter + index_offset]**2, rvs_dict['n_obs_nights'], flag_outliers=False)
            
        
    # Determine which iteration to use
    if iter_index is None:
        iter_indexes = np.zeros(n_orders).astype(int) + n_iters - 1
    elif iter_index == 'best':
        _, iter_indexes = get_best_iterations(rvs_dict, xcorr)
    else:
        iter_indexes = np.zeros(n_orders).astype(int) + iter_index
        
    # Summary of rvs
    print_rv_summary(rvs_dict, bad_rvs_dict, do_orders, iter_indexes, xcorr)
        
    # Get rms for all orders x spectra
    rms = np.zeros((n_orders, n_spec))
    for o in range(n_orders):
        rms[o, :] = rms_all[o, :, iter_indexes[o] + index_offset]
        
    # S / N
    snrs = np.nanmedian(1 / rms, axis=1)
    nightly_snrs = np.full(shape=(n_orders, n_nights), fill_value=np.nan)
    for o in range(n_orders):
        f, l = 0, n_obs_nights[0]
        for i in range(n_nights):
            nightly_snrs[o, i] = np.nansum((1 / rms[o, f:l])**2)**0.5
            if i < n_nights - 1:
                f += n_obs_nights[i]
                l += n_obs_nights[i+1]
            
    # Median nightly S / N for each order to compare against the photon limit
    nightly_snrs = np.nanmedian(nightly_snrs, axis=1)
        
    
    # Get for RVs for the desired iterations
    rvs = np.zeros((n_orders, n_spec))
    unc_nightly = np.zeros((n_orders, n_nights))
    rvs_nightly = np.zeros((n_orders, n_nights))
    for o in range(n_orders):
        if xcorr:
            rvs[o, :] = rvs_dict['rvsx'][o, :, iter_indexes[o]]
            rvs_nightly[o, :] = rvs_dict['rvsx_nightly'][o, :, iter_indexes[o]]
            unc_nightly[o, :] = rvs_dict['uncx_nightly'][o, :, iter_indexes[o]]
        else:
            rvs[o, :] = rvs_dict['rvs'][o, :, iter_indexes[o]]
            rvs_nightly[o, :] = rvs_dict['rvs_nightly'][o, :, iter_indexes[o]]
            unc_nightly[o, :] = rvs_dict['unc_nightly'][o, :, iter_indexes[o]]
    
    # Compute RV content of each order if set
    if templates is not None and len(templates) > 0:
        rvcs = np.zeros(n_orders)
        stellar_templates = parser.parse_stellar_templates(output_path_root, do_orders=do_orders, iter_indexes=iter_indexes)
        for o in range(n_orders):
            bad = np.where(fwms[o].data.badpix == 0)[0]
            wave = fwms[o].models_dict['wavelength_solution'].build(fwms[o].initial_parameters)
            wave[bad] = np.nan
            rvc = np.zeros(len(templates))
            for i, t in enumerate(templates):
                if t == 'star':
                    _, rvc[i] = pcrvcalc.compute_rv_content(stellar_templates[o][:, 0], stellar_templates[o][:, 1], snr=nightly_snrs[o], blaze=True, ron=0,width=fwms[o].initial_parameters[fwms[o].models_dict['lsf'].par_names[0]].value, sampling=None, wave_to_sample=wave)
                else:
                    _, rvc[i] = pcrvcalc.compute_rv_content(fwms[o].templates_dict[t][:, 0], fwms[o].templates_dict[t][:, 1], snr=nightly_snrs[o], blaze=True, ron=0,width=fwms[o].initial_parameters[fwms[o].models_dict['lsf'].par_names[0]].value, sampling=None, wave_to_sample=wave)
            rvcs[o] = np.nansum(rvc**2)**0.5
    else:
        rvcs = np.zeros(n_orders) + np.nanmedian(unc_nightly)

    # Generate weights
    rvs_dict, weights = gen_rv_weights(rvs_dict, bad_rvs_dict, rms=rms, rvcs=rvcs)
    
    # Combine the orders via tfa, sort of
    rvs_out = rv_method(rvs, rvs_nightly, unc_nightly, weights, rvs_dict['n_obs_nights'])
    
    # Plot the final rvs
    fname = output_path_root + tag + '_final_rvs.png'
    plot_final_rvs(star_name, spectrograph, rvs_dict['BJDS'], rvs_dict['BJDS_nightly'], *rvs_out, phase_to=phase_to, show=True, fname=None, tc=tc)

    # Save to a text file
    fname = output_path_root + tag + '_final_rvs.txt'
    np.savetxt(fname, np.array([rvs_dict['BJDS'], rvs_out[0], rvs_out[1]]).T, delimiter=',')
    fname = output_path_root + tag + '_final_rvs_nightly.txt'
    np.savetxt(fname, np.array([rvs_dict['BJDS_nightly'], rvs_out[2], rvs_out[3]]).T, delimiter=',')
    
    # redchi2s, redchi2s_nightly = compute_redchi2s(rvs_out[0], rvs_out[1], rvs_out[2], rvs_out[3], rvs_dict['n_obs_nights'])
    
    # Plot the RV contents and error bars
    plt.plot(do_orders, rvcs, label='Photon noise limit', lw=2, marker='X', markersize=12, mfc='hotpink', c='black')
    plt.title(star_name.replace('_', ' ') + ' ' + spectrograph + ' RV Precision')
    plt.plot(do_orders, np.nanmedian(unc_nightly, axis=1), label='Median Nightly RV uncertainties', lw=2, marker='X', markersize=12, mfc='green')
    plt.xticks(do_orders)
    plt.legend()
    plt.ylabel('$\sigma_{RV}$')
    plt.xlabel('Order')
    plt.show()
    
    #rvs_out += (redchi2s,)
    
    if debug:
        stop()
        
    return rvs_out
    
def compute_redchi2s(rvs_single, unc_single, rvs_nightly, unc_nightly, n_obs_nights):
    n_nights = len(rvs_nightly)
    f, l = 0, n_obs_nights[0]
    redchi2s = np.zeros(n_nights)
    redchi2s_nightly = np.zeros(n_nights)
    redchi2s_nightly[:] = np.nan
    redchi2s[:] = np.nan
    for inight in range(n_nights):
        ng = np.where(np.isfinite(rvs_single[f:l]))[0].size
        if ng == 1:
            continue
        redchi2s[inight] = np.nansum(((rvs_single[f:l] - rvs_nightly[inight]) / unc_single[f:l])**2) / (ng - 1)
        if inight < n_nights - 1:
            f += n_obs_nights[inight]
            l += n_obs_nights[inight+1]
    return redchi2s, redchi2s_nightly
    
def lsperiodogram(t, rvs, pmin=1.3, pmax=None, dp=0.01):
    """Computes a Lomb-Scargle periodogram.

    Args:
        t (np.ndarray): The independent variable.
        rvs (np.ndarray): The dependent variable.
        pmin (float, optional): . Defaults to 1.3.
        pmax (float, optional): The max period to consider. Defaults to 1.5 * time_baseline
    Returns:
        np.ndarray: The periods.
        np.ndarray: The LS periodogram
    """
    good = np.where(np.isfinite(rvs))[0]
    dt = np.nanmax(t[good]) - np.nanmin(t[good])
    tp = np.arange(pmin, 1.5*dt, dp)
    af = 2 * np.pi / tp
    pgram = scipy.signal.lombscargle(t[good], rvs[good] - np.median(rvs[good]), af)
    return tp, pgram
    
def gen_rv_mask_single_order(bad_rvs_dict, n_obs_nights):
    n_nights = len(n_obs_nights)
    n_spec = np.sum(n_obs_nights)
    mask = np.ones(n_spec, dtype=float)
    if 'bad_nights' in bad_rvs_dict:
        for i in bad_rvs_dict['bad_nights']:
            mask[pcfoward_models.ForwardModel.get_all_spec_indices_from_night(i, n_obs_nights)] = 0
    
    if 'bad_spec' in bad_rvs_dict:
        for i in bad_rvs_dict['bad_spec']:
            mask[i] = 0
    
    return mask

def print_rv_summary(rvs_dict, bad_rvs_dict, do_orders, iter_indexes, xcorr):
    
    n_ord, _, n_iters = rvs_dict['rvs'].shape
    n_obs_nights = rvs_dict['n_obs_nights']
    
    for o in range(n_ord):
        print('Order ' + str(do_orders[o]))
        for k in range(n_iters):
            if xcorr:
                stddev = np.nanstd(rvs_dict['rvsx'][o, :, k])
            else:
                stddev = np.nanstd(rvs_dict['rvs'][o, :, k])
            if k == iter_indexes[o]:
                print(' ** Iteration ' +  str(k + 1) + ': ' + str(round(stddev, 4)) + ' m/s')
            else:
                print('    Iteration ' +  str(k + 1) + ': ' + str(round(stddev, 4)) + ' m/s')
            

def get_best_iterations(rvs_dict, xcorr):
    
    n_iters = rvs_dict['rvs'].shape[2]
    n_orders = rvs_dict['rvs'].shape[0]
    best_iters = np.zeros(n_orders, dtype=int)
    best_stddevs = np.zeros(n_orders, dtype=int)
    for o in range(n_orders):
        stddevs = np.zeros(n_iters) + np.nan
        for k in range(n_iters):
            if xcorr:
                stddevs[k] = np.nanstd(rvs_dict['rvsx_nightly'][o, :, k])
            else:
                stddevs[k] = np.nanstd(rvs_dict['rvs_nightly'][o, :, k])
        best_iters[o] = np.nanargmin(stddevs)
        best_stddevs[o] = stddevs[best_iters[o]]
    return stddevs, best_iters


def gen_rv_mask(rvs_dict, bad_rvs_dict):
    
    # Copy the dictionary
    rvs_dict_out = copy.deepcopy(rvs_dict)
    
    # Some numbers
    n_orders, n_spec, n_iters = rvs_dict['rvs'].shape
    n_obs_nights = rvs_dict['n_obs_nights']
    n_nights = len(n_obs_nights)
    
    # Initialize a mask
    mask = np.ones(shape=(n_orders, n_spec), dtype=float)
    
    # Mask all spectra for a given night
    if 'bad_nights' in bad_rvs_dict:
        for i in bad_rvs_dict['bad_nights']:
            inds = pcfoward_models.ForwardModel.get_all_spec_indices_from_night(i, n_obs_nights)
            mask[:, inds] = 0
            rvs_dict_out['rvs'][:, inds, :] = np.nan
            if rvs_dict_out['do_xcorr']:
                rvs_dict_out['rvsx'][:, inds, :] = np.nan
    
    # Mask individual spectra
    if 'bad_spec' in bad_rvs_dict:
        for i in bad_rvs_dict['bad_spec']:
            mask[:, i] = 0
            rvs_dict_out['rvs'][:, i, :] = np.nan
            
            if rvs_dict_out['do_xcorr']:
                rvs_dict_out['rvsx'][:, i, :] = np.nan
            
    return rvs_dict_out, mask
            
def gen_rv_weights(rvs_dict, bad_rvs_dict, rms=None, rvcs=None):
    
    # Numbers
    n_orders, n_spec, n_iters = rvs_dict['rvs'].shape
    n_obs_nights =  rvs_dict['n_obs_nights']
    n_nights = len(n_obs_nights)
    
    # Generate mask
    rvs_dict, mask = gen_rv_mask(rvs_dict, bad_rvs_dict)
    
    # RMS weights
    if rms is not None:
        weights_rms = 1 / rms**2
        weights_rms *= mask
    else:
        weights_rms = np.ones_like(mask)
    weights_rms /= np.nansum(weights_rms)
        
    # RV content weights
    if rvcs is not None:
        weights_rvcont = np.outer(1 / rvcs**2, np.ones(n_spec))
    else:
        weights_rvcont = np.copy(mask)
    weights_rvcont /= np.nansum(weights_rvcont)
    
    # Combine weights
    # NOTE: Normalization above is not perfect but meant to be ensure approximately similar scaling between weights if using additive (quadrature ) weights.
    # For multiplicative weights, this doesn't matter.
    weights = weights_rvcont * weights_rms
    
    # Normalize
    weights /= np.nansum(weights)

    return rvs_dict, weights



def parameter_corrs(output_path_root, bad_rvs_dict=None, do_orders=None, iter_index=None, templates=False, debug=False, xcorr=False):
    
    # Get the orders
    if do_orders is None:
        do_orders = parser.get_orders(output_path_root)
    n_orders = len(do_orders)
    
    # Get the tag for this run
    fwm_temp = parser.parse_forward_model(output_path_root, do_orders[0], 1)
    tag = fwm_temp.tag + '_' + datetime.date.today().strftime("%d%m%Y")
    index_offset = int(not fwm_temp.models_dict['star'].from_synthetic)
    star_name = fwm_temp.star_name
    spectrograph = fwm_temp.spectrograph
    
    # Parse the RVs
    rvs_dict = parser.parse_rvs(output_path_root, do_orders=do_orders)
    
    # Number of spectra and nights
    n_spec = np.sum(rvs_dict['n_obs_nights'])
    n_nights = len(rvs_dict['n_obs_nights'])
    n_iters = rvs_dict['rvs'].shape[2]
    
    # Determine which iteration to use
    if iter_index is None:
        iter_indexes = np.zeros(n_orders).astype(int) + n_iters - 1
    elif iter_index == 'best':
        _, iter_indexes = get_best_iterations(rvs_dict, xcorr)
    else:
        iter_indexes = np.zeros(n_orders).astype(int) + iter_index
        
    pars = parser.parse_parameters(output_path_root, do_orders=do_orders)
    pars_unpacked, varies_unpacked = parser.parameter_unpack(pars, iter_indexes + index_offset)
    par_names = list(pars[0, 0, 0].keys())
    for o in range(n_orders):
        rvs_unpacked = rvs_dict['rvs'][o, :, iter_indexes[o]]
        
        n_cols = 5
        varies_locs = np.where(varies_unpacked[o, 0, :])[0]
        nv = varies_locs.size
        n_rows = int(np.ceil(nv / n_cols))
        fig, axarr = plt.subplots(nrows=n_rows, ncols=n_cols, figsize=(16, 12), dpi=300)
        for row in range(n_rows):
            for col in range(n_cols):
                
                # The par index
                ip = n_cols * row + col
                
                if ip + 1 > nv:
                    axarr[row, col].set_visible(False)
                    continue
                
                axarr[row, col].plot(rvs_unpacked - np.nanmedian(rvs_unpacked), pars_unpacked[o, :, varies_locs[ip]], marker='.', lw=0)
                axarr[row, col].set_xlabel('RV [m/s]', fontsize=4)
                axarr[row, col].set_ylabel(par_names[varies_locs[ip]].replace('_', ' '), fontsize=4)
                axarr[row, col].tick_params(axis='both', which='major', labelsize=4)
        fig.suptitle(star_name.replace('_', ' ') + ' Parameter Correlations Order ' + str(do_orders[o]), fontsize=10)
        fname = output_path_root + 'Order' + str(do_orders[o]) + os.sep + tag + '_ord' + str(do_orders[o]) + '_parameter_corrs.png'
        plt.subplots_adjust(left=0.05, bottom=0.05, right=0.95, top=0.95, wspace=0.3, hspace=0.5)
        plt.savefig(fname)
        plt.close()
        
    if debug:
        stop()
        
    
def plot_final_rvs(star_name, spectrograph, bjds, bjds_nightly, rvs_single, unc_single, rvs_nightly, unc_nightly, phase_to=None, tc=None, show=True, fname=None):
    
    if phase_to is None:
        _phase_to = 1E20
    else:
        _phase_to = phase_to
        
    if tc is None:
        alpha = 0
    else:
        alpha = tc - phase_to / 2
    
    # Single rvs
    plt.errorbar((bjds - alpha)%phase_to, rvs_single-np.nanmedian(rvs_single), yerr=unc_single, linewidth=0, elinewidth=1, marker='.', markersize=10, markerfacecolor='pink', color='green', alpha=0.8)

    # Nightly RVs
    plt.errorbar((bjds_nightly - alpha)%phase_to, rvs_nightly-np.nanmedian(rvs_nightly), yerr=unc_nightly, linewidth=0, elinewidth=3, marker='o', markersize=10, markerfacecolor='blue', color='grey', alpha=0.9)
    
    plt.title(star_name.replace('_', ' ') + ', ' + spectrograph + ' Relative RVs')
    if phase_to is None:
        plt.xlabel('BJD - BJD$_{0}$')
    else:
        plt.xlabel('Phase [days, P = ' +  str(round(_phase_to, 3)) + ']')
    plt.ylabel('RV [m/s]')
    
    if show:
        plt.show()
    else:
        if fname is not None:
            plt.savefig(fname)
            
def plot_stellar_templates_single_iter(output_path_root, star_name, stellar_templates, do_orders, iter_indexes, unit='Ang'):
    
    if unit == 'microns':
        factor = 1E-4
    elif unit == 'Ang':
        factor = 1
    else:
        factor = 1E-1
    
    n_orders = len(do_orders)
    
    fig, axarr = plt.subplots(nrows=n_orders, ncols=1, figsize=(20, 16), dpi=250)
    
    for o in range(n_orders):
        axarr[o].plot(stellar_templates[o][:, 0] * factor, stellar_templates[o][:, 1])
        axarr[o].set_title('Order ' + str(do_orders[o]) + ' iter ' + str(iter_indexes[o] + 1), fontsize=8)
        axarr[o].tick_params(axis='both', labelsize=10)
    axarr[-1].set_xlabel('Wavelength [' + unit + ']')
    plt.subplots_adjust(left=0.08, bottom=0.08, right=0.97, top=0.95, wspace=None, hspace=0.5)
    fig.text(0.03, 0.5, 'Norm. flux', rotation=90, verticalalignment='center', horizontalalignment='center', fontsize=20)
    fig.text(0.5, 0.97, star_name, fontsize=20, verticalalignment='center', horizontalalignment='center')
    plt.savefig(output_path_root + 'stellar_templates.png')
    
    plt.close()
            
            
            
def rvs_quicklook(output_path_root, do_orders, bad_rvs_dict, iter_index, xcorr=False, flag=False, phase_to=None, debug=False, tc=None):
    
    if phase_to is None:
        _phase_to = 1E20
    else:
        _phase_to = phase_to
        
    if tc is None:
        alpha = 0
    else:
        alpha = tc - phase_to / 2
    
    # Parse RVs
    rvs_dict = parser.parse_rvs(output_path_root, do_orders)
    
    # Numbers
    n_orders, n_spec, n_iters = rvs_dict['rvs'].shape
    n_obs_nights = rvs_dict['n_obs_nights']
    bjds, bjdsn = rvs_dict['BJDS'], rvs_dict['BJDS_nightly']
    n_nights = len(n_obs_nights)
    
    iter_indexes = np.zeros(n_spec)
    print_rv_summary(rvs_dict, {}, do_orders, iter_indexes, xcorr=xcorr)
    
    # Generate mask
    rvs_dict, mask = gen_rv_mask(rvs_dict, bad_rvs_dict)
    
    # Get RVs
    rvs = np.zeros((n_orders, n_spec))
    for o in range(n_orders):
        if xcorr:
            rr = rvs_dict['rvsx'][o, :, iter_index]
        else:
            rr = rvs_dict['rvs'][o, :, iter_index]
        rvs[o, :] = rr - np.nanmedian(rr)
        
    # Combine
    rvs_nightly, unc_nightly = pcrvcalc.compute_nightly_rvs_from_all(rvs, mask, n_obs_nights, flag_outliers=flag, thresh=5)
    
    # Plot
    for o in range(n_orders):
        if phase_to is not None:
            plt.plot((bjds - alpha)%_phase_to, rvs[o, :] - np.nanmedian(rvs_nightly), marker='o', markersize=6, lw=0, label='Order ' + str(do_orders[o]))
        
    plt.errorbar((bjdsn - alpha)%_phase_to, rvs_nightly-np.nanmedian(rvs_nightly), yerr=unc_nightly, marker='o', lw=0, elinewidth=1, label='Binned Nightly', c='black', markersize=10)
    plt.legend()
    plt.show()
    
    if debug:
        stop()