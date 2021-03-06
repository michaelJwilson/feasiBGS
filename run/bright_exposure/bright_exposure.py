'''
'''
import os 
import h5py 
import pickle 
import numpy as np 
import scipy as sp 
from scipy.interpolate import interp1d
# -- astropy -- 
from astropy import units as u
# --- sklearn ---
from sklearn.gaussian_process import GaussianProcessRegressor as GPR 
from sklearn.gaussian_process.kernels import RBF, ConstantKernel
# -- desi --
import desisim.simexp 
import specsim.config 
from desispec.io import read_spectra
# -- feasibgs -- 
from feasibgs import util as UT
from feasibgs import catalogs as Cat
from feasibgs import skymodel as Sky
# -- plotting -- 
import matplotlib as mpl
import matplotlib.pyplot as plt
mpl.rcParams['text.usetex'] = True
mpl.rcParams['font.family'] = 'serif'
mpl.rcParams['axes.linewidth'] = 1.5
mpl.rcParams['axes.xmargin'] = 1
mpl.rcParams['xtick.labelsize'] = 'x-large'
mpl.rcParams['xtick.major.size'] = 5
mpl.rcParams['xtick.major.width'] = 1.5
mpl.rcParams['ytick.labelsize'] = 'x-large'
mpl.rcParams['ytick.major.size'] = 5
mpl.rcParams['ytick.major.width'] = 1.5
mpl.rcParams['legend.frameon'] = False

specsim_sky = Sky.specsim_initialize('desi')


def sky_convexhull_exposure_samples(): 
    fsamp = os.path.join(UT.dat_dir(), 'bright_exposure', 
            'params.exp_samples.exposures_surveysim_fork_150s.npy') 
    # airmasses moon_ill moon_alt moon_sep sun_alt sun_sep 
    params = np.load(fsamp) 
    airmass, moonill, moonalt, moonsep, sun_alt, sun_sep = params.T # unpack the parameters

    # generate sky brightness
    for i in range(len(airmass)): 
        print(i)
        wave, _Isky = sky_KSrescaled_twi(airmass[i], moonill[i], moonalt[i], moonsep[i], sun_alt[i], sun_sep[i])
        if i == 0: 
            Isky = np.zeros((params.shape[0], len(_Isky)))
        Isky[i,:] = _Isky 

    # dump sky brightnesses
    fsky = os.path.join(UT.dat_dir(), 'bright_exposure', 
            'sky.params.exp_samples.exposures_surveysim_fork_150s.p') 
    pickle.dump([wave, Isky], open(fsky, 'wb'))
    return None 


