#!/bin/python 
'''
redshift success rate calculations necessary for SV preparation 
'''
import os 
import h5py 
import pickle 
import numpy as np 
import scipy as sp 
import corner as DFM 
from itertools import product 
# --- desi --- 
import specsim.config 
from desisurvey import etc as ETC
# --- astropy --- 
import astropy.units as u
from astropy.io import fits
from astropy.table import Table as aTable
# --- sklearn ---
from sklearn.gaussian_process import GaussianProcessRegressor as GPR 
from sklearn.gaussian_process.kernels import RBF, ConstantKernel
from sklearn.linear_model import LinearRegression as LR 
# -- feasibgs -- 
from feasibgs import util as UT
from feasibgs import skymodel as Sky 
from feasibgs import catalogs as Cat
from feasibgs import forwardmodel as FM 
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


dir_dat = os.path.join(UT.dat_dir(), 'survey_validation')


def zsuccess_surveysim(specfile, expfile, min_deltachi2=40.):
    ''' plot the compiled redshift success rate for the redrock output 
    of BGS-like spectra for the nexp observing conditions

    :param spec_flag: 
        noiseless source spectra file. (default: 'GALeg.g15.sourceSpec.3000.hdf5') 
    '''
    # read in noiseless spectra (for true redshift and r-band magnitude) 
    fspec = h5py.File(specfile, 'r') 
    ztrue       = fspec['gama-spec']['z'][...]
    r_mag_gama  = fspec['r_mag_gama'][...]
    r_fibermag  = fspec['r_mag_apflux'][...]
    r_mag_legacy = UT.flux2mag(fspec['legacy-photo']['flux_r'].value, method='log')

    # read in sampled exposures
    fexps = h5py.File(expfile, 'r') 
    nexps = len(fexps['airmass'][...]) 
    
    ncol = 4
    nrow = int(np.ceil(float(nexps)/ncol)) 

    for rname, rmag in zip(['r_mag', 'r_mag_legacy', 'r_fibermag'], [r_mag_gama, r_mag_legacy, r_fibermag]): 
        fig = plt.figure(figsize=(4*ncol, 4*nrow))
        for iexp in range(nexps): 
            print('--- exposure %i ---' % iexp) 
            print('%s' % ', '.join(['%s = %.2f' % (k, fexps[k][iexp]) 
                for k in ['texp_total', 'airmass', 'moon_alt', 'moon_ill', 'moon_sep', 'sun_alt', 'sun_sep']]))
                
            # read in redrock outputs
            f_bgs = specfile.replace('sourceSpec', 'bgsSpec').replace('.hdf5', '.%s' % os.path.basename(expfile).replace('.hdf5', '.exp%i.rr.fits' % iexp))
            rr      = fits.open(f_bgs)[1].data
            zrr     = rr['Z']
            dchi2   = rr['DELTACHI2']
            zwarn   = rr['ZWARN']

            # redshift success 
            zsuccess_exp = UT.zsuccess(zrr, ztrue, zwarn, deltachi2=dchi2, min_deltachi2=min_deltachi2) 
            if rname == 'r_mag': 
                wmean, rate, err_rate = UT.zsuccess_rate(rmag, zsuccess_exp, range=[15,20], nbins=28, bin_min=10) 
            elif rname == 'r_mag_legacy': 
                wmean, rate, err_rate = UT.zsuccess_rate(rmag, zsuccess_exp, range=[15,21], nbins=28, bin_min=10) 
            elif rname == 'r_fibermag': 
                wmean, rate, err_rate = UT.zsuccess_rate(rmag, zsuccess_exp, range=[18,22], nbins=28, bin_min=10) 
            
            sub = fig.add_subplot(nrow, ncol, iexp+1)
            sub.plot([15., 22.], [1., 1.], c='k', ls='--', lw=2)
            sub.errorbar(wmean, rate, err_rate, fmt='.C0', elinewidth=2, markersize=10)
            if rname in ['r_mag', 'r_mag_legacy']: 
                sub.vlines(19.5, 0., 1.2, color='k', linestyle=':', linewidth=1)
            else: 
                sub.vlines(21., 0., 1.2, color='k', linestyle=':', linewidth=1)
            if rname == 'r_mag': 
                sub.set_xlim([16.5, 20.]) 
            elif rname == 'r_mag_legacy': 
                sub.set_xlim([16.5, 21.]) 
            elif rname == 'r_fibermag': 
                sub.set_xlim([18., 22.]) 
            sub.set_ylim([0.6, 1.1])
            sub.set_yticks([0.6, 0.7, 0.8, 0.9, 1.]) 
            if iexp == ncol-1: 
                sub.legend(loc='lower right', markerscale=0.5, handletextpad=-0.7, prop={'size': 20})
            if (iexp % ncol) != 0:  
                sub.set_yticklabels([]) 
            if (iexp // ncol) != nrow-1: 
                sub.set_xticklabels([]) 

            sub.text(0.05, 0.05, ('%i.' % (iexp+1)), ha='left', va='bottom', transform=sub.transAxes, fontsize=20)
            sub.text(0.95, 0.4, r'$t_{\rm exp} = %.f$' % (fexps['texp_total'][iexp]), 
                    ha='right', va='bottom', transform=sub.transAxes, fontsize=10) 
            #sub.text(0.95, 0.275, r'exp factor = %.1f, airmass = %.2f' % (fbright, fexps['airmass'][iexp]), 
            #        ha='right', va='bottom', transform=sub.transAxes, fontsize=10) 
            sub.text(0.95, 0.15, r'moon ill=%.2f, alt=%.f, sep=%.f' % 
                    (fexps['moon_ill'][iexp], fexps['moon_alt'][iexp], fexps['moon_sep'][iexp]), 
                    ha='right', va='bottom', transform=sub.transAxes, fontsize=10) 
            sub.text(0.95, 0.025, r'sun alt=%.f, sep=%.f' % 
                    (fexps['sun_alt'][iexp], fexps['sun_sep'][iexp]), 
                    ha='right', va='bottom', transform=sub.transAxes, fontsize=10) 

        bkgd = fig.add_subplot(111, frameon=False)
        bkgd.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
        if rname == 'r_mag': 
            bkgd.set_xlabel(r'$r_{\rm GAMA}$ magnitude', labelpad=10, fontsize=30)
        elif rname == 'r_mag_legacy': 
            bkgd.set_xlabel(r'Legacy DR7 $r$ magnitude', labelpad=10, fontsize=30)
        elif rname == 'r_fibermag':
            bkgd.set_xlabel(r'Legacy DR7 $r$ 1" aperture magnitude', labelpad=10, fontsize=30)
        bkgd.set_ylabel(r'redrock redshift success', labelpad=10, fontsize=30)

        fig.subplots_adjust(wspace=0.05, hspace=0.05)

        ffig = specfile.replace('sourceSpec', 'zsuccess_%s' % rname).replace('.hdf5', '.%s' % os.path.basename(expfile).replace('.hdf5', '.deltachi2_%.f.png' % min_deltachi2))
        fig.savefig(ffig, bbox_inches='tight') 
    return None 


def zsuccess_fibermag_halpha(specfile, expfile, min_deltachi2=40.):
    ''' plot the compiled redshift success rate for the redrock output 
    of BGS-like spectra for the nexp observing conditions

    :param spec_flag: 
        noiseless source spectra file. (default: 'GALeg.g15.sourceSpec.3000.hdf5') 
    '''
    # read in noiseless spectra (for true redshift and r-band magnitude) 
    fspec = h5py.File(specfile, 'r') 
    ztrue   = fspec['gama-spec']['z'][...]

    g_mag   = UT.flux2mag(fspec['legacy-photo']['flux_g'][...], method='log')
    r_mag   = UT.flux2mag(fspec['legacy-photo']['flux_r'][...], method='log')
    z_mag   = UT.flux2mag(fspec['legacy-photo']['flux_z'][...], method='log')
    w1_mag  = UT.flux2mag(fspec['legacy-photo']['flux_w1'][...], method='log')
    
    # r-band fiber magnitude 
    r_fibermag = fspec['r_mag_apflux'][...]
    
    # halpha probe 
    _halpha = (z_mag - w1_mag) - 3./2.5 * (g_mag - r_mag) + 1.2 

    # read in sampled exposures
    fexps = h5py.File(expfile, 'r') 
    iexp = 0 # only the first exposrue

    print('%s' % ', '.join(['%s = %.2f' % (k, fexps[k][iexp]) 
        for k in ['texp_total', 'airmass', 'moon_alt', 'moon_ill', 'moon_sep', 'sun_alt', 'sun_sep']]))
            
    # read in redrock outputs
    f_bgs = specfile.replace('sourceSpec', 'bgsSpec').replace('.hdf5', '.%s' % os.path.basename(expfile).replace('.hdf5', '.exp%i.rr.fits' % iexp))
    rr      = fits.open(f_bgs)[1].data
    zrr     = rr['Z']
    dchi2   = rr['DELTACHI2']
    zwarn   = rr['ZWARN']

    # redshift success 
    zsuccess_exp = UT.zsuccess(zrr, ztrue, zwarn, deltachi2=dchi2, min_deltachi2=min_deltachi2) 

    redherring = (r_mag < 18.5) 

    high_sbright = (r_fibermag < 21.) 

    fig = plt.figure(figsize=(16,5))

    sub = fig.add_subplot(131)
    sub.plot([15., 22.], [1., 1.], c='k', ls='--', lw=2)

    wmean, rate, err_rate = UT.zsuccess_rate(r_mag, zsuccess_exp, range=[15, 22], nbins=28, bin_min=10) 
    sub.errorbar(wmean, rate, err_rate, fmt='.k', elinewidth=2, markersize=10)
    
    zsuccess_exp_high_sbright = UT.zsuccess(
            zrr[high_sbright], ztrue[high_sbright], zwarn[high_sbright], deltachi2=dchi2[high_sbright], min_deltachi2=min_deltachi2) 
    wmean, rate, err_rate = UT.zsuccess_rate(r_mag[high_sbright], zsuccess_exp_high_sbright, range=[15, 22], nbins=28, bin_min=10) 
    sub.errorbar(wmean, rate, err_rate, fmt='.C0', elinewidth=2, markersize=10, label=r'$r_{\rm fiber} < 21.$')

    zsuccess_exp_low_sbright = UT.zsuccess(
            zrr[~high_sbright], ztrue[~high_sbright], zwarn[~high_sbright], deltachi2=dchi2[~high_sbright], min_deltachi2=min_deltachi2) 
    wmean, rate, err_rate = UT.zsuccess_rate(r_mag[~high_sbright], zsuccess_exp_low_sbright, range=[15, 22], nbins=28, bin_min=10) 
    sub.errorbar(wmean, rate, err_rate, fmt='.C1', elinewidth=2, markersize=10, label=r'$r_{\rm fiber} > 21.$')

    sub.vlines(19.5, 0., 1.2, color='k', linestyle=':', linewidth=1)
    sub.set_xlabel(r'$r$ magnitude', fontsize=25)
    sub.set_xlim([16.5, 21.]) 
    sub.set_ylabel(r'$z$ success rate', fontsize=25)
    sub.set_ylim([0.6, 1.1])
    sub.set_yticks([0.6, 0.7, 0.8, 0.9, 1.]) 
    sub.legend(loc='lower left', frameon=True, handletextpad=0.1, fontsize=15)

    sub = fig.add_subplot(132)
    sub.scatter(r_mag[zsuccess_exp], r_fibermag[zsuccess_exp], c='C0', s=2, label='$z$ success') 
    sub.scatter(r_mag[~zsuccess_exp], r_fibermag[~zsuccess_exp], c='C1', s=2, label='$z$ fail') 
    sub.plot([18, 23], [18, 23], c='k', ls='--') 
    sub.set_xlabel('$r$ magnitude', fontsize=25) 
    sub.set_xlim(18., 23.) 
    sub.set_ylabel('$r$ fiber magnitude', fontsize=25) 
    sub.set_ylim(18., 23.) 
    sub.legend(loc='lower right', handletextpad=0.1, markerscale=5, fontsize=15, frameon=True)

    sub = fig.add_subplot(133)
    sub.scatter(r_fibermag[zsuccess_exp], _halpha[zsuccess_exp], c='C0', s=2, label='$z$ success') 
    sub.scatter(r_fibermag[~zsuccess_exp], _halpha[~zsuccess_exp], c='C1', s=2, label='$z$ fail') 
    sub.scatter(r_fibermag[~zsuccess_exp & ~redherring], _halpha[~zsuccess_exp & ~redherring], c='C3', s=3, label='$z$ fail + $r > 18.5$') 
    sub.vlines(21, -1., 2., color='k', linestyle='--', linewidth=1)
    sub.set_xlabel('$r$ fiber magnitude', fontsize=25) 
    sub.set_xlim(18., 23.) 
    sub.set_ylabel('$(z - W1) - 3/2.5 (g - r) + 1.2$', fontsize=20) 
    sub.set_ylim(-1., 2.) 
    sub.legend(loc='upper left', handletextpad=0.1, markerscale=5, fontsize=15, frameon=True)
    
    fig.subplots_adjust(wspace=0.3) 
    ffig = specfile.replace('sourceSpec', 'zsuccess.fibermag_halpha').replace('.hdf5', '.%s' % os.path.basename(expfile).replace('.hdf5', '.deltachi2_%.f.png' % min_deltachi2))
    fig.savefig(ffig, bbox_inches='tight') 
    return None 


def zsuccess_TSreview(specfile, min_deltachi2=40.):
    ''' redshift success rate from redrock for 3 different observing conditions and 
    different exposure times 
    '''
    # read in noiseless spectra (for true redshift and r-band magnitude) 
    _fspec = os.path.join(dir_dat, specfile)
    fspec           = h5py.File(_fspec, 'r') 
    ztrue           = fspec['gama-spec']['z'].value # true redshift 

    r_mag_gama      = fspec['r_mag_gama'][...]
    r_fibermag      = fspec['r_mag_apflux'][...]
    r_mag_legacy    = UT.flux2mag(fspec['legacy-photo']['flux_r'].value, method='log')
    
    fig = plt.figure(figsize=(12, 4))
    
    texps = 60. * np.array([3, 5, 8, 12, 15]) # 3 to 15 min 

    for iexp in range(3): 
        sub = fig.add_subplot(1,3,iexp+1)
        sub.plot([15., 22.], [1., 1.], c='k', ls='--', lw=2)

        for itexp, texp in enumerate(texps): 
            # read in redrock output  
            frr = _fspec.replace('sourceSpec', 'bgsSpec').replace('.hdf5', '.TSreview.exp%i.texp_%.f.rr.fits' % (iexp, texp))
            rr      = fits.open(frr)[1].data
            zrr     = rr['Z']
            dchi2   = rr['DELTACHI2']
            zwarn   = rr['ZWARN']

            # redshift success 
            zsuccess_exp = UT.zsuccess(zrr, ztrue, zwarn, deltachi2=dchi2, min_deltachi2=min_deltachi2) 
            wmean, rate, err_rate = UT.zsuccess_rate(r_mag_gama, zsuccess_exp, range=[15, 22], nbins=28, bin_min=10) 
            sub.errorbar(wmean, rate, err_rate, fmt='.C%i' % itexp, elinewidth=2, markersize=10, 
                    label=r'$t_{\rm exp} = %.fs$' % texp)
            sub.plot(wmean, rate, color='C%i' % itexp)
            #sub.fill_between(wmean, rate - err_rate, rate + err_rate, color='C%i' % itexp, linewidth=0, alpha=0.75)
            #if iexp == 0: sub.fill_between([],[],[], color='C%i' % itexp, alpha=0.75, label=r'$t_{\rm exp} = %.fs$' % texp) 

        sub.set_xlim([18.3, 20.]) 
        sub.set_ylim([0.6, 1.1])
        sub.set_yticks([0.6, 0.7, 0.8, 0.9, 1.]) 
        if iexp != 0: sub.set_yticklabels([]) 
        if iexp == 0: sub.text(0.95, 0.95, 'faint moon', ha='right', va='top', transform=sub.transAxes, fontsize=20)
        if iexp == 1: sub.text(0.95, 0.95, 'bright moon', ha='right', va='top', transform=sub.transAxes, fontsize=20)
        if iexp == 2: sub.text(0.95, 0.95, 'twilight', ha='right', va='top', transform=sub.transAxes, fontsize=20)
        
        if iexp == 0: sub.legend(loc='lower left', handletextpad=0.2, fontsize=12) 

    bkgd = fig.add_subplot(111, frameon=False)
    bkgd.tick_params(labelcolor='none', top=False, bottom=False, left=False, right=False)
    bkgd.set_xlabel(r'$r_{\rm GAMA}$ magnitude', labelpad=10, fontsize=25)
    bkgd.set_ylabel(r'$z$ success rate', labelpad=10, fontsize=25)

    fig.subplots_adjust(wspace=0.1)
    ffig = os.path.join(dir_dat, 'GALeg.zsuccess.TSreview.png')
    fig.savefig(ffig, bbox_inches='tight') 
    ffig = os.path.join(dir_dat, 'GALeg_zsuccess_TSreview.pdf')
    fig.savefig(ffig, bbox_inches='tight') 
    return None 


if __name__=="__main__": 
    #zsuccess_TSreview('GALeg.g15.sourceSpec.5000.hdf5', min_deltachi2=40.)
    #zsuccess_surveysim(
    #        os.path.join(dir_dat, 'GALeg.g15.sourceSpec.5000.hdf5'), 
    #        os.path.join(dir_dat, 'exposures_surveysim_fork_150sv0p5.sample.seed0.hdf5'),
    #        min_deltachi2=40.)
    zsuccess_fibermag_halpha(
            os.path.join(dir_dat, 'GALeg.g15.sourceSpec.5000.hdf5'), 
            os.path.join(dir_dat, 'exposures_surveysim_fork_150sv0p5.sample.seed0.hdf5'),
            min_deltachi2=40.)
