'''
script for making the mtl file from desitarget output 
'''
import os 
import glob
import h5py
import numpy as np 
import numpy.lib.recfunctions as rfn

import fitsio
import healpy as hp 
from astropy.table import Table
from pydl.pydlutils.spheregroup import spherematch
# -- desitarget --
from desitarget.targets import calc_priority, main_cmx_or_sv, set_obsconditions
from desitarget.sv1.sv1_targetmask import bgs_mask
# -- plotting -- 
import matplotlib as mpl
import matplotlib.pyplot as plt
if os.environ['NERSC_HOST'] != 'cori': 
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



dir_dat = '/global/cscratch1/sd/chahah/feasibgs/survey_validation/'
if not os.path.isdir(dir_dat): 
    dir_dat = '/Users/ChangHoon/data/feasiBGS/survey_validation/'


def mtl_dr9sv(seed=0): 
    ''' make MTL using DR9SV imaging 
    '''
    np.random.seed(seed)
    #########################################################################
    # compile sv tiles 
    #########################################################################
    # read SV tiles 
    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Mar2020.fits')) # new SV tiles
    print('%i BGS SV tiles' % len(sv['RA']))
    # get SV tiles *outside* of the DR9 SV imaging region 
    in_dr9 = _in_DR9_SVregion(sv['RA'], sv['DEC'])
    print('%i tiles outside of DR9' % np.sum(~in_dr9))
    #########################################################################
    # compile targets and match to truth table and SN host 
    #########################################################################
    # read targets from DR9SV 
    ftargets = ['sv1-targets-dr9-hp-X.fits']
    # for tiles outside of DR9SV read dr8 healpix
    phi = np.deg2rad(sv['RA'][~in_dr9])
    theta = 0.5 * np.pi - np.deg2rad(sv['DEC'][~in_dr9])
    ipixs = np.unique(hp.ang2pix(2, theta, phi, nest=True)) 
    print('     reading in healpixels', ipixs)
    for i in ipixs: 
        ftargets.append('sv1-targets-dr8-hp-%i.fits' % i) 
    n_targets = len(ftargets)

    for i, _ftarget in enumerate(ftargets): 
        ftarget = os.path.join(dir_dat, 'sv.spec_truth', 
                _ftarget.replace('.fits', '.spec_truth.sn_host.fits'))
        if not os.path.isfile(ftarget): 
            # read target files with truth tables 
            _f = os.path.join(dir_dat, 'sv.spec_truth', 
                _ftarget.replace('.fits', '.spec_truth.fits'))
            if not os.path.isfile(_f):  
                print('... matching %s to truth table' % _ftarget) 
                _target = fitsio.read(os.path.join(dir_dat, _ftarget)) 
                target = match2spectruth(_target)
                fitsio.write(_f, target, clobber=True)
            else: 
                target = fitsio.read(_f)

            print('... matching %s to SN host' % _ftarget) 
            target = match2snhost(target)
            fitsio.write(ftarget, target, clobber=True)
        else: 
            target = fitsio.read(ftarget)

        # construct MTLs for set of targets 
        mtl = make_mtl(target, seed=seed)
        fmtl = os.path.join(dir_dat, 'mtl',
                'mtl.bgs.dr9sv.%iof%i.seed%i.fits' % (i+1, n_targets, seed))
        mtl.write(fmtl, format='fits', overwrite=True) 
    return None 


def check_mtl_dr9sv(): 
    ''' check the target fraction of the MTLs  
    '''
    for fmtl in glob.glob(os.path.join(dir_dat, 'mtl', '*.fits')): 
        print('--- %s ---' % fmtl) 
        # read MTL 
        mtl = fitsio.read(fmtl)

        n_bgs, n_bgs_bright, n_bgs_faint, n_bgs_extfaint, n_bgs_fibmag, n_bgs_lowq = \
                bgs_targetclass(mtl['SV1_BGS_TARGET'])

        print('total n_bgs = %i' % n_bgs)
        print('                       nobj frac (expected frac)')  
        print('     ------------------------------------')  
        print('     BGS Bright          %i %.3f (0.45)' % (n_bgs_bright, n_bgs_bright/n_bgs))
        print('     BGS Faint           %i %.3f (0.25)' % (n_bgs_faint, n_bgs_faint/n_bgs))
        print('     BGS Ext.Faint       %i %.3f (0.125)' % (n_bgs_extfaint, n_bgs_extfaint/n_bgs))
        print('     BGS Fib.Mag         %i %.3f (0.125)' % (n_bgs_fibmag, n_bgs_fibmag/n_bgs))
        print('     BGS Low Q.          %i %.3f (0.05)' % (n_bgs_lowq, n_bgs_lowq/n_bgs))
    return None 