def texp_factor(validate=False, silent=True, wrange=4500): 
    ''' Calculate the exposure time correction factor using the `surveysim` 
    exposure list from Jeremy: `bgs_survey_exposures.withsun.hdf5', which 
    supplemented the observing conditions with sun observing conditions. 
    Outputs a file that contains the observing conditions (parameters) and 
    the ratio between (new sky flux)/(nominal dark time sky flux) 

    :param validate: (default: False)
        If True, generate some figures to validate things 

    :param silent: (default: True) 
        if False, code will print statements to indicate progress 
    '''
    # read surveysim BGS exposures parameters 
    fsamp = os.path.join(UT.dat_dir(), 'bright_exposure', 
            'params.exp_samples.exposures_surveysim_fork_150s.npy') 
    # airmasses moon_ill moon_alt moon_sep sun_alt sun_sep 
    thetas = np.load(fsamp) 
    airmass, moonill, moonalt, moonsep, sun_alt, sun_sep = thetas.T # unpack the parameters
    bgs_exps = {} 
    bgs_exps['AIRMASS'] = airmass 
    bgs_exps['MOONFRAC'] = moonill  
    bgs_exps['MOONALT'] = moonalt 
    bgs_exps['MOONSEP'] = moonsep 
    bgs_exps['SUNALT'] = sun_alt
    bgs_exps['SUNSEP'] = sun_sep
    n_exps = len(airmass) # number of exposures

    # read in pre-computed old and new sky brightness (this takes a bit) 
    if not silent: print('reading in sky brightness') 
    fnew = os.path.join(UT.dat_dir(), 'bright_exposure', 
            'sky.params.exp_samples.exposures_surveysim_fork_150s.p') 
    wave, sky_bright = pickle.load(open(fnew, 'rb'))
    
    # nominal dark sky brightness 
    config = desisim.simexp._specsim_config_for_wave(wave, dwave_out=None, specsim_config_file='desi')
    atm_config = config.atmosphere
    surface_brightness_dict = config.load_table(atm_config.sky, 'surface_brightness', as_dict=True)
    sky_dark= surface_brightness_dict['dark'] 
    
    # get the continuums 
    w_cont, sky_dark_cont = getContinuum(wave, sky_dark.value)

    sky_bright_cont = np.zeros((len(sky_bright), len(w_cont)))
    for isky in range(len(sky_bright)):  
        _, sky_bright_cont_i = getContinuum(wave, sky_bright[isky])
        sky_bright_cont[isky,:] = sky_bright_cont_i

    # calculate (new sky brightness)/(nominal dark sky brightness), which is the correction
    # factor for the exposure time. 
    if wrange == 4500: 
        wlim = ((wave > 4000.) & (wave < 5000.)) # ratio over 4000 - 5000 A  
        f_exp = np.zeros(n_exps)
        for i_exp in range(n_exps): 
            f_exp[i_exp] = np.median((sky_bright[i_exp] / sky_dark.value)[wlim])
    elif wrange == 7000: 
        wlim = ((w_cont > 6500.) & (w_cont < 7500.)) # ratio over 4000 - 5000 A  
        assert np.sum(wlim) == 1
        f_exp = np.zeros(n_exps)
        for i_exp in range(n_exps): 
            f_exp[i_exp] = (sky_bright_cont[i_exp] / sky_dark_cont)[wlim][0]
    print(np.median(f_exp)) 

    # write exposure subsets out to file 
    ff = os.path.join(UT.dat_dir(), 'bright_exposure', 'texp_factor_exposures.hdf5')
    fpick = h5py.File(ff, 'w')
    for k in ['AIRMASS', 'MOONFRAC', 'MOONALT', 'MOONSEP', 'SUNALT', 'SUNSEP']: # write observing conditions  
        fpick.create_dataset(k.lower(), data=bgs_exps[k]) 
    # save sky brightnesses
    fpick.create_dataset('f_exp', data=f_exp) 
    fpick.close() 

    if validate: 
        fig = plt.figure(figsize=(15,25))
        sub = fig.add_subplot(611)
        sub.scatter(bgs_exps['MOONALT'], f_exp, c='k', s=1)
        f_exp_i, bin_edges, _ = sp.stats.binned_statistic(bgs_exps['MOONALT'], f_exp, statistic='median', bins=20)
        sub.scatter(0.5*(bin_edges[:-1] + bin_edges[1:]), f_exp_i, c='C1') 
        sub.set_xlabel('Moon Altitude', fontsize=20)
        sub.set_xlim([-90., 90.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])

        sub = fig.add_subplot(612)
        sub.scatter(bgs_exps['MOONFRAC'], f_exp, c='k', s=1)
        f_exp_i, bin_edges, _ = sp.stats.binned_statistic(bgs_exps['MOONFRAC'], f_exp, statistic='median', bins=20)
        sub.scatter(0.5*(bin_edges[:-1] + bin_edges[1:]), f_exp_i, c='C1') 
        sub.set_xlabel('Moon Illumination', fontsize=20)
        sub.set_xlim([0.5, 1.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])

        sub = fig.add_subplot(613)
        sub.scatter(bgs_exps['MOONSEP'], f_exp, c='k', s=1)
        f_exp_i, bin_edges, _ = sp.stats.binned_statistic(bgs_exps['MOONSEP'], f_exp, statistic='median', bins=20)
        sub.scatter(0.5*(bin_edges[:-1] + bin_edges[1:]), f_exp_i, c='C1') 
        sub.set_xlabel('Moon Separation', fontsize=20)
        sub.set_xlim([40., 180.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])
        
        sub = fig.add_subplot(614)
        sub.scatter(bgs_exps['SUNALT'], f_exp, c='k', s=1)
        f_exp_i, bin_edges, _ = sp.stats.binned_statistic(bgs_exps['SUNALT'], f_exp, statistic='median', bins=20) 
        sub.scatter(0.5*(bin_edges[:-1] + bin_edges[1:]), f_exp_i, c='C1') 
        sub.set_xlabel('Sun Altitude', fontsize=20)
        sub.set_xlim([-90., 0.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])
        
        sub = fig.add_subplot(615)
        sub.scatter(bgs_exps['SUNSEP'], f_exp, c='k', s=1)
        f_exp_i, bin_edges, _ = sp.stats.binned_statistic(bgs_exps['SUNSEP'], f_exp, statistic='median', bins=20) 
        sub.scatter(0.5*(bin_edges[:-1] + bin_edges[1:]), f_exp_i, c='C1') 
        sub.set_xlabel('Sun Separation', fontsize=20)
        sub.set_xlim([40., 180.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])

        sub = fig.add_subplot(616)
        sub.scatter(bgs_exps['AIRMASS'], f_exp, c='k', s=1)
        f_exp_i, bin_edges, _ = sp.stats.binned_statistic(bgs_exps['AIRMASS'], f_exp, statistic='median', bins=20)
        sub.scatter(0.5*(bin_edges[:-1] + bin_edges[1:]), f_exp_i, c='C1') 
        sub.set_xlabel('Airmass', fontsize=20)
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_xlim([1., 2.])
        sub.set_ylim([0.5, 15.])
        fig.subplots_adjust(hspace=0.4)
        fig.savefig(ff.replace('.hdf5', '%iA.png' % wrange), bbox_inches='tight')

        # plot some of the sky brightnesses
        fig = plt.figure(figsize=(15,20))
        bkgd = fig.add_subplot(111, frameon=False) 
        for ii, isky in enumerate(np.random.choice(range(n_exps), 4, replace=False)):
            sub = fig.add_subplot(4,1,ii+1)
            sub.plot(wave, sky_bright[isky,:], c='C1', label='bright sky')
            sub.plot(w_cont, sky_bright_cont[isky,:], c='k', ls='--')
            sub.plot(wave, sky_dark, c='k', label='nomnial dark sky')
            sub.plot(w_cont, sky_dark_cont, c='C0')
            sub.set_xlim([3500., 9500.]) 
            sub.set_ylim([0., 20]) 
            if ii == 0: sub.legend(loc='upper left', fontsize=20) 
        bkgd.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
        bkgd.set_xlabel('wavelength [Angstrom]', fontsize=25) 
        bkgd.set_ylabel('sky brightness [$erg/s/cm^2/A/\mathrm{arcsec}^2$]', fontsize=25) 
        fig.savefig(ff.replace('.hdf5', '.sky.png'), bbox_inches='tight')
    return None 


