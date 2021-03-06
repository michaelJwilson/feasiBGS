'''

script for testing the output of fiber assign

'''
import os 
import glob
import numpy as np 
# --- 
import fitsio
from astropy.io import fits
# -- desitarget -- 
from desitarget.sv1.sv1_targetmask import bgs_mask
# -- plotting -- 
import matplotlib as mpl
import matplotlib.pyplot as plt
if 'NERSC_HOST' not in os.environ: 
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


dir_dat = '/global/cscratch1/sd/chahah/feasibgs/survey_validation'


def new_SVfields(seed=1): 
    ''' compare SV fields from Sep 2019 to newly proposed SV regions from 
    Anand and Christophe Dec 2019.

    radius of tile is 1.6275 deg 
    '''
    import matplotlib.patches as patches
    np.random.seed(seed)

    sv_old = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Sep2019.fits')) 
    sv_new = sv_old.copy() 

    svdict = {}
    svdict['01_s82']            = '30,40,-7,2'
    svdict['02_egs']            = '210,220,50,55'
    svdict['03_gama12']         = '175,185,-3,2'
    svdict['04_gama15']         = '212,222,-2,3'
    svdict['05_overlap']        = '135,160,30,35'
    svdict['06_refnorth']       = '215,230,41,46'
    svdict['07_ages']           = '215,220,30,40'
    svdict['08_sagittarius']    = '200,210,5,10'
    svdict['09_highebv_n']      = '140,150,65,70'
    svdict['10_highebv_s']      = '240,245,20,25'
    svdict['11_highstardens_n'] = '273,283,40,45'
    svdict['12_highstardens_s'] = '260,270,15,20'

    # regions that were omitted 
    omitted = {} 
    omitted['g09'] = '129,141,-1,3'
    omitted['PRIMUS-COSMOS'] = '149.6,150.7,1.8,2.9'
    omitted['PRIMUS-CDFS-SWIRE'] = '51.8,54.4,-29.7,-28.0'

    # formulate new SV fields 
    # keep fields that already fall into regions 

    keep = np.zeros(len(sv_old['RA'])).astype(bool) 
    for reg in svdict.keys(): 
        # get RA, Dec range of new SV regions 
        ra_min, ra_max      = float(svdict[reg].split(',')[0]), float(svdict[reg].split(',')[1])
        dec_min, dec_max    = float(svdict[reg].split(',')[2]), float(svdict[reg].split(',')[3])
        inkeep = (
                (sv_old['RA'] > ra_min) & (sv_old['RA'] < ra_max) & 
                (sv_old['DEC'] > dec_min) & (sv_old['DEC'] < dec_max)
                )    
        keep = keep | inkeep
    print('keeping %i previous fields in new region' % np.sum(keep))
    
    for reg in omitted.keys(): 
        ra_min, ra_max      = float(omitted[reg].split(',')[0]), float(omitted[reg].split(',')[1])
        dec_min, dec_max    = float(omitted[reg].split(',')[2]), float(omitted[reg].split(',')[3])
        inkeep = (
                (sv_old['RA'] > ra_min) & 
                (sv_old['RA'] < ra_max) & 
                (sv_old['DEC'] > dec_min) & 
                (sv_old['DEC'] < dec_max)
                ) 
        keep = keep | inkeep 
    print('keeping %i previous fields including omitted regions' % np.sum(keep))

    # put SV tiles on high EBV regions and high star density 
    ra_new, dec_new = [], [] 
    for reg in ['01_s82', '02_egs', '05_overlap', '06_refnorth', '08_sagittarius', '09_highebv_n', '10_highebv_s', '11_highstardens_n', '12_highstardens_s']: 
        ra_min, ra_max      = float(svdict[reg].split(',')[0]), float(svdict[reg].split(',')[1])
        dec_min, dec_max    = float(svdict[reg].split(',')[2]), float(svdict[reg].split(',')[3])
        
        if reg == '10_highebv_s': 
            ra_new.append([0.5*(ra_min + ra_max)])
            dec_new.append([0.5*(dec_min + dec_max)]) 
        elif reg == '06_refnorth': 
            ra_new.append([0.5*(ra_min + ra_max)-4.89, 0.5*(ra_min + ra_max)-1.63, 0.5*(ra_min + ra_max)+1.63, 0.5*(ra_min + ra_max)+4.89])
            dec_new.append([0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max)]) 
        elif reg == '05_overlap': 
            ra_new.append([0.5*(ra_min + ra_max)-6.52, 0.5*(ra_min + ra_max)-3.26, 0.5*(ra_min + ra_max), 0.5*(ra_min + ra_max)+3.26, 0.5*(ra_min + ra_max)+6.52])
            dec_new.append([0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max)]) 
        elif reg == '01_s82':
            ra_new.append([0.5*(ra_min + ra_max)-1.63, 0.5*(ra_min + ra_max)+1.63])
            dec_new.append([0.25*dec_min + 0.75*dec_max, 0.25*dec_min + 0.75*dec_max]) 
        else: 
            ra_new.append([0.5*(ra_min + ra_max)-1.63, 0.5*(ra_min + ra_max)+1.63])
            dec_new.append([0.5*(dec_min + dec_max), 0.5*(dec_min + dec_max)]) 
    
    ra_new = np.concatenate(ra_new)
    dec_new = np.concatenate(dec_new)
    i_new = len(ra_new) 
    print('%i new SV fields in new regions' % i_new) 

    for i in range(i_new):
        sv_new['RA'][np.arange(len(sv_old['RA']))[~keep][i]] = ra_new[i]
        sv_new['DEC'][np.arange(len(sv_old['RA']))[~keep][i]] = dec_new[i]

    ra_new = np.concatenate([sv_old['RA'][keep], ra_new]) 
    dec_new = np.concatenate([sv_old['DEC'][keep], dec_new]) 

    # pick the rest of the tiles from desi-tiles.fits far from the selected tiles 
    desi_tiles = fitsio.read(os.path.join(dir_dat, 'desi-tiles.fits')) 
    
    keeptile = np.ones(desi_tiles.shape[0]).astype(bool) 
    for ra, dec in zip(ra_new, dec_new): 
        _keep = (
                (desi_tiles['IN_DESI'] == 1) & 
                (desi_tiles['PASS'] == 5) & 
                ((desi_tiles['RA'] - ra)**2 + (desi_tiles['DEC'] - dec)**2 > 100.)
                )
        keeptile = keeptile & _keep
     
    for i in range(60 - i_new - np.sum(keep)): 
        new_pick = np.random.choice(np.arange(np.sum(keeptile)), 1, replace=False) 
        _ra, _dec = desi_tiles['RA'][keeptile][new_pick], desi_tiles['DEC'][keeptile][new_pick]
        ra_new = np.concatenate([ra_new, _ra]) 
        dec_new = np.concatenate([dec_new, _dec]) 

        for k in sv_new.dtype.names:
            if k in desi_tiles.dtype.names: 
                sv_new[k][np.arange(len(sv_old['RA']))[~keep][i_new+i]] = desi_tiles[k][keeptile][new_pick][0]
    
        keeptile = keeptile & ((desi_tiles['RA'] - _ra)**2 + (desi_tiles['DEC'] - _dec)**2 > 100.)
    print('%i random new fields' % (60 - i_new - np.sum(keep)))

    # write out the tile centers 
    np.savetxt('updated_BGSSV_tile_centers.seed%i.dat' % seed, np.vstack([ra_new, dec_new]).T, fmt='%.2f %.2f')
    # write out 
    fitsio.write(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Jan2020.fits'), sv_new, clobber=True)

    # --- plot everything ---
    fig = plt.figure(figsize=(20,10))
    sub = fig.add_subplot(111)
    for i, reg in enumerate(svdict.keys()): 
        # get RA, Dec range of new SV regions 
        ra_min, ra_max      = float(svdict[reg].split(',')[0]), float(svdict[reg].split(',')[1])
        dec_min, dec_max    = float(svdict[reg].split(',')[2]), float(svdict[reg].split(',')[3])
        
        name = reg.split('_')[1]
        region = patches.Rectangle((ra_min, dec_min), (ra_max - ra_min), (dec_max - dec_min), 
                linewidth=1, edgecolor='C%i' % i, facecolor='none', label=name)
        sub.add_patch(region) 

    for i, reg in enumerate(omitted.keys()): 
        ra_min, ra_max      = float(omitted[reg].split(',')[0]), float(omitted[reg].split(',')[1])
        dec_min, dec_max    = float(omitted[reg].split(',')[2]), float(omitted[reg].split(',')[3])

        if i == 0:
            region = patches.Rectangle((ra_min, dec_min), (ra_max - ra_min), (dec_max - dec_min), 
                    linewidth=1, edgecolor='r', facecolor='none', linestyle='--', label='omitted')
        else: 
            region = patches.Rectangle((ra_min, dec_min), (ra_max - ra_min), (dec_max - dec_min), 
                    linewidth=1, edgecolor='r', facecolor='none', linestyle='--')
        sub.add_patch(region) 
        if reg != 'g09':
            sub.annotate(reg, xy=(0.5*(ra_min+ra_max), 0.5*(dec_min+dec_max)), xycoords='data',
                xytext=(ra_max-50., dec_max+20.), textcoords='data',
                arrowprops=dict(facecolor='black', width=0.1, headwidth=3),
                horizontalalignment='right', verticalalignment='top')
        else:
            sub.annotate(reg, xy=(0.5*(ra_min+ra_max), 0.5*(dec_min+dec_max)), xycoords='data',
                xytext=(ra_max-30., dec_max+10.), textcoords='data',
                arrowprops=dict(facecolor='black', width=0.1, headwidth=3),
                horizontalalignment='right', verticalalignment='top')

    for i in range(len(sv_old['RA'])): 
        circ = patches.Circle((sv_old['RA'][i], sv_old['DEC'][i]), 
                radius=1.6275, edgecolor='k', facecolor='none', linestyle=':') 
        sub.add_patch(circ) 
        #sub.scatter(sv_old['RA'], sv_old['DEC'], c='k', s=20, label='BGS SV')

    for i in range(len(sv_new['RA'])): 
        circ = patches.Circle((sv_new['RA'][i], sv_new['DEC'][i]), radius=1.6275, edgecolor='C1', facecolor='none') 
        sub.add_patch(circ) 

    sub.legend(loc='upper right', ncol=2, markerscale=2, handletextpad=0.2, fontsize=10)
    sub.set_xlabel('RA', fontsize=20)
    sub.set_xlim(360, 0)
    sub.set_ylabel('Dec', fontsize=20)
    sub.set_ylim(-40, 90)
    fig.savefig('new_SVregion.png', bbox_inches='tight') 
    return None 


def testFA_dr9sv(): 
    ''' test the fiberassign output of DR9SV 
    '''
    # all the fiberassign output files 
    f_fbas = glob.glob(os.path.join(dir_dat, 'fba_dr9sv.spec_truth.Mar2020',
        'fiberassign*.fits'))

    n_zero = 0
    n_nosky = 0 
    __n_bgs_bright, __n_bgs_faint, __n_bgs_extfaint, __n_bgs_fibmag, __n_bgs_lowq = [], [], [], [], []
    for i, f in enumerate(f_fbas): 
        # read in tile
        tile_i = fitsio.read(f)
        if i == 0: 
            tile = tile_i
        else: 
            tile = np.concatenate([tile, tile_i]) 

        _n_bgs, _n_bgs_bright, _n_bgs_faint, _n_bgs_extfaint, _n_bgs_fibmag, _n_bgs_lowq = \
                bgs_targetclass(tile_i['SV1_BGS_TARGET'])
        _n_sky = np.sum(tile_i['OBJTYPE'] == 'SKY')
        
        __n_bgs_bright.append(_n_bgs_bright/_n_bgs)
        __n_bgs_faint.append(_n_bgs_faint/_n_bgs)
        __n_bgs_extfaint.append(_n_bgs_extfaint/_n_bgs)
        __n_bgs_fibmag.append(_n_bgs_fibmag/_n_bgs)
        __n_bgs_lowq.append(_n_bgs_lowq/_n_bgs)

        print('---------------------------------')
        print('tiles: %s' % os.path.basename(f))
        print('total n_bgs = %i' % _n_bgs)
        print('                       nobj frac (expected frac)')  
        print('     ------------------------------------')  
        print('     BGS Bright          %i %.3f (0.45)' % (_n_bgs_bright, _n_bgs_bright/_n_bgs))
        print('     BGS Faint           %i %.3f (0.25)' % (_n_bgs_faint, _n_bgs_faint/_n_bgs))
        print('     BGS Ext.Faint       %i %.3f (0.125)' % (_n_bgs_extfaint, _n_bgs_extfaint/_n_bgs))
        print('     BGS Fib.Mag         %i %.3f (0.125)' % (_n_bgs_fibmag, _n_bgs_fibmag/_n_bgs))
        print('     BGS Low Q.          %i %.3f (0.05)' % (_n_bgs_lowq, _n_bgs_lowq/_n_bgs))
        print('     SKY                 %i' % (_n_sky)) 
        # tiles with no sky targets 
        if _n_sky == 0: n_nosky += 1
        # tiles with no BGS targets 
        if _n_bgs == 0: n_zero += 1
    print('---------------------------------')
    print('%i tiles with zero BGS targets' % n_zero)
    print('%i tiles with zero SKY targets' % n_nosky)

    n_bgs, n_bgs_bright, n_bgs_faint, n_bgs_extfaint, n_bgs_fibmag, n_bgs_lowq = \
            bgs_targetclass(tile['SV1_BGS_TARGET'])
    print('---------------------------------')
    print('total n_bgs = %i' % n_bgs)
    print('                       nobj frac (expected frac)')  
    print('     ------------------------------------')  
    print('     BGS Bright          %i %.3f, %.3f-%.3f (0.45)' % (n_bgs_bright, n_bgs_bright/n_bgs, np.min(__n_bgs_bright), np.max(__n_bgs_bright)))
    print('     BGS Faint           %i %.3f, %.3f-%.3f (0.25)' % (n_bgs_faint, n_bgs_faint/n_bgs, np.min(__n_bgs_faint), np.max(__n_bgs_faint)))
    print('     BGS Ext.Faint       %i %.3f, %.3f-%.3f (0.125)' % (n_bgs_extfaint, n_bgs_extfaint/n_bgs, np.min(__n_bgs_extfaint), np.max(__n_bgs_extfaint)))
    print('     BGS Fib.Mag         %i %.3f, %.3f-%.3f (0.125)' % (n_bgs_fibmag, n_bgs_fibmag/n_bgs, np.min(__n_bgs_fibmag), np.max(__n_bgs_fibmag)))
    print('     BGS Low Q.          %i %.3f, %.3f-%.3f (0.05)' % (n_bgs_lowq, n_bgs_lowq/n_bgs, np.min(__n_bgs_lowq), np.max(__n_bgs_lowq)))
    
    #fig = plt.figure(figsize=(10,5))
    #sub = fig.add_subplot(111)
    #sub.scatter(tile['TARGET_RA'], tile['TARGET_DEC'], c='k', s=2)
    #sub.scatter(tile['TARGET_RA'][_flags], tile['TARGET_DEC'][_flags], c='C1', s=2)

    ##sub.legend(loc='upper right', handletextpad=0.2, markerscale=5, fontsize=15) 
    #sub.set_xlabel('RA', fontsize=20)
    #sub.set_xlim(360., 0.)#tile['TARGET_RA'].min(), tile['TARGET_RA'].max())
    #sub.set_ylabel('Dec', fontsize=20)
    ##sub.set_ylim(22., 26) 
    #sub.set_ylim(-30., 80.)#tile['TARGET_DEC'].min(), tile['TARGET_DEC'].max())
    #fig.savefig(os.path.join(dir_dat, 'fba_dr9sv.spec_truth.Mar2020', 'fiberassign_outliers.png'), bbox_inches='tight') 
    return None 


def _dr9sv_nosky(): 
    ''' examine why some tiles have no sky fibers
    '''
    # all the fiberassign output files 
    f_fbas = glob.glob(os.path.join(dir_dat, 'fba_dr9sv.spec_truth.Mar2020',
        'fiberassign*.fits'))
    # all the sky targets
    f_skies = [ 
            "/global/cfs/cdirs/desi/target/catalogs/dr8/0.37.0/skies/skies-dr8-hp-0.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr8/0.37.0/skies/skies-dr8-hp-15.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr8/0.37.0/skies/skies-dr8-hp-19.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr8/0.37.0/skies/skies-dr8-hp-47.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-4.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-5.fits", 
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-7.fits", 
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-8.fits", 
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-9.fits", 
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-10.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-11.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-14.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-17.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-21.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-24.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-25.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-26.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-27.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-31.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-35.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-39.fits",
            "/global/cfs/cdirs/desi/target/catalogs/dr9sv/0.37.0/skies/skies-dr9-hp-43.fits"]

    fig = plt.figure(figsize=(10,5))
    sub = fig.add_subplot(111)
    for f in f_skies: 
        sky = fitsio.read(f) 
        _plt_sky = sub.scatter(sky['RA'][::100], sky['DEC'][::100], c='k', s=1)

    dr8sky = fitsio.read(os.path.join(dir_dat, 'mtl', 'dr8_skies_cutout.fits'))
    _plt_sky2 = sub.scatter(dr8sky['RA'][::100], dr8sky['DEC'][::100], c='C1', s=1)

    for f in f_fbas: 
        # read in tile
        tile_i = fitsio.read(f)
        _n_sky = np.sum(tile_i['OBJTYPE'] == 'SKY')

        if _n_sky == 0: 
            _plt_nosky = sub.scatter(tile_i['TARGET_RA'][::10], tile_i['TARGET_DEC'][::10],
                    c='r', s=1, label='No Sky Fibers')
        else: 
            _plt_bgs = sub.scatter(tile_i['TARGET_RA'][::10], tile_i['TARGET_DEC'][::10],
                    c='C0', s=1, label='BGS SV tile')

    sub.legend([_plt_sky, _plt_sky2, _plt_nosky, _plt_bgs], 
            ['Sky Targets', 'DR8 cut out', 'No Sky Fibers', 'BGS SV tiles'], 
            loc='upper right', handletextpad=0.2, markerscale=5, fontsize=15) 
    sub.set_xlabel('RA', fontsize=20)
    sub.set_xlim(360., 0.)#tile['TARGET_RA'].min(), tile['TARGET_RA'].max())
    sub.set_ylabel('Dec', fontsize=20)
    sub.set_ylim(-40., 90.)#tile['TARGET_DEC'].min(), tile['TARGET_DEC'].max())
    fig.savefig('fba_dr9sv_nosky.png', bbox_inches='tight') 
    return None 


def testFA_singletile(ftile): 
    ''' examine the different target classes for a single tile 
    '''
    # read in tile
    tile = fits.open(ftile)[1].data

    # bgs bitmasks
    bitmask_bgs     = tile['SV1_BGS_TARGET']
    bgs_bright      = (bitmask_bgs & bgs_mask.mask('BGS_BRIGHT')).astype(bool)
    bgs_faint       = (bitmask_bgs & bgs_mask.mask('BGS_FAINT')).astype(bool)
    bgs_extfaint    = (bitmask_bgs & bgs_mask.mask('BGS_FAINT_EXT')).astype(bool) # extended faint
    bgs_fibmag      = (bitmask_bgs & bgs_mask.mask('BGS_FIBMAG')).astype(bool) # fiber magnitude limited
    bgs_lowq        = (bitmask_bgs & bgs_mask.mask('BGS_LOWQ')).astype(bool) # low quality
    #2203 Bright
    #787 Faint
    #597 Ext.Faint
    #218 Fib.Mag.
    #67 Low Q.
    n_bgs, n_bgs_bright, n_bgs_faint, n_bgs_extfaint, n_bgs_fibmag, n_bgs_lowq = \
            bgs_targetclass(tile['SV1_BGS_TARGET'])
    
    print('---------------------------------')
    print('total n_bgs = %i' % n_bgs)
    print('%i' % (n_bgs_bright + n_bgs_faint + n_bgs_extfaint + n_bgs_fibmag + n_bgs_lowq))
    print('BGS Bright %i %.3f' % (n_bgs_bright, n_bgs_bright/n_bgs))
    print('BGS Faint %i %.3f' % (n_bgs_faint, n_bgs_faint/n_bgs))
    print('BGS Ext.Faint %i %.3f' % (n_bgs_extfaint, n_bgs_extfaint/n_bgs))
    print('BGS Fib.Mag %i %.3f' % (n_bgs_fibmag, n_bgs_fibmag/n_bgs))
    print('BGS Low Q. %i %.3f' % (n_bgs_lowq, n_bgs_lowq/n_bgs))
    
    fig = plt.figure(figsize=(10,10))
    sub = fig.add_subplot(111)
    sub.scatter(tile['TARGET_RA'], tile['TARGET_DEC'], c='k', s=1) 
    # BGS BRIGHT
    sub.scatter(tile['TARGET_RA'][bgs_bright], tile['TARGET_DEC'][bgs_bright], c='C0', s=3,
            label='Bright %i (%.2f)' % (np.sum(bgs_bright), np.float(np.sum(bgs_bright))/n_bgs)) 
    # BGS FAINT 
    sub.scatter(tile['TARGET_RA'][bgs_faint], tile['TARGET_DEC'][bgs_faint], c='C1', s=3, 
            label='Faint %i (%.2f)' % (np.sum(bgs_faint), np.float(np.sum(bgs_faint))/n_bgs)) 
    # BGS EXTFAINT 
    sub.scatter(tile['TARGET_RA'][bgs_extfaint], tile['TARGET_DEC'][bgs_extfaint], c='C4', s=5,
            label='Ext.Faint %i (%.2f)' % (np.sum(bgs_extfaint), np.float(np.sum(bgs_extfaint))/n_bgs)) 
    # BGS fibmag 
    sub.scatter(tile['TARGET_RA'][bgs_fibmag], tile['TARGET_DEC'][bgs_fibmag], c='C5', s=7, 
            label='Fib.Mag. %i (%.2f)' % (np.sum(bgs_fibmag), np.sum(bgs_fibmag)/n_bgs)) 
    # BGS Low quality 
    sub.scatter(tile['TARGET_RA'][bgs_lowq], tile['TARGET_DEC'][bgs_lowq], c='C3', s=9, 
            label='Low Q. %i (%.2f)' % (np.sum(bgs_lowq), np.sum(bgs_lowq)/n_bgs)) 
    
    sub.legend(loc='upper right', handletextpad=0.2, markerscale=5, fontsize=15) 
    sub.set_xlabel('RA', fontsize=20)
    sub.set_xlim(tile['TARGET_RA'].min(), tile['TARGET_RA'].max())
    sub.set_ylabel('Dec', fontsize=20)
    #sub.set_ylim(22., 26) 
    sub.set_ylim(tile['TARGET_DEC'].min(), tile['TARGET_DEC'].max())
    fig.savefig(os.path.join(dir_dat, ftile.replace('.fits', '.png')), bbox_inches='tight')  
    return None 


def testFA_tiles(): 
    '''
    '''
    n_zero = 0
    _flags = [] 
    for i, f in enumerate(glob.glob(os.path.join(dir_dat, 'fba_dr8.0.34.0.hp-comb', 'fiberassign*.fits'))): 
        # read in tile
        tile_i = fits.open(f)[1].data 
        if i == 0: 
            tile = tile_i
        else: 
            tile = np.concatenate([tile, tile_i]) 

        _n_bgs, _n_bgs_bright, _n_bgs_faint, _n_bgs_extfaint, _n_bgs_fibmag, _n_bgs_lowq = \
                bgs_targetclass(tile_i['SV1_BGS_TARGET'])
        print('---------------------------------')
        print('field %i, n_bgs = %f' % (i, _n_bgs))
        print('BGS Bright %.3f (0.45)' % (_n_bgs_bright/_n_bgs))
        print('BGS Faint %.3f (0.25)' % (_n_bgs_faint/_n_bgs))
        print('BGS Ext.Faint %.3f (0.125)' % (_n_bgs_extfaint/_n_bgs))
        print('BGS Fib.Mag %.3f (0.125)' % (_n_bgs_fibmag/_n_bgs))
        print('BGS Low Q. %.3f (0.05)' % (_n_bgs_lowq/_n_bgs))
        if _n_bgs == 0: n_zero += 1

        # high LOW Q
        if _n_bgs_lowq/_n_bgs > 0.1: 
            _flags.append(np.ones(len(tile_i['TARGET_RA'])))
        else: 
            _flags.append(np.zeros(len(tile_i['TARGET_RA'])))
    _flags = np.concatenate(_flags).astype(bool)

    n_bgs, n_bgs_bright, n_bgs_faint, n_bgs_extfaint, n_bgs_fibmag, n_bgs_lowq = \
            bgs_targetclass(tile['SV1_BGS_TARGET'])
    print('---------------------------------')
    print('%i tiles with zero BGS targets' % n_zero)
    print('---------------------------------')
    print('total n_bgs = %i' % n_bgs)
    print('BGS Bright %.3f (0.45)' % (n_bgs_bright/n_bgs))
    print('BGS Faint %.3f (0.25)' % (n_bgs_faint/n_bgs))
    print('BGS Ext.Faint %.3f (0.125)' % (n_bgs_extfaint/n_bgs))
    print('BGS Fib.Mag %.3f (0.125)' % (n_bgs_fibmag/n_bgs))
    print('BGS Low Q. %.3f (0.05)' % (n_bgs_lowq/n_bgs))
    
    fig = plt.figure(figsize=(10,5))
    sub = fig.add_subplot(111)
    sub.scatter(tile['TARGET_RA'], tile['TARGET_DEC'], c='k', s=2)
    sub.scatter(tile['TARGET_RA'][_flags], tile['TARGET_DEC'][_flags], c='C1', s=2)

    #sub.legend(loc='upper right', handletextpad=0.2, markerscale=5, fontsize=15) 
    sub.set_xlabel('RA', fontsize=20)
    sub.set_xlim(360., 0.)#tile['TARGET_RA'].min(), tile['TARGET_RA'].max())
    sub.set_ylabel('Dec', fontsize=20)
    #sub.set_ylim(22., 26) 
    sub.set_ylim(-30., 80.)#tile['TARGET_DEC'].min(), tile['TARGET_DEC'].max())
    fig.savefig(os.path.join(dir_dat, 'fba_dr8.0.34.0.hp-comb', 'fiberassign_outliers.png'), bbox_inches='tight') 
    return None 


def testFA_tiles_targetclass(spectruth=False): 
    ''' plot the target class fractions of the fiberassign output 
    '''
    # SV tiles 
    sv = fitsio.read(os.path.join(dir_dat, 'BGS_SV_30_3x_superset60_Sep2019.fits')) 
    phi = np.deg2rad(sv['RA'])
    theta = 0.5 * np.pi - np.deg2rad(sv['DEC'])

    fig = plt.figure(figsize=(30,10))
    gs = mpl.gridspec.GridSpec(2,3, figure=fig)

    if spectruth:
        ffba = os.path.join(dir_dat, 'fba_dr8.0.34.0.hp-comb.spec_truth', 'fiberassign*.fits')
        classes = ['BGS_BRIGHT', 'BGS_FAINT', 'BGS_FAINT_EXT', 'BGS_FIBMAG', 'BGS_LOWQ', 'IN_SPECTRUTH']
    else: 
        ffba = os.path.join(dir_dat, 'fba_dr8.0.34.0.hp-comb', 'fiberassign*.fits')
        classes = ['BGS_BRIGHT', 'BGS_FAINT', 'BGS_FAINT_EXT', 'BGS_FIBMAG', 'BGS_LOWQ']
    
    subs = [plt.subplot(gs[i], projection='mollweide') for i in range(len(classes))]

    for cl, sub in zip(classes, subs):  
        tras, tdecs, fclasses = [], [], [] 
        for ftile in glob.glob(ffba):
            # read in tile
            tile = fits.open(ftile)[1].data 
            tid     = int(ftile.split('-')[-1].replace('.fits', ''))  # tile ID 
            tra     = sv['RA'][sv['TILEID'] == tid] # tile phi 
            tdec    = sv['DEC'][sv['TILEID'] == tid] # tile theta 

            # bgs bitmask
            bitmask_bgs = tile['SV1_BGS_TARGET'] 
            n_bgs = float(np.sum((bitmask_bgs).astype(bool))) 
            
            if cl != 'IN_SPECTRUTH': 
                bgs_class = (bitmask_bgs & bgs_mask.mask(cl)).astype(bool)
            else:
                # fraction of galaxies in spectroscopic truth tables 
                bgs_class = (bitmask_bgs.astype(bool) & tile['IN_SPECTRUTH'])

            # calculate target fraction in tile  
            fclass = float(np.sum(bgs_class)) / n_bgs

            tras.append(tra)
            tdecs.append(tdec)
            fclasses.append(fclass) 

        tras = np.array(tras).flatten()
        tdecs = np.array(tdecs).flatten() 
        im = sub.scatter((tras - 180.) * np.pi/180., tdecs * np.pi/180., c=np.array(fclasses), cmap='viridis') 
        sub.set_title('%s (avg.frac. %.2f)' % (cl, np.mean(fclasses)), fontsize=20) 
        sub.set_xticklabels([]) 
        fig.colorbar(im, ax=sub)

    if spectruth: 
        ffig = os.path.join(dir_dat, 'fba_dr8.0.34.0.hp-comb.spec_truth', 'fiberassign_targetclass.png')
    else: 
        ffig = os.path.join(dir_dat, 'fba_dr8.0.34.0.hp-comb', 'fiberassign_targetclass.png')
    fig.savefig(ffig, bbox_inches='tight') 
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
    #new_SVfields()
    testFA_dr9sv()
    #_dr9sv_nosky()
    #testFA_tiles()
    #testFA_tiles_targetclass(spectruth=True)
    #testFA_tiles_targetclass(spectruth=False)
    #for f in glob.glob(os.path.join(dir_dat, 'subpriority_test', 'fiberassign-test0*.fits')): 
    #    testFA_singletile(f)
