#!/bin/usr/python 
import os
import sys
import subprocess
import numpy as np 
# -- feasibgs -- 
from feasibgs import util as UT
from feasibgs import catalogs as Cat
from feasibgs import forwardmodel as FM 

from redrock.external.desi import rrdesi


def expSpectra(field, dr_gama=3, dr_legacy=7, skycondition='bright', seed=1, exptime=480, i_blocks=None):
    ''' spectra with simulated exposure for the galaxies in the 
    `field` region of the Gama-Legacy catalog.
    '''
    if skycondition not in ['bright', 'dark']: raise ValueError
    # read in GAMA-Legacy catalog 
    cata = Cat.GamaLegacy()
    gleg = cata.Read(field, dr_gama=dr_gama, dr_legacy=dr_legacy)

    redshift = gleg['gama-spec']['z'] # redshift 
    absmag_ugriz = cata.AbsMag(gleg, kcorr=0.1, H0=70, Om0=0.3, galext=False) # ABSMAG k-correct to z=0.1 
    ngal = len(redshift) # number of galaxies
    print('%i galaxies in %s region of GLeg catalog' % (ngal, field))

    # match galaxies in the catalog to BGS templates
    bgs3 = FM.BGStree() 
    match = bgs3._GamaLegacy(gleg) 
    hasmatch = (match != -999) 
    print('%i galaxies do not have matches' % (len(match) - np.sum(hasmatch)))
    
    n_block = (ngal // 5000) + 1 
    if i_blocks is None: 
        i_blocks = range(n_block) 
    
    # r-band aperture magnitude from Legacy photometry 
    r_mag_apflux = UT.flux2mag(gleg['legacy-photo']['apflux_r'][:,1])
    # r-band magnitude from GAMA (SDSS) photometry 
    r_mag_gama = gleg['gama-photo']['modelmag_r']
    vdisp = np.repeat(100.0, ngal) # velocity dispersions [km/s]
   
    dir_spec = ''.join([UT.dat_dir(), 'spectra/gamadr', str(dr_gama), '_legacydr', str(dr_legacy), '/']) 
    for i_block in i_blocks: 
        print('block %i of %i' % (i_block+1, n_block))
        in_block = (hasmatch & 
                (np.arange(ngal) >= i_block * 5000) & 
                (np.arange(ngal) < (i_block+1) * 5000))
        # calculate source spectra from templates
        s_bgs = FM.BGSsourceSpectra(wavemin=1500.0, wavemax=2e4)
        # add emission lines 
        emline_flux = s_bgs.EmissionLineFlux(gleg, index=np.arange(ngal)[in_block], 
                dr_gama=dr_gama, silent=True)
        print('---- emission line flux constructed ----') 
        flux_eml, wave, _, magnorm_flag = s_bgs.Spectra(r_mag_apflux[in_block], redshift[in_block], 
                vdisp[in_block], seed=seed, templateid=match[in_block], 
                emflux=emline_flux, mag_em=r_mag_gama[in_block], silent=False) 
        print('---- source spectra constructed ----') 

        # simulate exposure for DESI-like spectra  
        f = ''.join([dir_spec, field, '.synSpectra.', skycondition, 'sky.seed', str(seed), 
            '.exptime', str(exptime), '.', str(i_block+1), 'of', str(n_block), 'blocks.fits']) 
        fdesi = FM.fakeDESIspec() 
        bgs_spectra = fdesi.simExposure(wave, flux_eml, skycondition=skycondition, 
                exptime=exptime, filename=f) 
        print('---- synthetic spectra constructed ----') 

        # output GAMA-Legacy data 
        fblock = ''.join([dir_spec, 'gleg.', field, '.', skycondition, 'sky.seed', str(seed), 
            '.exptime', str(exptime), '.', str(i_block+1), 'of', str(n_block), 'blocks.hdf5']) 
        cata_block = cata.select(index=in_block)
        cata_block['forwardmodel'] = {} 
        cata_block['forwardmodel']['magnorm_flag'] = magnorm_flag
        cata.write(cata_block, fblock)
        # save indices for future reference 
        f_indx = ''.join([dir_spec, 'gleg.', field, '.', skycondition, 'sky.seed', str(seed), 
            '.exptime', str(exptime), '.', str(i_block+1), 'of', str(n_block), 'blocks.index']) 
        np.savetxt(f_indx, np.arange(ngal)[in_block], fmt='%i')
    return None 


def expSpectra_faintEmLine(field, dr_gama=3, skycondition='bright', seed=1, exptime=480):
    ''' simulated spectra with simulated exposure for the galaxies in the 
    Gama-Legacy survey that have faint Halpha emission lines. 
    '''
    if skycondition not in ['bright', 'dark']: raise ValueError
    # read in GAMA-Legacy catalog 
    cata = Cat.GamaLegacy()
    gleg = cata.Read(field)

    redshift = gleg['gama-spec']['z'] # redshift 
    ha_gama = gleg['gama-spec']['ha_flux'] # halpha line flux 
    absmag_ugriz = cata.AbsMag(gleg, kcorr=0.1, H0=70, Om0=0.3, galext=False) # ABSMAG k-correct to z=0.1 
    ngal = len(redshift) # number of galaxies
    print('%i galaxies out of %i do not have Halpha flux' % (np.sum(ha_gama < 0.), ngal))

    # match galaxies in the catalog to BGS templates
    bgs3 = FM.BGStree() 
    match = bgs3._GamaLegacy(gleg) 
    hasmatch = (match != -999) 
    print('%i galaxies out of %i do not have matches' % ((len(match) - np.sum(hasmatch)), ngal))
    
    # r-band aperture magnitude from Legacy photometry 
    has_rapflux = (gleg['legacy-photo']['apflux_r'][:,1] > 0) 
    r_mag_apflux = UT.flux2mag(gleg['legacy-photo']['apflux_r'][:,1])
    # r-band magnitude from GAMA (SDSS) photometry 
    r_mag_gama = gleg['gama-photo']['modelmag_r']
    vdisp = np.repeat(100.0, ngal) # velocity dispersions [km/s]
    print('%i galaxies out of %i do not have r-band aperture flux' % (np.sum(np.invert(has_rapflux)), ngal))
    
    # randomly select 1000 galaxies with faint Halpha line flux
    np.random.seed(seed)
    has_faint_emline = (ha_gama < 10.)
    faint_emline = np.random.choice(np.arange(ngal)[hasmatch & has_rapflux & has_faint_emline], 1000, replace=False) 

    s_bgs = FM.BGSsourceSpectra(wavemin=1500.0, wavemax=2e4)
    # emission line fluxes
    emline_flux = s_bgs.EmissionLineFlux(gleg, index=faint_emline, dr_gama=dr_gama, silent=True)
    
    flux_eml, wave, _ = s_bgs.Spectra(r_mag_apflux[faint_emline], redshift[faint_emline], 
            vdisp[faint_emline], seed=seed, templateid=match[faint_emline], 
            emflux=emline_flux, mag_em=r_mag_gama[faint_emline], silent=False) 

    # simulate exposure using 
    fdesi = FM.fakeDESIspec() 
        
    f = ''.join([UT.dat_dir(), 'spectra/',
        'GamaLegacy.', field, '.expSpectra.', skycondition, 'sky.seed', str(seed), 
        '.exptime', str(exptime), '.faintEmLine.fits']) 
    bgs_spectra = fdesi.simExposure(wave, flux_eml, skycondition=skycondition, exptime=exptime, filename=f) 
    # save indices for future reference 
    f_indx = ''.join([UT.dat_dir(), 'spectra/'
        'GamaLegacy.', field, '.expSpectra.', skycondition, 'sky.seed', str(seed), 
        '.exptime', str(exptime), '.faintEmLine.index']) 
    np.savetxt(f_indx, faint_emline, fmt='%i')
    return None 


def expSpectra_fixedvdispEmLine(field, dr_gama=3, skycondition='bright', seed=1, exptime=480, 
        vdisp=150.):
    ''' synthetic spectra with simulated exposure for the galaxies in the 
    5th "block" of the Gama-Legacy survey where emission lines have *fixed* 
    velocity dispersions. 
    '''
    if skycondition not in ['bright', 'dark']: raise ValueError
    # read in GAMA-Legacy catalog 
    cata = Cat.GamaLegacy()
    gleg = cata.Read(field)

    redshift = gleg['gama-spec']['z'] # redshift 
    absmag_ugriz = cata.AbsMag(gleg, kcorr=0.1, H0=70, Om0=0.3, galext=False) # ABSMAG k-correct to z=0.1 
    ngal = len(redshift) # number of galaxies
    print('%i galaxies in %s region of GLeg catalog' % (ngal, field))

    # match galaxies in the catalog to BGS templates
    bgs3 = FM.BGStree() 
    match = bgs3._GamaLegacy(gleg) 
    hasmatch = (match != -999) 
    print('%i galaxies do not have matches' % (len(match) - np.sum(hasmatch)))
    
    # r-band aperture magnitude from Legacy photometry 
    r_mag_apflux = UT.flux2mag(gleg['legacy-photo']['apflux_r'][:,1])
    # r-band magnitude from GAMA (SDSS) photometry 
    r_mag_gama = gleg['gama-photo']['modelmag_r']
    vdisp_arr = np.repeat(100.0, ngal) # velocity dispersions [km/s]
   
    n_block = (ngal // 1000) + 1 

    i_block = 4 
    in_block = (hasmatch & 
            (np.arange(ngal) >= i_block * 1000) & 
            (np.arange(ngal) < (i_block+1) * 1000))

    s_bgs = FM.BGSsourceSpectra(wavemin=1500.0, wavemax=2e4)
    # emission line fluxes
    emline_flux = s_bgs._EmissionLineFlux_vdisp(gleg, vdisp=vdisp, 
            index=np.arange(ngal)[in_block], dr_gama=dr_gama, silent=True)
    
    flux_eml, wave, _ = s_bgs.Spectra(r_mag_apflux[in_block], redshift[in_block], 
            vdisp_arr[in_block], seed=seed, templateid=match[in_block], 
            emflux=emline_flux, mag_em=r_mag_gama[in_block], silent=False) 

    # simulate exposure using 
    f = ''.join([UT.dat_dir(), 'spectra/',
        'GamaLegacy.', field, '.expSpectra.', skycondition, 'sky.seed', str(seed), 
        '.exptime', str(exptime), '.', str(i_block+1), 'of', str(n_block), 
        'blocks_fixedvdispEmLine_', str(int(vdisp)), 'kms.fits']) 
    fdesi = FM.fakeDESIspec() 
    bgs_spectra = fdesi.simExposure(wave, flux_eml, skycondition=skycondition, 
            exptime=exptime, filename=f) 
    # save indices for future reference 
    f_indx = ''.join([UT.dat_dir(), 'spectra/'
        'GamaLegacy.', field, '.expSpectra.', skycondition, 'sky.seed', str(seed), 
        '.exptime', str(exptime), '.', str(i_block+1), 'of', str(n_block), 
        'blocks_fixedvdispEmLine_', str(int(vdisp)), 'kms.index']) 
    np.savetxt(f_indx, np.arange(ngal)[in_block], fmt='%i')
    return None 


def expSpectra_noEmLine(skycondition='bright', seed=1, exptime=480):
    ''' simulated spectra with simulated exposure for the galaxies in the 
    Gama-Legacy survey that have **no** emission lines (i.e. we don't run 
    add emission line) . 
    '''
    if skycondition not in ['bright', 'dark']: raise ValueError
    # read in GAMA-Legacy catalog 
    cata = Cat.GamaLegacy()
    gleg = cata.Read()

    redshift = gleg['gama-spec']['z_helio'] # redshift 
    ha_gama = gleg['gama-spec']['ha'] # halpha line flux 
    absmag_ugriz = cata.AbsMag(gleg, kcorr=0.1, H0=70, Om0=0.3, galext=False) # ABSMAG k-correct to z=0.1 
    ngal = len(redshift) # number of galaxies

    # match galaxies in the catalog to BGS templates
    bgs3 = FM.BGStree() 
    match = bgs3._GamaLegacy(gleg) 
    hasmatch = (match != -999) 
    print('%i galaxies out of %i do not have matches' % ((len(match) - np.sum(hasmatch)), ngal))
    
    # r-band aperture magnitude from Legacy photometry 
    r_mag = UT.flux2mag(gleg['legacy-photo']['apflux_r'][:,1])
    vdisp = np.repeat(100.0, ngal) # velocity dispersions [km/s]
    
    # randomly select 1000 galaxies with faint Halpha line flux
    np.random.seed(seed)
    gals = np.random.choice(np.arange(ngal), 1000) 

    bgstemp = FM.BGStemplates(wavemin=1500.0, wavemax=2e4)
    flux, wave, meta = bgstemp.Spectra(r_mag[gals], redshift[gals], vdisp[gals],
            seed=seed, templateid=match[gals], silent=False) 
    # no emission lines = we don't run the line below
    #wave, flux_eml = bgstemp.addEmissionLines(wave, flux, gleg, faint_emline, silent=False)

    # simulate exposure using 
    fdesi = FM.fakeDESIspec() 

    f = ''.join([UT.dat_dir(), 'spectra/'
        'gama_legacy.expSpectra.', skycondition, 'sky.seed', str(seed), '.exptime', str(exptime), '.noEmLine.fits']) 
    bgs_spectra = fdesi.simExposure(wave, flux, skycondition=skycondition, exptime=exptime, filename=f) 
    # save indices for future reference 
    f_indx = ''.join([UT.dat_dir(), 'spectra/'
        'gama_legacy.expSpectra.', skycondition, 'sky.seed', str(seed), '.exptime', str(exptime), '.noEmLine.index']) 
    np.savetxt(f_indx, gals, fmt='%i')
    return None 


def _test_NERSC(): 
    ''' test that every part of the code is functional with a quick version of the 
    actual run
    '''
    # read in GAMA-Legacy catalog 
    cata = Cat.GamaLegacy()
    gleg = cata.Read()

    redshift = gleg['gama-spec']['z_helio'] # redshift 
    absmag_ugriz = cata.AbsMag(gleg, kcorr=0.1, H0=70, Om0=0.3, galext=False) # ABSMAG k-correct to z=0.1 

    # pick a random galaxy from the GAMA-legacy sample
    i_rand = np.random.choice(range(len(redshift)), size=10) 
    
    # match random galaxy to BGS templates
    bgs3 = FM.BGStree() 
    match = bgs3._GamaLegacy(gleg, index=i_rand) 
    mabs_temp = bgs3.meta['SDSS_UGRIZ_ABSMAG_Z01'] # template absolute magnitude 
    
    # r-band aperture magnitude from Legacy photometry 
    r_mag = UT.flux2mag(gleg['legacy-photo']['apflux_r'][i_rand,1])  

    bgstemp = FM.BGStemplates(wavemin=1500.0, wavemax=2e4)
    vdisp = np.repeat(100.0, len(i_rand)) # velocity dispersions [km/s]

    flux, wave, meta = bgstemp.Spectra(
            r_mag, redshift[i_rand], vdisp,
            seed=1, templateid=match, silent=False) 
    flux0 = flux.copy()  
    wave, flux_eml = bgstemp.addEmissionLines(wave, flux, gleg, i_rand, silent=False) 

    # simulate exposure using 
    fdesi = FM.fakeDESIspec() 
    f_bright =  UT.dat_dir()+'spectra_tmp_bright.fits'
    bgs_spectra_bright = fdesi.simExposure(wave, flux_eml, skycondition='bright', filename=f_bright) 

    rrdesi(options=['--zbest', ''.join([f_bright.split('.fits')[0]+'_zbest.fits']) , f_bright]) 
    return None 


if __name__=='__main__':
    tt = sys.argv[1]
    field = sys.argv[2]
    sky = sys.argv[3]
    seed = int(sys.argv[4])
    exptime = int(sys.argv[5]) 
    if tt == 'spectra': 
        expSpectra(field, dr_gama=3, dr_legacy=7, skycondition=sky, seed=seed, exptime=exptime)
    elif tt == 'spectra_block': 
        iblock = [int(sys.argv[6])]
        expSpectra(field, dr_gama=3, dr_legacy=7, skycondition=sky, seed=seed, exptime=exptime, i_blocks=iblock)
    elif tt == 'spectra_faintemline': 
        expSpectra_faintEmLine(field, skycondition=sky, seed=seed, exptime=exptime)
    elif tt == 'spectra_fixedvdispEmline': 
        expSpectra_fixedvdispEmLine(field, skycondition=sky, seed=seed, exptime=exptime, 
                vdisp=150.)
    else: 
        raise ValueError 
    #elif tt == 'spectra_noemline': 
    #    expSpectra_noEmLine(skycondition=sky, seed=seed, exptime=exptime)
