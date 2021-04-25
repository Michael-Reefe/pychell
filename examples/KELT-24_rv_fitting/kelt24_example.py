# Base Python libraries
import os

# Import numpy
import numpy as np

# Import pychell orbits module
import pychell.orbits as pco

# Path to input rv file and outputs
path = os.path.dirname(os.path.abspath(__file__)) + os.sep
fname = 'kelt24_rvs.txt'

# The name of the star for plots
star_name = 'KELT-24'

# Mass and uncertainty of star for mass determination
mstar = 1.460
mstar_unc = [0.059, 0.055]

# Starting jitter values for each instrument.
jitter_dict = {'SONG': 50, 'TRES': 0}

# All data in one dictionary
data = pco.CompositeRVData.from_radvel_file(fname)

# Init parameters and planets dictionary
pars = pco.Parameters()
planets_dict = {}

# Define parameters for planet 1
# Other bases are available.
planets_dict[1] = {"label": "b", "basis": pco.TCOrbitBasis(1)}

# Values from Rodriguez et al. 2019 for KELT-24 b
per1 = 5.5514926
per1_unc = 0.0000081
tc1 =  2457147.0529
tc1_unc = 0.002
ecc1 = 0.077
ecc1_unc = 0.024
w1 = 55 * np.pi / 180
w1_unc = 15 * np.pi / 180

# Period
pars["per1"] = pco.Parameter(value=per1, vary=True)
pars["per1"].add_prior(pco.Gaussian(per1, per1_unc))

# Time of conjunction
pars["tc1"] = pco.Parameter(value=tc1, vary=True)
pars["tc1"].add_prior(pco.Gaussian(tc1, tc1_unc))

# Eccentricity
pars["ecc1"] = pco.Parameter(value=ecc1, vary=True)
pars["ecc1"].add_prior(pco.Uniform(1E-10, 1))
pars["ecc1"].add_prior(pco.Gaussian(ecc1, ecc1_unc))

# Angle of periastron
pars["w1"] = pco.Parameter(value=w1, vary=True)
pars["w1"].add_prior(pco.Gaussian(w1, w1_unc))

# RV semi-amplitude
pars["k1"] = pco.Parameter(value=462, vary=True)
pars["k1"].add_prior(pco.Positive())

# Per instrument gamma offsets
# Additional small offset is to avoid cases where the median is already subtracted off.
for instname in data:
    pname = "gamma_" + instname
    pars[pname] = pco.Parameter(value=np.nanmedian(data[instname].rv) + np.pi / 100, vary=True)
    pars[pname].add_prior(pco.Uniform(pars[pname].value - 200, pars[pname].value + 200))
    
# Linear and quadratic trends
pars["gamma_dot"] = pco.Parameter(value=0, vary=False)
pars["gamma_ddot"] = pco.Parameter(value=0, vary=False)

# Per-instrument jitter
for instname in data:
    pname = "jitter_" + instname
    pars[pname] = pco.Parameter(value=jitter_dict[instname], vary=jitter_dict[instname] > 0)
    if pars[pname].vary:
        pars[pname].add_prior(pco.Uniform(1E-10, 100))

# Initiate a composite likelihood object
likes = pco.RVPosterior()

# Define a single kernel and model, add to likelihoods
kernel = pco.WhiteNoise(data=data)
model = pco.RVModel(planets_dict=planets_dict, data=data, p0=pars)
likes["rvs"] = pco.RVLikelihood(data=data, model=model, kernel=kernel)

# Define max like optimizer (iterative Nelder-Mead) and emcee MCMC sampler
optimizer = pco.NelderMead(scorer=likes)
sampler = pco.AffInv(scorer=likes, options=None)

# Define top-level exoplanet "problem" (Really an RV problem for now)
optprob = pco.RVProblem(output_path=path, star_name=star_name, p0=pars, optimizer=optimizer, sampler=sampler, data=data, scorer=likes, mstar=mstar, mstar_unc=mstar_unc, tag="EXAMPLE")

# Perform max like fit
# Results are saved to a pickle file.
maxlike_result = optprob.maxlikefit()

# Plots
# All plots are automatically saved with a unique timestamp in the filename.
optprob.plot_phased_rvs_all(maxlike_result["pbest"])
optprob.plot_full_rvs(maxlike_result["pbest"])

# Set parameters from max like fit
optprob.set_pars(maxlike_result["pbest"])

# Perform model comparison
# Results are saved to a pickle file
mc_result = optprob.model_comparison()

# Perform mcmc. Here we expose several kwargs, which is not always necessary.
# Results are saved to a pickle file
mcmc_result = optprob.mcmc(n_burn_steps=500, check_every=200, n_steps=75_000, rel_tau_thresh=0.01, n_min_steps=1000, n_cores=8, n_taus_thresh=50)

# Corner plot
optprob.corner_plot(mcmc_result)