def make_mtl(targets, seed=None):
    ''' construct mtl given targets. 

    notes: 
    -----
    * At the moment, highest priority is set for targets with spectroscopic
    redshifts or are SN hosts. 
    '''
    assert 'IN_SPECTRUTH' in targets.dtype.names
    assert 'HAS_SN' in targets.dtype.names

    np.random.seed(seed)
    # determine whether the input targets are main survey, cmx or SV.
    colnames, masks, survey = main_cmx_or_sv(targets)
    # ADM set the first column to be the "desitarget" column
    desi_target, desi_mask = colnames[0], masks[0]
    n = len(targets)

    # ADM if the input target columns were incorrectly called NUMOBS or PRIORITY
    # ADM rename them to NUMOBS_INIT or PRIORITY_INIT.
    for name in ['NUMOBS', 'PRIORITY']:
        targets.dtype.names = [name+'_INIT' if col == name else col for col in targets.dtype.names]

    # ADM if a redshift catalog was passed, order it to match the input targets
    # ADM catalog on 'TARGETID'.
    ztargets = Table()
    ztargets['TARGETID'] = targets['TARGETID']
    ztargets['NUMOBS'] = np.zeros(n, dtype=np.int32)
    ztargets['Z'] = -1 * np.ones(n, dtype=np.float32)
    ztargets['ZWARN'] = -1 * np.ones(n, dtype=np.int32)
    # ADM if zcat wasn't passed, there is a one-to-one correspondence
    # ADM between the targets and the zcat.
    zmatcher = np.arange(n)

    # ADM extract just the targets that match the input zcat.
    targets_zmatcher = targets[zmatcher]

    # ADM use passed value of NUMOBS_INIT instead of calling the memory-heavy calc_numobs.
    # ztargets['NUMOBS_MORE'] = np.maximum(0, calc_numobs(ztargets) - ztargets['NUMOBS'])
    ztargets['NUMOBS_MORE'] = np.maximum(0, targets_zmatcher['NUMOBS_INIT'] - ztargets['NUMOBS'])

    # ADM need a minor hack to ensure BGS targets are observed once
    # ADM (and only once) every time during the BRIGHT survey, regardless
    # ADM of how often they've previously been observed. I've turned this
    # ADM off for commissioning. Not sure if we'll keep it in general.

    # ADM only if we're considering bright survey conditions.
    ii = targets_zmatcher[desi_target] & desi_mask.BGS_ANY > 0
    ztargets['NUMOBS_MORE'][ii] = 1

    # ADM assign priorities, note that only things in the zcat can have changed priorities.
    # ADM anything else will be assigned PRIORITY_INIT, below.
    priority = calc_priority(targets_zmatcher, ztargets, 'BRIGHT')

    # set subpriority in order to tune the SV target densities 
    # BGS target classes: BRIGHT, FAINT, EXTFAINT, FIBERMAG, LOWQ
    # initial DR8 target density ---> desired density
    # BRIGHT:   882.056980 ---> 540 = 63%   0.62 - 1  
    # FAINT:    746.769486 ---> 300 = 41%   0.41 - 1
    # EXTFAINT: 623.470673 ---> 150 = 24%   0    - 1
    # FIBERMAG: 207.534409 ---> 150 = 71%   0.66 - 1
    # LOW Q:    55.400240  ---> 60  = 100%  0.76 - 1
    # (depending on imaging LOWQ varies a lot! DES~50/deg2, DECALS~114/deg2, North~185/deg2) 

    # bgs bitmask
    bitmask_bgs = targets['SV1_BGS_TARGET']
    has_spec    = targets['IN_SPECTRUTH'] # objects in spectroscopic truth table  
    has_sn      = targets['HAS_SN']

    # BGS objects with spectra or hosts SN 
    special         = np.zeros(n).astype(bool) #(has_spec | has_sn) 
    bgs_special    =  special & (bitmask_bgs).astype(bool) 

    bgs_all         = ~special & (bitmask_bgs).astype(bool)
    bgs_bright      = ~special & (bitmask_bgs & bgs_mask.mask('BGS_BRIGHT')).astype(bool)
    bgs_faint       = ~special & (bitmask_bgs & bgs_mask.mask('BGS_FAINT')).astype(bool)
    bgs_extfaint    = ~special & (bitmask_bgs & bgs_mask.mask('BGS_FAINT_EXT')).astype(bool) # extended faint
    bgs_fibmag      = ~special & (bitmask_bgs & bgs_mask.mask('BGS_FIBMAG')).astype(bool) # fiber magn limited
    bgs_lowq        = ~special & (bitmask_bgs & bgs_mask.mask('BGS_LOWQ')).astype(bool) # low quality

    n_bgs           = np.sum(bgs_special) + np.sum(bgs_all) 
    n_bgs_special   = np.sum(bgs_special) 
    n_bgs_bright    = np.sum(bgs_bright)
    n_bgs_faint     = np.sum(bgs_faint)
    n_bgs_extfaint  = np.sum(bgs_extfaint)
    n_bgs_fibmag    = np.sum(bgs_fibmag)
    n_bgs_lowq      = np.sum(bgs_lowq)

    # target classes with spectra
    n_bgs_sp, n_bgs_bright_sp, n_bgs_faint_sp, n_bgs_extfaint_sp, n_bgs_fibmag_sp, n_bgs_lowq_sp = \
            bgs_targetclass(targets['SV1_BGS_TARGET'][special])

    #f_special   = 1. # keep 100%
    #f_bright    = 0.45 / n_bgs_bright
    #f_faint     = 0.25 / n_bgs_faint
    #f_extfaint  = 0.125 / n_bgs_extfaint
    #f_fibmag    = 0.125 / n_bgs_fibmag
    #f_lowq      = 0.05 / n_bgs_lowq
    f_bright    = 540. / (n_bgs_bright + n_bgs_bright_sp)
    f_faint     = 300. / (n_bgs_faint + n_bgs_faint_sp) 
    f_extfaint  = 150. / (n_bgs_extfaint + n_bgs_extfaint_sp)
    f_fibmag    = 150. / (n_bgs_fibmag + n_bgs_fibmag_sp)
    f_lowq      = 60. / (n_bgs_lowq + n_bgs_lowq_sp) 
    f_ref = np.min([f_bright, f_faint, f_extfaint, f_fibmag, f_lowq])

    r_special   = 1.#(1. - f_ref / f_special) 
    r_bright    = (1. - f_ref / f_bright)
    r_faint     = (1. - f_ref / f_faint)   
    r_extfaint  = (1. - f_ref / f_extfaint)
    r_fibmag    = (1. - f_ref / f_fibmag)
    r_lowq      = (1. - f_ref / f_lowq)

    subpriority = np.random.uniform(0., 1., n) 
    subpriority[bgs_special]    = np.random.uniform(r_special, 1., np.sum(bgs_special))
    subpriority[bgs_bright]     = np.random.uniform(r_bright, 1., np.sum(bgs_bright))
    subpriority[bgs_faint]      = np.random.uniform(r_faint, 1., np.sum(bgs_faint))
    subpriority[bgs_extfaint]   = np.random.uniform(f_extfaint, 1, np.sum(bgs_extfaint))
    subpriority[bgs_fibmag]     = np.random.uniform(r_fibmag, 1, np.sum(bgs_fibmag))
    subpriority[bgs_lowq]       = np.random.uniform(r_lowq, 1, np.sum(bgs_lowq))

    _sample = (bitmask_bgs).astype(bool) & (subpriority > 0.943)#np.random.uniform(0., 1., n)) 
    _n_bgs, _n_bgs_bright, _n_bgs_faint, _n_bgs_extfaint, _n_bgs_fibmag, _n_bgs_lowq = \
            bgs_targetclass(targets['SV1_BGS_TARGET'][_sample])

    # set priority of all BGS targets equal 
    priority[bgs_all] = 2000
    print('---------------------------------')
    print('total n_bgs = %i' % n_bgs)
    print('approx. target class fractions') 
    print('                       orig frac exp. frac (target frac)')  
    print('     ------------------------------------')  
    #print('     BGS special         %i %.3f' % (n_bgs_special, n_bgs_special/n_bgs))
    #print('     BGS Bright          %i %.3f (0.45)' % (n_bgs_bright, n_bgs_bright/n_bgs))
    #print('     BGS Faint           %i %.3f (0.25)' % (n_bgs_faint, n_bgs_faint/n_bgs))
    #print('     BGS Ext.Faint       %i %.3f (0.125)' % (n_bgs_extfaint, n_bgs_extfaint/n_bgs))
    #print('     BGS Fib.Mag         %i %.3f (0.125)' % (n_bgs_fibmag, n_bgs_fibmag/n_bgs))
    #print('     BGS Low Q.          %i %.3f (0.05)' % (n_bgs_lowq, n_bgs_lowq/n_bgs))
    print('     BGS Bright        %.3f  %.3f (0.45)' % (n_bgs_bright/n_bgs, _n_bgs_bright/_n_bgs))
    print('     BGS Faint         %.3f  %.3f (0.25)' % (n_bgs_faint/n_bgs, _n_bgs_faint/_n_bgs))
    print('     BGS Ext.Faint     %.3f  %.3f (0.125)' % (n_bgs_extfaint/n_bgs, _n_bgs_extfaint/_n_bgs))
    print('     BGS Fib.Mag       %.3f  %.3f (0.125)' % (n_bgs_fibmag/n_bgs, _n_bgs_fibmag/_n_bgs))
    print('     BGS Low Q.        %.3f  %.3f (0.05)' % (n_bgs_lowq/n_bgs, _n_bgs_lowq/_n_bgs))

    # If priority went to 0==DONOTOBSERVE or 1==OBS or 2==DONE, then NUMOBS_MORE should also be 0.
    # ## mtl['NUMOBS_MORE'] = ztargets['NUMOBS_MORE']
    #ii = (priority <= 2)
    #log.info('{:d} of {:d} targets have priority zero, setting N_obs=0.'.format(np.sum(ii), n))
    #ztargets['NUMOBS_MORE'][ii] = 0

    # - Set the OBSCONDITIONS mask for each target bit.
    obsconmask = set_obsconditions(targets)

    # ADM set up the output mtl table.
    mtl = Table(targets)
    mtl.meta['EXTNAME'] = 'MTL'
    # ADM any target that wasn't matched to the ZCAT should retain its
    # ADM original (INIT) value of PRIORITY and NUMOBS.
    mtl['NUMOBS_MORE'] = mtl['NUMOBS_INIT']
    mtl['PRIORITY'] = mtl['PRIORITY_INIT']
    # ADM now populate the new mtl columns with the updated information.
    mtl['OBSCONDITIONS'] = obsconmask
    mtl['PRIORITY'][zmatcher] = priority
    mtl['SUBPRIORITY'][zmatcher] = subpriority
    mtl['NUMOBS_MORE'][zmatcher] = ztargets['NUMOBS_MORE']

    # Filtering can reset the fill_value, which is just wrong wrong wrong
    # See https://github.com/astropy/astropy/issues/4707
    # and https://github.com/astropy/astropy/issues/4708
    mtl['NUMOBS_MORE'].fill_value = -1
    return mtl