def texp_factor_GP(validate=False): 
    ''' fit GP for exposure time correction factor as a function of 6 parameters
    'AIRMASS', 'MOONFRAC', 'MOONALT', 'MOONSEP', 'SUNALT', 'SUNSEP'
    '''
    ff = os.path.join(UT.dat_dir(), 'bright_exposure', 'texp_factor_exposures.hdf5')
    ffexp = h5py.File(ff, 'r')
    
    f_exp  = ffexp['f_exp'].value 
    bgs_exps = {} 
    thetas = np.zeros((len(f_exp), 6))
    for i_k, k in enumerate(['AIRMASS', 'MOONFRAC', 'MOONALT', 'MOONSEP', 'SUNALT', 'SUNSEP']): 
        bgs_exps[k] = ffexp[k.lower()].value 
        thetas[:,i_k] = ffexp[k.lower()].value 

    _thetas = np.zeros((5000, 6))
    for i in range(6): 
        _thetas[:,i] = np.random.uniform(thetas[:,i].min(), thetas[:,i].max(), 5000)
    print('convex hull') 
    param_hull = sp.spatial.Delaunay(thetas[::10,:])
    inhull = (param_hull.find_simplex(_thetas) >= 0) 
    thetas_test = _thetas[inhull]
    print('test set size', thetas_test.shape)
    mu_theta_test = np.zeros(np.sum(inhull))
    
    for typ in ['nottwi', 'twi']:
        if typ == 'nottwi': 
            cut = (thetas[:,4] <= -20.) 
            test_cut = (thetas_test[:,4] <= -20.) 
        elif typ == 'twi': 
            cut = (thetas[:,4] > -20.) 
            test_cut = (thetas_test[:,4] > -20.) 
        kern = ConstantKernel(1.0, (1e-4, 1e4)) * RBF(1, (1e-4, 1e4)) # kernel
        print('training %s GP' % typ) 
        gp = GPR(kernel=kern, n_restarts_optimizer=10) # instanciate a GP model
        gp.fit(thetas[cut,:], f_exp[cut])
        #gp.fit(thetas[cut,:][::5], f_exp[cut][::5])
        # save GP parameters to file 
        #params = gp.get_params(deep=True).copy() 
        #kern_thetas = gp.kernel_.theta
        #kern_params = gp.kernel_.get_params(deep=True).copy() 
        pickle.dump(gp, open(ff.replace('.hdf5', '.%s.GPparams.p' % typ), 'wb')) 

        print('%s GP predicting' % typ)  
        mu_theta_test[test_cut] = gp.predict(thetas_test[test_cut,:]) 

    print(np.median(mu_theta_test)) 
    if validate: 
        fig = plt.figure(figsize=(15,25))
        sub = fig.add_subplot(611)
        sub.scatter(bgs_exps['MOONALT'], f_exp, c='k', s=1)
        sub.scatter(thetas_test[:,2], mu_theta_test, c='C1', s=5)
        sub.set_xlabel('Moon Altitude', fontsize=20)
        sub.set_xlim([-90., 90.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])

        sub = fig.add_subplot(612)
        sub.scatter(bgs_exps['MOONFRAC'], f_exp, c='k', s=1)
        sub.scatter(thetas_test[:,1], mu_theta_test, c='C1', s=5)
        sub.set_xlabel('Moon Illumination', fontsize=20)
        sub.set_xlim([0.5, 1.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])

        sub = fig.add_subplot(613)
        sub.scatter(bgs_exps['MOONSEP'], f_exp, c='k', s=1)
        sub.scatter(thetas_test[:,3], mu_theta_test, c='C1', s=5)
        sub.set_xlabel('Moon Separation', fontsize=20)
        sub.set_xlim([40., 180.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])
        
        sub = fig.add_subplot(614)
        sub.scatter(bgs_exps['SUNALT'], f_exp, c='k', s=1)
        sub.scatter(thetas_test[:,4], mu_theta_test, c='C1', s=5)
        sub.set_xlabel('Sun Altitude', fontsize=20)
        sub.set_xlim([-90., 0.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])
        
        sub = fig.add_subplot(615)
        sub.scatter(bgs_exps['SUNSEP'], f_exp, c='k', s=1)
        sub.scatter(thetas_test[:,5], mu_theta_test, c='C1', s=5)
        sub.set_xlabel('Sun Separation', fontsize=20)
        sub.set_xlim([40., 180.])
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_ylim([0.5, 15.])

        sub = fig.add_subplot(616)
        sub.scatter(bgs_exps['AIRMASS'], f_exp, c='k', s=1)
        sub.scatter(thetas_test[:,0], mu_theta_test, c='C1', s=5)
        sub.set_xlabel('Airmass', fontsize=20)
        sub.set_ylabel('exposure time factor', fontsize=20)
        sub.set_xlim([1., 2.])
        sub.set_ylim([0.5, 15.])
        fig.savefig(ff.replace('.hdf5', '.GP.png'), bbox_inches='tight')
    return None 


