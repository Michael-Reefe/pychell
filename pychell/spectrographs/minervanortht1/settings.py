import os
import numpy as np
import pychell.rvs

# Path to default templates for rvs
default_templates_path = pychell.rvs.__file__[0:-11] + 'default_templates' + os.sep

#############################
####### Name and Site #######
#############################

spectrograph = 'MinervaNorthT1'
observatory = 'Whipple'

####################################################################
####### Reduction / Extraction #####################################
####################################################################

redux_settings = NotImplemented


####################################################################
####### RADIAL VELOCITIES ##########################################
####################################################################

# Default forward model settings
forward_model_settings = {
    
    # The cropped pixels
    'crop_data_pix': [20, 20],
    
    # The units for plotting
    'plot_wave_unit': 'nm',
    
    'observatory': observatory
}

# Forward model blueprints for RVs
# No default blueprints are defined.
forward_model_blueprints = {
    
    # The star
    'star': {
        'name': 'star',
        'class_name': 'StarModel',
        'input_file': None,
        'vel': [-1000 * 300, 10, 1000 * 300]
    },
    
    # The methane gas cell
    'gas_cell': {
        'name': 'iodine_gas_cell',
        'class_name': 'GasCellModel',
        'input_file': default_templates_path + 'MINERVA_North_Iodine_nist.npz',
        'shift': [0, 0, 0],
        'depth': [1, 1, 1]
    },
    
    # Tellurics (from TAPAS)
    'tellurics': {
        'name': 'vis_tellurics',
        'class_name': 'TelluricModelTAPAS',
        'vel': [-500, -100, 500],
        'species': {
            'water': {
                'input_file': default_templates_path + 'telluric_water_tapas_whipple_vis.npz',
                'depth':[0.01, 1.5, 4.0]
            },
            'ozone': {
                'input_file': default_templates_path + 'telluric_ozone_tapas_whipple_vis.npz',
                'depth': [0.1, 1.0, 3.0]
            },
            'oxygen': {
                'input_file': default_templates_path + 'telluric_oxygen_tapas_whipple_vis.npz',
                'depth': [0.05, 0.65, 3.0]
            }
        }
    },
    
    # The default blaze is a quadratic + splines.
    #'blaze': {
    #    'name': 'full_blaze', # The blaze model after a division from a flat field
    #    'class_name': 'FullBlazeModel',
    #    'n_splines': 0,
    #    'n_delay_splines': 0,
    #    'base_amp': [1.0, 1.05, 1.4],
    #    'base_b': [0.008, 0.01, 0.04],
    #    'base_c': [-1, 0.01, 1],
    #    'base_d': [0.51, 0.7, 0.9],
    #    'spline': [-0.135, 0.01, 0.135],
        
        # Blaze is centered on the blaze wavelength.
    #    'blaze_wavelengths': [5012.060852456845, 5053.459990944932, 5095.561244542134, 5138.360690563254, 5181.892299270933, 5226.163597295029, 5271.199840554507, 5317.024989942361, 5363.642535762575, 5411.091222301685, 5459.386482538174, 5508.5422589421, 5558.605103377195, 5609.5859110586725, 5661.502332634189, 5714.387997283954, 5768.283070147888, 5823.189678639199, 5879.16025835496, 5936.222417382394, 5994.390187105367, 6053.721598301344, 6114.230529992971, 6175.958134786341, 6238.959278109819, 6303.237911559996, 6368.873022593966, 6435.888127832344, 0.0]
    #},
    
    # The default blaze is a quadratic + splines.
    'blaze': {
        'name': 'residual_blaze', # The blaze model after a division from a flat field
        'class_name': 'SplineBlazeModel',
        'n_splines': 6,
        'spline': [-0.135, 0.01, 0.135],
        #'spline': [-0.3, 1.0, 1.1],
        'n_delay': 0
    },
    
    
    # Hermite Gaussian LSF
    'lsf': {
        'name': 'lsf_hermite',
        'class_name': 'LSFHermiteModel',
        'hermdeg': 2,
        'n_delay': 0,
        'compress': 32,
        'width': [0.010, 0.014, 0.018], # LSF width, in angstroms
        'ak': [-0.03, 0.001, 0.2] # Hermite polynomial coefficients
    },
    
    # Quadratic (Lagrange points) + splines
    'wavelength_solution': {
        
        'name': 'lagrange_wavesol_splines',
        'class_name': 'WaveSolModelSplines',
        
        # The three pixels to span the detector
        'base_pixel_set_points': [199, 1023, 1847],
        
        # Left most set point for the quadratic wavelength solution
        #'base_set_point_1': [4995.44009795547, 5036.694068872001, 5078.662447993969, 5121.308208044935, 5164.70118529824, 5208.816415728758, 5253.706813476153, 5299.365662762142, 5345.830108543917, 5393.126907141758, 5441.24861800657, 5490.2549388724665, 5540.144531455879, 5590.973953394308, 5642.699268564512, 5695.40658479837, 5749.115542262161, 5803.832088944785, 5859.62114719924, 5916.4860242840205, 5974.465251023381, 6033.601145806596, 6093.907212336449, 6155.434210469942, 6218.214991555288, 6282.28904547583, 6347.719749321356, 6414.502327196737, 0.0],

        # Middle set point for the quadratic wavelength solution
        #'base_set_point_2': [5012.060852456845, 5053.459990944932, 5095.561244542134, 5138.360690563254, 5181.892299270933, 5226.163597295029, 5271.199840554507, 5317.024989942361, 5363.642535762575, 5411.091222301685, 5459.386482538174, 5508.5422589421, 5558.605103377195, 5609.5859110586725, 5661.502332634189, 5714.387997283954, 5768.283070147888, 5823.189678639199, 5879.16025835496, 5936.222417382394, 5994.390187105367, 6053.721598301344, 6114.230529992971, 6175.958134786341, 6238.959278109819, 6303.237911559996, 6368.873022593966, 6435.888127832344, 0.0],

        # Right most set point for the quadratic wavelength solution
        #'base_set_point_3': [5027.307137763543, 5068.828907329501, 5111.0547656534245, 5153.989186982839, 5197.6597970028315, 5242.072554919374, 5287.230094370015, 5333.194163663312, 5380.036363617119, 5427.556885596881, 5476.003996021366, 5525.310614823622, 5575.545803670773, 5626.665041134895, 5678.743792460886, 5731.7950401260305, 5785.846834024057, 5840.927559800103, 5897.061418761491, 5954.299363778574, 6012.668040846991, 6072.1675202625065, 6132.8638831046455, 6194.789311874347, 6257.963948363508, 6322.454439742417, 6388.30533836116, 6455.45584701302, 0.0],
        
        'base_set_point_1': [0.0, 5034.853697572874, 5076.812630787258, 5119.47332870002, 5162.863938423941, 5206.991404425711, 5251.871712707604, 5297.537806125327, 5344.011497745494, 5391.301574584434, 5439.441398147255, 5488.441679478328, 5538.341607959066, 5589.311652278706, 5640.893680573438, 5693.618386820708, 5747.332360938869, 5802.065798040452, 5857.861297042003, 5914.742834118711, 5972.7310335422535, 6031.866877601428, 6092.185400272845, 6153.720542873271, 6216.5249581525495, 6280.615403285079, 6346.037489025672, 6412.829961078201, 0.0],
        
        'base_set_point_2': [0.0, 5051.797742891635, 5093.898685761055, 5136.697595510594, 5180.233076475155, 5224.508536304159, 5269.5427694487735, 5315.364638948184, 5361.992864941634, 5409.443535145528, 5457.742919358793, 5506.909169238973, 5556.970264512113, 5607.957112181663, 5659.876566684212, 5712.771902843216, 5766.668664042743, 5821.5861705217485, 5877.567064061789, 5934.640248932237, 5992.8133511595415, 6052.148584042049, 6112.6745762439705, 6174.403373183191, 6237.422193252906, 6301.723684229485, 6367.375320671031, 6434.398000613977, 0.0],
            
        'base_set_point_3': [0.0, 5067.306317313274, 5109.539742822402, 5152.471828725401, 5196.134102810834, 5240.549275045628, 5285.72582733859, 5331.690324839082, 5378.463693283485, 5426.0533289506975, 5474.498064685866, 5523.8184482579245, 5574.047438040501, 5625.161567818693, 5677.26090476372, 5730.309920366878, 5784.379331768739, 5839.466273222518, 5895.613344838828, 5952.846938796597, 6011.2163127724625, 6070.727482754385, 6131.432211521225, 6193.363501926163, 6256.559669953157, 6321.063717173306, 6386.910837903344, 6454.131868090541, 0.0],
        
        'n_splines': 0,
        'n_delay_splines': 0,
        'spline': [-0.005, 0.0001, 0.005]
    }
}