def dr8_skies_cutouts(): 
    ''' compiled skies file for BGS tiles outside of the dr9sv regions 
    '''
    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Mar2020.fits')) # new SV tiles
    in_dr9 = _in_DR9_SVregion(sv['RA'], sv['DEC'])
    print("%i tiles outside of DR9SV" % (np.sum(~in_dr9)))

    # DR8 sky files 
    fskies = glob.glob('/global/cfs/cdirs/desi/target/catalogs/dr8/0.37.0/skies/*fits')

    dr8_skies = [] 
    for fsky in fskies: 
        print('... reading %s' % fsky)
        sky = fitsio.read(fsky)
        
        keep = np.zeros(len(sky['RA'])).astype(bool)
        for tile_ra, tile_dec in zip(sv['RA'][~in_dr9], sv['DEC'][~in_dr9]): 
            keep = keep | (np.sqrt((sky['RA'] - tile_ra)**2 + (sky['DEC'] - tile_dec)**2) < 2.)

            dr8_skies.append(sky[keep])

    dr8_skies = np.concatenate(dr8_skies) 
    fitsio.write(os.path.join(dir_dat, 'mtl', 'dr8_skies_cutout.fits'), dr8_skies, clobber=True)
    return None 


def _in_DR9_SVregion(ras, decs): 
    ''' DR9 imaging SV region listed in
    https://desi.lbl.gov/trac/wiki/TargetSelectionWG/SVFields_for_DR9
    '''
    sv_regions = {}
    sv_regions['01_s82']            = [30.,40.,-7.,2.]
    sv_regions['02_egs']            = [210.,220.,50.,55.]
    sv_regions['03_gama09']         = [129.,141.,-2.,3.]
    sv_regions['04_gama12']         = [175.,185.,-3.,2.]
    sv_regions['05_gama15']         = [212.,222.,-2.,3.]
    sv_regions['06_overlap']        = [135.,160.,30.,35.]
    sv_regions['07_refnorth']       = [215.,230.,41.,46.]
    sv_regions['08_ages']           = [215.,220.,30.,40.]
    sv_regions['09_sagittarius']    = [200.,210.,5.,10.]
    sv_regions['10_highebv_n']      = [140.,150.,65.,70.]
    sv_regions['11_highebv_s']      = [240.,245.,20.,25.]
    sv_regions['12_highstardens_n'] = [273.,283.,40.,45.]
    sv_regions['13_highstardens_s'] = [260.,270.,15.,20.]
   
    n_tiles = len(ras)
    in_dr9 = np.zeros(n_tiles).astype(bool) 
    for i, ra, dec in zip(range(n_tiles), ras, decs): 
        for k in sv_regions.keys(): 
            if ((ra >= sv_regions[k][0]) & (ra <= sv_regions[k][1]) & 
                    (dec >= sv_regions[k][2]) & (dec <= sv_regions[k][3])): 
                in_dr9[i] = True
    return in_dr9 