def test_texp_factor_GP(): 
    ff = os.path.join(UT.dat_dir(), 'bright_exposure', 'texp_factor_exposures.hdf5')
    ffexp = h5py.File(ff, 'r')
    
    f_exp  = ffexp['f_exp'].value 
    bgs_exps = {} 
    thetas = np.zeros((len(f_exp), 6))
    for i_k, k in enumerate(['AIRMASS', 'MOONFRAC', 'MOONALT', 'MOONSEP', 'SUNALT', 'SUNSEP']): 
        bgs_exps[k] = ffexp[k.lower()].value 
        thetas[:,i_k] = ffexp[k.lower()].value 

    _thetas = np.zeros((5000, 6))
    for i in range(6): 
        _thetas[:,i] = np.random.uniform(thetas[:,i].min(), thetas[:,i].max(), 5000)
    param_hull = sp.spatial.Delaunay(thetas[::10,:])
    inhull = (param_hull.find_simplex(_thetas) >= 0) 
    thetas_test = _thetas[inhull]

    for typ in ['nottwi', 'twi']:
        if typ == 'nottwi': 
            test_cut = (thetas_test[:,4] <= -20.) 
        elif typ == 'twi': 
            test_cut = (thetas_test[:,4] > -20.) 
        # saved GP parameters 
        gp = pickle.load(open(ff.replace('.hdf5', '.%s.GPparams.p' % typ), 'rb')) 

        #kern = ConstantKernel(1.0, (1e-4, 1e4)) * RBF(1, (1e-4, 1e4)) # kernel
        #kern.set_params(**kern_params)
        #kern.theta = kern_thetas
        #print kern_params
        #print kern.get_params() 
        #print kern.theta
        #gp = GPR(kernel=kern) # instanciate a GP model
        #gp.set_params(**params) 
        print(gp.predict(thetas_test[test_cut,:]))
        print(thetas_test[0,:])
        print(gp.predict(np.atleast_2d(thetas_test[0,:])))
    return None