def match2spectruth(targets): 
    ''' match target table to spectroscopic truth table
    '''
    assert 'BRICKID' in targets.dtype.names
    assert 'BRICK_OBJID' in targets.dtype.names 
    isbgs = (targets['SV1_BGS_TARGET']).astype(bool) 
    targ_brickid    = targets['BRICKID'][isbgs]
    targ_objid      = targets['BRICK_OBJID'][isbgs]

    # read in spectroscopic truth table
    spectruth   = h5py.File(os.path.join(dir_dat, 'bgs_truth_table.hdf5'), 'r') 
    st_brickid  = spectruth['BRICKID'][...]
    st_objid    = spectruth['OBJID'][...]

    in_spectruth = np.zeros(targets.shape[0]).astype(bool)
    gama_cataid  = np.repeat(-999, targets.shape[0]) 
    #in_spectruth.dtype.names = ['ID', 'IN_SPECTRUTH']
    ii = np.arange(targets.shape[0])
    indices, cataid = [], [] 

    uniq_brickid = np.unique(targ_brickid) 
    for brickid in uniq_brickid: 
        in_targbrick = (targ_brickid == brickid)
        in_specbrick = (st_brickid == brickid)
        #in_spec = np.isin(targ_objid[in_targbrick], st_objid[in_specbrick])
        _, in_spec, in_targ = np.intersect1d(targ_objid[in_targbrick], st_objid[in_specbrick], 
                return_indices=True)
        if len(in_spec) > 0: 
            #print(len(in_spec))
            #print(targets['RA'][isbgs][in_targbrick][in_spec] - spectruth['RA'][...][in_specbrick][in_targ]) 
            #print(targets['DEC'][isbgs][in_targbrick][in_spec] - spectruth['DEC'][...][in_specbrick][in_targ])
            #print(spectruth['GAMA_CATAID'][...][in_specbrick][in_targ]) 
            indices.append(ii[isbgs][in_targbrick][in_spec])
            cataid.append(spectruth['GAMA_CATAID'][...][in_specbrick][in_targ]) 

    in_spectruth[np.concatenate(indices)] = True
    gama_cataid[np.concatenate(indices)] = np.concatenate(cataid) 
    print('%i BGS SV targets have spectra' % np.sum(in_spectruth)) 
    targets = rfn.append_fields(targets, ['IN_SPECTRUTH'], [in_spectruth]) 
    targets = rfn.append_fields(targets, ['GAMA_CATAID'], [gama_cataid]) 
    return targets


def match2snhost(targets): 
    ''' match target table to supernovae hosts compiled by Segev
    '''
    assert 'BRICKID' in targets.dtype.names
    assert 'BRICK_OBJID' in targets.dtype.names 
    isbgs = (targets['SV1_BGS_TARGET']).astype(bool) 
    targ_ra     = targets['RA'][isbgs]
    targ_dec    = targets['DEC'][isbgs]

    # read in supernovae hosts
    snhost  = fitsio.read(os.path.join(dir_dat, 'snhost_dr8_target.fits'))
    sn_ra   = snhost['RA']
    sn_dec  = snhost['DEC']

    has_sn = np.zeros(targets.shape[0]).astype(bool)
    # spherematch compiled hosts 
    m_targ, m_sn, d_match = spherematch(targ_ra, targ_dec, sn_ra, sn_dec, 0.000277778, maxmatch=1) 
    has_sn[m_targ] = True
    print('%i BGS SV targets are supernova hosts' % np.sum(has_sn)) 
    targets = rfn.append_fields(targets, ['HAS_SN'], [has_sn]) 
    return targets


def mtl_dr8sv_healpy(spectruth=True, seed=None): 
    ''' generate MTLs from targets in healpixels with SV tiles 
    '''
    #sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Sep2019.fits')) # old SV tiles
    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Jan2020.fits')) # new SV tiles
    phi = np.deg2rad(sv['RA'])
    theta = 0.5 * np.pi - np.deg2rad(sv['DEC'])

    ipixs = np.unique(hp.ang2pix(2, theta, phi, nest=True)) 
    
    for i in ipixs: 
        print('--- %i pixel ---' % i) 
        targets = fitsio.read(os.path.join(dir_dat, 'sv.spec_truth', 'sv1-targets-dr8-hp-%i.spec_truth.fits' % i))
        mtl = make_mtl_healpix(targets, spectruth=spectruth, seed=seed)
        
        if spectruth:
            dir_mtl = os.path.join(dir_dat, 'mtl.spec_truth')
            fmtl = os.path.join(dir_mtl, 'mtl.dr8.0.34.0.bgs_sv.hp-%i.spec_truth.seed%i.fits' % (i, seed))
        else: 
            dir_mtl = os.path.join(dir_dat, 'mtl')
            fmtl = os.path.join(dir_mtl, 'mtl.dr8.0.34.0.bgs_sv.hp-%i.seed%i.fits' % (i, seed))
        mtl.write(fmtl, format='fits', overwrite=True) 
    return None 