def getContinuum(ww, sb): 
    ''' smooth out the sufrace brightness somehow...
    '''
    wavebin = np.linspace(3.6e3, 1e4, 10)
    sb_med = np.zeros(len(wavebin)-1)
    for i in range(len(wavebin)-1): 
        inwbin = ((wavebin[i] < ww) & (ww < wavebin[i+1]) & np.isfinite(sb))
        if np.sum(inwbin) > 0.: 
            sb_med[i] = np.median(sb[inwbin])
    return 0.5*(wavebin[1:]+wavebin[:-1]), sb_med


def sky_KSrescaled_twi(airmass, moonill, moonalt, moonsep, sun_alt, sun_sep):
    ''' calculate sky brightness using rescaled KS coefficients plus a twilight
    factor from Parker. 

    :return specsim_wave, Isky: 
        returns wavelength [Angstrom] and sky surface brightness [$10^{-17} erg/cm^{2}/s/\AA/arcsec^2$]
    '''
    #specsim_sky = Sky.specsim_initialize('desi')
    specsim_wave = specsim_sky._wavelength # Ang
    specsim_sky.airmass = airmass
    specsim_sky.moon.moon_phase = np.arccos(2.*moonill - 1)/np.pi
    specsim_sky.moon.moon_zenith = (90. - moonalt) * u.deg
    specsim_sky.moon.separation_angle = moonsep * u.deg
    
    # updated KS coefficients 
    specsim_sky.moon.KS_CR = 458173.535128
    specsim_sky.moon.KS_CM0 = 5.540103
    specsim_sky.moon.KS_CM1 = 178.141045
    
    I_ks_rescale = specsim_sky.surface_brightness
    Isky = I_ks_rescale.value
    if sun_alt > -20.: # adding in twilight
        w_twi, I_twi = cI_twi(sun_alt, sun_sep, airmass)
        I_twi /= np.pi
        I_twi_interp = interp1d(10. * w_twi, I_twi, fill_value='extrapolate')
        Isky += I_twi_interp(specsim_wave.value)
    return specsim_wave.value, Isky


def cI_twi(alpha, delta, airmass):
    ''' twilight contribution

    :param alpha: 

    :param delta: 

    :param airmass: 

    :return twi: 

    '''
    ftwi = os.path.join(UT.dat_dir(), 'sky', 'twilight_coeffs.p')
    twi_coeffs = pickle.load(open(ftwi, 'rb'))
    twi = (
        twi_coeffs['t0'] * np.abs(alpha) +      # CT2
        twi_coeffs['t1'] * np.abs(alpha)**2 +   # CT1
        twi_coeffs['t2'] * np.abs(delta)**2 +   # CT3
        twi_coeffs['t3'] * np.abs(delta)        # CT4
    ) * np.exp(-twi_coeffs['t4'] * airmass) + twi_coeffs['c0']
    return twi_coeffs['wave'], np.array(twi)


def _twilight_coeffs(): 
    ''' save twilight coefficients from Parker
    '''
    import pandas as pd
    f = os.path.join(UT.code_dir(), 'dat', 'sky', 'MoonResults.csv')

    coeffs = pd.DataFrame.from_csv(f)
    coeffs.columns = [
        'wl', 'model', 'data_var', 'unexplained_var',' X2', 'rX2',
        'c0', 'c_am', 'tau', 'tau2', 'c_zodi', 'c_isl', 'sol', 'I',
        't0', 't1', 't2', 't3', 't4', 'm0', 'm1', 'm2', 'm3', 'm4', 'm5', 'm6',
        'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
        'c2', 'c3', 'c4', 'c5', 'c6']
    # keep moon models
    twi_coeffs = coeffs[coeffs['model'] == 'twilight']
    coeffs = coeffs[coeffs['model'] == 'moon']
    # order based on wavelengths for convenience
    wave_sort = np.argsort(np.array(coeffs['wl']))

    twi = {} 
    twi['wave'] = np.array(coeffs['wl'])[wave_sort] 
    for k in ['t0', 't1', 't2', 't3', 't4', 'c0']:
        twi[k] = np.array(twi_coeffs[k])[wave_sort]
    
    # save to file 
    ftwi = os.path.join(UT.dat_dir(), 'sky', 'twilight_coeffs.p')
    pickle.dump(twi, open(ftwi, 'wb'))
    return None 


if __name__=="__main__": 
    #sky_convexhull_exposure_samples()
    #texp_factor(validate=True)
    texp_factor_GP(validate=True)
    #test_texp_factor_GP()