def test_mtl_SV_healpy(): 
    ''' test the MTLs by plotting the SV BGS target fractions in each of healpix 
    '''
    fig = plt.figure(figsize=(20,20))
    gs = mpl.gridspec.GridSpec(3,2, figure=fig)

    classes = ['BGS_BRIGHT', 'BGS_FAINT', 'BGS_FAINT_EXT', 'BGS_FIBMAG', 'BGS_LOWQ', 'IN_SPECTRUTH']
    subs = [plt.subplot(gs[i], projection='mollweide') for i in range(6)]

    dir_mtl = os.path.join(dir_dat, 'mtl.spec_truth')

    for cl, sub in zip(classes, subs):  
        print(cl) 
        fclass_pixs = np.zeros(hp.nside2npix(2))

        for fmtl in glob.glob(os.path.join(dir_mtl, 'mtl.dr8.0.34.0.bgs_sv.hp-*.fits')): 
            # read MTL 
            mtl = fitsio.read(fmtl)

            # bgs bitmask
            bitmask_bgs = mtl['SV1_BGS_TARGET'] 
            n_bgs = float(np.sum((bitmask_bgs).astype(bool))) 
            
            if cl != 'IN_SPECTRUTH': 
                bgs_class = (bitmask_bgs & bgs_mask.mask(cl)).astype(bool)
            else:
                # fraction of galaxies in spectroscopic truth tables 
                bgs_class = (bitmask_bgs.astype(bool) & mtl['IN_SPECTRUTH'])

            # calculate target fraction in healpix 
            ipix = int(os.path.basename(fmtl).split('-')[-1].split('.')[0])
            fclass_pixs[ipix] = float(np.sum(bgs_class)) / n_bgs

        plt.axes(sub) 
        hp.mollview(fclass_pixs, nest=True, rot=180., hold=True, title=cl) 

    fig.savefig(os.path.join(dir_dat, 'mtl_healpix_targetclass.png'), bbox_inches='tight') 
    return None 


def match2spec_SV_healpy(): 
    ''' append desitarget SV output files with column specifying spectroscopic 
    truth tables. 
    '''
    #sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Sep2019.fits')) # old SV tiles
    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Jan2020.fits')) # new SV tiles
    phi = np.deg2rad(sv['RA'])
    theta = 0.5 * np.pi - np.deg2rad(sv['DEC'])

    ipixs = np.unique(hp.ang2pix(2, theta, phi, nest=True)) 
    
    dir_sv = '/project/projectdirs/desi/target/catalogs/dr8/0.34.0/targets/sv/resolve/bright/'
    for i in ipixs: 
        if i <= 17: continue
        print('--- %i pixel ---' % i) 
        targets = fitsio.read(os.path.join(dir_sv, 'sv1-targets-dr8-hp-%i.fits' % i))
        targets = match2spectruth(targets) 
        fitsio.write(os.path.join(dir_dat, 'sv.spec_truth', 'sv1-targets-dr8-hp-%i.spec_truth.fits' % i), targets, clobber=True)
    return None 


def test_match2spec_SV_healpy(): 
    ''' plot where the spectroscopic truth table SV targets lie
    '''
    # old SV tiles
    #sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Sep2019.fits')) 
    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Jan2020.fits')) # new SV tiles
    phi_sv = np.deg2rad(sv['RA'])
    theta_sv = 0.5 * np.pi - np.deg2rad(sv['DEC'])
    
    pixs = np.zeros(hp.nside2npix(2))
    ipixs = np.unique(hp.ang2pix(2, theta_sv, phi_sv, nest=True)) 
    
    dir_sv = '/project/projectdirs/desi/target/catalogs/dr8/0.34.0/targets/sv/resolve/bright/'
    for i in ipixs: pixs[i] = 1.
    hp.mollview(pixs, nest=True, rot=180.) 

    for i in ipixs: 
        targ = fitsio.read(os.path.join(dir_dat, 'sv.spec_truth', 'sv1-targets-dr8-hp-%i.spec_truth.fits' % i))
        targ_spectrue = targ[targ['IN_SPECTRUTH']] 

        phi = np.deg2rad(targ_spectrue['RA'])
        theta = 0.5 * np.pi - np.deg2rad(targ_spectrue['DEC'])

        hp.projscatter(theta[::10], phi[::10], c='C1', s=1)
    hp.projscatter(theta_sv, phi_sv, c='C0', s=20)

    plt.savefig(os.path.join(dir_dat, 'match2spec_SV_healpix.png'), bbox_inches='tight') 
    return None 


def target_dr8healpix(target_class='bright'): 
    ''' examine target class densities for DR8 healpixels
    '''
    dir_sv = '/project/projectdirs/desi/target/catalogs/dr8/0.34.0/targets/sv/resolve/bright/'
    ftargs = glob.glob(os.path.join(dir_sv, '*.fits')) 
    
    pixs = np.zeros(hp.nside2npix(2))

    for ftarg in ftargs: 
        ipix = int(os.path.basename(ftarg).split('-')[-1].replace('.fits', ''))
        print('--- %i pixel ---' % ipix) 

        targets = fitsio.read(ftarg)
        n_bgs, n_bgs_bright, n_bgs_faint, n_bgs_extfaint, n_bgs_fibmag, n_bgs_lowq = \
                bgs_targetclass(targets['SV1_BGS_TARGET'])
        
        if target_class == 'bright': 
            pixs[ipix] = n_bgs_bright/n_bgs 
        elif target_class == 'faint': 
            pixs[ipix] = n_bgs_faint/n_bgs 
        elif target_class == 'extfaint':
            pixs[ipix] = n_bgs_extfaint/n_bgs 
        elif target_class == 'fibmag':
            pixs[ipix] = n_bgs_fibmag/n_bgs 
        elif target_class == 'lowq':
            pixs[ipix] = n_bgs_lowq/n_bgs 
    
    if target_class != 'lowq': 
        hp.mollview(pixs, nest=True, rot=180., title='%s Target Class Fraction' % target_class.upper()) 
    else: 
        hp.mollview(pixs, nest=True, rot=180., title='%s Target Class Fraction' % target_class.upper(), min=0., max=0.2) 

    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Sep2019.fits')) 
    phi = np.deg2rad(sv['RA'])
    theta = 0.5 * np.pi - np.deg2rad(sv['DEC'])
    hp.projscatter(theta, phi, c='k', s=20)

    plt.savefig(os.path.join(dir_dat, 'target_healpix.%s.png' % target_class), bbox_inches='tight') 
    return None 


def bgs_truth_table(): 
    ''' compile list of brickid, objid, ra, dec, north or south, name of survey of
    spectroscopic truth tables that Mike compiled 
    '''
    brickid, objid, ra, dec, nors, survey, gama_cataid = [], [], [], [], [], [], [] 
    for ns in ['north', 'south']: 
        fspecs = glob.glob(os.path.join(dir_dat, 'truth_table', '*-%s-standard.fits' % ns))

        dir_match = '/project/projectdirs/desi/target/analysis/truth/dr8.0/%s/matched/' % ns
        for fspec in fspecs:
            print(fspec)
            _fspec = os.path.basename(fspec).replace('-%s-standard.fits' % ns, '')

            fmatch = glob.glob(os.path.join(dir_match, 'ls-dr8.0-*%s*' % _fspec))
            assert len(fmatch) == 1
            print(fmatch[0]) 

            tab = fitsio.read(fmatch[0])
            print('%i objects in %s' % (tab.shape[0], os.path.basename(fmatch[0])))

            brickid.append(tab['BRICKID'])
            objid.append(tab['OBJID'])
            ra.append(tab['RA'])
            dec.append(tab['DEC'])
            nors.append(np.repeat(ns, tab.shape[0]))
            survey.append(np.repeat(os.path.basename(fmatch[0]), tab.shape[0]))

            if 'GAMA' in fmatch[0]: # append CATAID from gama 
                fgama = fmatch[0].replace('ls-dr8.0-', '')
                print(fgama) 
                gama = fitsio.read(fgama) # read gama data 
                gama_cataid.append(gama['CATAID']) 
            else: 
                gama_cataid.append(np.repeat(-999, tab.shape[0]))
    
    fmaster = h5py.File(os.path.join(dir_dat, 'bgs_truth_table.hdf5'), 'w') 
    fmaster.create_dataset('BRICKID', data=np.concatenate(brickid))
    fmaster.create_dataset('OBJID', data=np.concatenate(objid))
    fmaster.create_dataset('RA', data=np.concatenate(ra))
    fmaster.create_dataset('DEC', data=np.concatenate(dec))
    fmaster.create_dataset('NORS', data=np.concatenate(nors).astype('S'))
    fmaster.create_dataset('SURVEY', data=np.concatenate(survey).astype('S'))
    fmaster.create_dataset('GAMA_CATAID', data=np.concatenate(gama_cataid))
    fmaster.close() 
    return None  


def target_densities(): 
    ''' Examine the target class densities for the different healpixels to
    see the variation in the targeting 
    '''
    dir_sv = '/project/projectdirs/desi/target/catalogs/dr8/0.34.0/targets/sv/resolve/bright/'
    for i in ipixs: 
        print('--- %i pixel ---' % i) 
        targets = fitsio.read(os.path.join(dir_sv, 'sv1-targets-dr8-hp-%i.fits' % i))
        mtl = make_mtl(targets)
        mtl.write(os.path.join(dir_dat, 'mtl.dr8.0.34.0.bgs_sv.hp-%i.fits' % i), format='fits') 


def master_truth_table(): 
    ''' compile master list of brickid, objid, ra, dec, north or south, name of survey of
    spectroscopic truth tables 
    '''
    import h5py 
    brickid, objid, ra, dec, nors, survey = [], [], [], [], [], []
    for ns in ['north', 'south']: 
        dir_match = '/project/projectdirs/desi/target/analysis/truth/dr8.0/%s/matched/' % ns
        ftabs = glob.glob(dir_match+'ls-dr8.0*') 
        for ftab in ftabs: 
            tab = fitsio.read(ftab)
            print('%i objects in %s' % (tab.shape[0], os.path.basename(ftab)))

            brickid.append(tab['BRICKID'])
            objid.append(tab['OBJID'])
            ra.append(tab['RA'])
            dec.append(tab['DEC'])
            nors.append(np.repeat(ns, tab.shape[0]))
            survey.append(np.repeat(os.path.basename(ftab), tab.shape[0]))
    
    fmaster = h5py.File(os.path.join(dir_dat, 'master_truth_table.hdf5'), 'w') 
    fmaster.create_dataset('BRICKID', data=np.concatenate(brickid))
    fmaster.create_dataset('OBJID', data=np.concatenate(objid))
    fmaster.create_dataset('RA', data=np.concatenate(ra))
    fmaster.create_dataset('DEC', data=np.concatenate(dec))
    fmaster.create_dataset('NORS', data=np.concatenate(nors).astype('S'))
    fmaster.create_dataset('SURVEY', data=np.concatenate(survey).astype('S'))
    fmaster.close() 
    return None  


def bgs_targetclass(bitmask_bgs): 
    n_bgs = np.float(np.sum(bitmask_bgs.astype(bool))) 
    n_bgs_bright    = np.sum((bitmask_bgs & bgs_mask.mask('BGS_BRIGHT')).astype(bool))
    n_bgs_faint     = np.sum((bitmask_bgs & bgs_mask.mask('BGS_FAINT')).astype(bool))
    n_bgs_extfaint  = np.sum((bitmask_bgs & bgs_mask.mask('BGS_FAINT_EXT')).astype(bool)) # extended faint
    n_bgs_fibmag    = np.sum((bitmask_bgs & bgs_mask.mask('BGS_FIBMAG')).astype(bool)) # fiber magnitude limited
    n_bgs_lowq      = np.sum((bitmask_bgs & bgs_mask.mask('BGS_LOWQ')).astype(bool)) # low quality
    return n_bgs, n_bgs_bright, n_bgs_faint, n_bgs_extfaint, n_bgs_fibmag, n_bgs_lowq


if __name__=="__main__": 
    mtl_dr9sv(seed=0)
    #check_mtl_dr9sv()
    #dr8_skies_cutouts()
