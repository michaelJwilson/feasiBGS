'''

forward model a spectra from meta data. 
most of the functions here serve as wrappers
for `desisim` code 

References: 
    - https://github.com/desihub/desisim/blob/master/doc/nb/bgs-reference-spectra.ipynb
    - https://github.com/desihub/desisim/blob/master/doc/nb/bgs-redshift-efficiency.ipynb 
    - https://github.com/desihub/desisim/blob/master/py/desisim/scripts/quickspectra.py
'''
import os
import time 
import numpy as np 
from scipy.spatial import cKDTree as KDTree
# -- astropy 
from astropy.table import vstack
import astropy.units as u 
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM
# -- desi -- 
from speclite import filters
import specsim.simulator
from specsim.simulator import Simulator 
import specsim.config
from desimodel.io import load_throughput
from desisim.io import empty_metatable
from desisim.io import read_basis_templates
from desisim.obs import get_night
from desisim.templates import GALAXY 
from desisim.templates import BGS 
import desisim.simexp
import desisim.specsim
import desimodel.io
import desispec
import desitarget
from desisim import pixelsplines as pxs
from desispec.spectra import Spectra
from desispec.resolution import Resolution
from desispec.interpolation import resample_flux

# -- local -- 
from feasibgs import skymodel as Sky


LIGHT = 2.99792458E5  #- speed of light in km/s


class BGStree(object):
    '''class to deal with KDTree from BGS basis template metadata.
    Read in meta data of BGS basis templates, construct a KDTree
    and then use the KDTree to identify closest templates. 
    '''
    def __init__(self):
        # read in the meta data of the BGS basis templates
        self.meta = read_basis_templates(objtype='BGS', onlymeta=True)
        # construct KDTree from it 
        self.tree = KDTree(self.extractMeta())

    def extractMeta(self):
        ''' Extract quantities used to construct KDTree from the basis
        template meta data: redshift (z), M_0.1r, and 0.1(g-r).
        '''
        # read in necessary meta data
        zobj = self.meta['Z'].data  # redshift 
        mabs = self.meta['SDSS_UGRIZ_ABSMAG_Z01'].data # absolute magnitudes in SDSS ugriz bands kcorrected to z=0.1
        rmabs = mabs[:,2] # r-band absolute magnitude
        gr = mabs[:,1] - mabs[:,2] # g-r color 

        return np.vstack((zobj, rmabs, gr)).T
    
    def Query(self, matrix):
        '''Return the nearest template number based on the KD Tree.

        Parameters
        ----------
          matrix (numpy.ndarray): 
            M x N array (M=number of properties, N=number of objects) 
            in the same format as the corresponding function for each 
            object type (e.g., self.bgs).

        Returns
        -------
          - indx: index of nearest template (main item of interest) 
          - dist: distance to nearest template
        '''
        dist, indx = self.tree.query(matrix)
        return indx, dist

    def _GamaLegacy(self, gleg, index=False): 
        ''' Given `catalogs.GamaLegacy` class object, return matches to  
        template. This is purely for convenience. 
        '''
        from feasibgs import catalogs as Cat 
        # extract necessary meta data 
        redshift = gleg['gama-spec']['z']  # redshift
        # calculate ABSMAG k-correct to z=0.1 
        cata = Cat.GamaLegacy()
        absmag_ugriz = cata.AbsMag(gleg, kcorr=0.1, H0=70, Om0=0.3) 

        if not np.any(index): # match all galaxies in the GamaLegacy object
            ind = np.ones(absmag_ugriz.shape[1], dtype=bool) 
        else: # match only specified galaxies
            if not isinstance(index, np.ndarray): raise ValueError
            ind = index 
        
        # stack meta data -- [z, M_r0.1, 0.1(g-r)]
        gleg_meta = np.vstack([
            redshift[ind], 
            absmag_ugriz[2,ind], 
            absmag_ugriz[1,ind] - absmag_ugriz[2,ind]]).T

        # match to templates 
        match, _ = self.Query(gleg_meta)
        # in some cases there won't be a match from  KDTree.query
        # we flag these with -999 
        nomatch = (match >= len(self.meta['TEMPLATEID']))
        match[nomatch] = -999
        return match 


class BGSsourceSpectra(GALAXY):
    '''Generate source spectra for the forwardmodel using BGS templates
    and GAMA emission line fluxes 
    '''
    def __init__(self, wavemin=None, wavemax=None, dw=0.2):
        ''' initiate BGS template spectra. Mainly for initializing `desisim.templates.BGS`
        '''
        # default (buffered) wavelength vector
        if wavemin is None: self.wavemin = load_throughput('b').wavemin - 10.0
        if wavemax is None: self.wavemax = load_throughput('z').wavemax + 10.0
        self.dw = dw
        self.wave = np.arange(round(wavemin, 1), wavemax, dw)

        super(BGSsourceSpectra, self).__init__(objtype='BGS', minwave=3600.0, maxwave=10000.0, 
                cdelt=0.2, wave=self.wave, colorcuts_function=None, normfilter_south='decam2014-r', 
                normline=None, baseflux=None, basewave=None, basemeta=None)

    def Spectra(self, r_mag, zred, vdisp, seed=None, templateid=None, emflux=None, mag_em=None, silent=True):
        '''
        '''
        if isinstance(r_mag, np.ndarray):
            nobj = len(r_mag) 
        else: 
            nobj = 1
        # meta data of 'mag', 'redshift', 'vdisp'
        input_meta = empty_metatable(nmodel=nobj, objtype='BGS', input_meta=True)
        input_meta['SEED'] = seed #np.random.randint(2**32, size=nobj) 
        input_meta['MAG'] = r_mag # r band apparent magnitude
        input_meta['REDSHIFT'] = zred # redshift
        input_meta['VDISP'] = vdisp 
        input_meta['TEMPLATEID'] = templateid

        flux, self.wave, magnorm_flag = self._make_galaxy_templates(input_meta, emflux=emflux, mag_em=mag_em, 
                nocolorcuts=True, restframe=False, silent=silent) 

        return flux, self.wave, magnorm_flag

    def EmissionLineFlux(self, gleg, index=None, dr_gama=3, silent=True): 
        ''' Calculate emission line flux for GAMA-Legacy objects. Returns
        emission line flux in units of 10^(-17)erg/s/cm^2/A
        '''
        if dr_gama != 3: raise ValueError("Only supported for GAMA DR3") 
        # emission lines
        emline_keys = ['oiib', 'oiir', 'hb',  'oiiib', 'oiiir', 'oib', 'oir', 'niib', 'ha', 'niir', 'siib', 'siir']
        #emline_lambda = [3726., 3729., 4861., 4959., 5007., 6300., 6364., 6548., 6563., 6583., 6717., 6731.]
        # updated emission line wavelengths from 
        # https://github.com/desihub/desisim/blob/master/py/desisim/data/forbidden_lines.ecsv
        # and 
        # https://github.com/desihub/desisim/blob/master/py/desisim/data/recombination_lines.ecsv
        emline_lambda = [3727.092, 3729.874, 4862.683, 4960.295, 5008.239, 6302.046, 6365.535, 6549.852, 6564.613, 6585.277, 6718.294, 6732.673]
   
        if index is None: 
            index = np.arange(len(gleg['gama-photo']['ra'])) 
        else: 
            assert isinstance(index, np.ndarray)
        
        # gama spectra data
        gleg_s = gleg['gama-spec']

        npix = len(self.basewave)
        wave = self.basewave.astype(float)
        emline_flux = np.zeros((len(index), npix))
        
        # loop through emission lines and add them to the emline_flux! 
        for i_k, k in enumerate(emline_keys): 
            # galaxies with measured emission line (DR3 allows for negative emission lines...) 
            hasem = (gleg_s[k+'_flux'][index] > 0.)
            n_hasem = np.sum(hasem) 
            if n_hasem == 0: 
                if not silent: print('no galaxies with emission line %s' % k) 
                continue
            em_lineflux = gleg_s[k+'_flux'][index][hasem] # line flux [10^(-17) erg/s/cm^2]
            # width of Gaussian emission line 
            em_sig = gleg_s['sig_'+k][index][hasem] # Angstrom
            assert em_sig.min() > 0. 

            # normalization of the Gaussian
            A = em_lineflux/np.sqrt(2. * np.pi * em_sig**2)
            
            emline_flux[hasem] += A[:,None] * \
                    np.exp(-0.5*(np.tile(wave, n_hasem).reshape(n_hasem, npix) - emline_lambda[i_k])**2/em_sig[:,None]**2)
        return emline_flux 

    def _EmissionLineFlux_vdisp(self, gleg, vdisp=150., index=None, dr_gama=3, silent=True): 
        ''' Calculate emission line only spectra flux for GAMA-Legacy objects with fixed 
        emission line velocity dispersion. **This is mainly for testing purposes**. Returns
        emission line flux in units of 10^(-17)erg/s/cm^2/A
        '''
        if dr_gama != 3: raise ValueError("Only supported for GAMA DR3") 
        # emission lines
        emline_keys = ['oiib', 'oiir', 'hb',  'oiiib', 'oiiir', 'oib', 'oir', 'niib', 'ha', 'niir', 'siib', 'siir']
        emline_lambda = [3726., 3729., 4861., 4959., 5007., 6300., 6364., 6548., 6563., 6583., 6717., 6731.]
   
        if index is None: 
            index = np.arange(len(gleg['gama-photo']['ra'])) 
        else: 
            assert isinstance(index, np.ndarray)
        
        # gama spectra data
        gleg_s = gleg['gama-spec']

        npix = len(self.basewave)
        wave = self.basewave.astype(float)
        emline_flux = np.zeros((len(index), npix))
        
        # loop through emission lines and add them to the emline_flux! 
        for i_k, k in enumerate(emline_keys): 
            # galaxies with measured emission line (DR3 allows for negative emission lines...) 
            hasem = (gleg_s[k+'_flux'][index] > 0.)
            n_hasem = np.sum(hasem) 
            if n_hasem == 0: 
                if not silent: print('no galaxies with emission line %s' % k) 
                continue
            em_lineflux = gleg_s[k+'_flux'][index][hasem] # line flux [10^(-17) erg/s/cm^2]
            # width of Gaussian emission line derived from *fixed* velocity dispersion.
            em_sig = vdisp * (emline_lambda[i_k] * (1.+gleg_s['z'][index][hasem])) / 299792.458 # this line of code is the main difference
            if not silent: 
                print('%s emission line width range: %f - %f' % (k, em_sig.min(), em_sig.max()))

            # normalization of the Gaussian
            A = em_lineflux/np.sqrt(2. * np.pi * em_sig**2)
            
            emline_flux[hasem] += A[:,None] * \
                    np.exp(-0.5*(np.tile(wave, n_hasem).reshape(n_hasem, npix) - emline_lambda[i_k])**2/em_sig[:,None]**2)
        return emline_flux 

    def _make_galaxy_templates(self, input_meta, emflux=None, mag_em=None, nocolorcuts=True, restframe=False, silent=True):
        ''' a streamlined version of desisim.template.GALAXY.make_galaxy_templates
        for BGS galaxies that takes in emission line flux from self.EmissionLineFlux 
        as an optional input. Particular care was taken to figure out the flux 
        calibration. 

        flux calibration implementation 
        --------------------------------------
        The source spectra for the `feasiBGS` is derived from the 
        combination of `desisim.templates.BGS.make_templates` spectra 
        combined with GAMA emission line data:
        $$s(\lambda) = c(\lambda) + e(\lambda) $$
        $c(\lambda)$ is the template spectra from 
        `desisim.templates.BGS.make_templates` and $e(\lambda)$ is the 
        emission line flux from GAMA data. However, there are some 
        complications caused by the fact that $s(\lambda)$ has to be 
        properly normalized.

        Since $e(\lambda)$ is derived from $s_\mathrm{GAMA}(\lambda)$, 
        which has the flux calibration of above, we first calibrate 
        $s(\lambda)$ to the $r_\mathrm{SDSS}$ --- i.e. replicate the GAMA 
        flux calibration:
        $$s'(\lambda) = f \times c(\lambda) + e(\lambda)$$
        where
        $$f = \frac{10^{-0.4\times r_\mathrm{SDSS}} - \int e(\lambda) b_r(\lambda) d\lambda}
        {\int c(\lambda) b_r(\lambda) d\lambda}$$

        Then flux calibrate $s'(\lambda)$ to the desired $r$-band apparent 
        magnitude.
        '''
        if emflux is not None and mag_em is None: 
            raise ValueError('To do flux calibration appropriately, please include apparent magnitude that corresponds to the flux calibration of the emission lines') 
        npix = len(self.basewave)
    
        # unpack metadata table.
        templateseed = input_meta['SEED'].data
        rand = np.random.RandomState(templateseed[0])

        redshift = input_meta['REDSHIFT'].data
        mag = input_meta['MAG'].data
        vdisp = input_meta['VDISP'].data
        assert input_meta['VDISP'].data.min() > 0

        nmodel = len(input_meta)
        templateid = input_meta['TEMPLATEID'].data

        # Precompute the velocity dispersion convolution matrix for each unique
        # value of vdisp.
        blurmatrix = self._blurmatrix(vdisp)

        # Optionally initialize the emission-line objects and line-ratios.
        d4000 = self.basemeta['D4000']
        
        # input rest-frame emission line flux 
        if emflux is None: 
            emflux = np.zeros((nmodel, npix))
        else: 
            # check dimensions of emission line flux 
            assert emflux.shape[0] == nmodel 
            assert emflux.shape[1] == npix 
            # emission line flux from EmissionLineFlux is in units of 10^(-17)erg/s/cm^2/A
            emflux *= 1e-17

        # Build each spectrum in turn.
        outflux = np.zeros([nmodel, len(self.wave)]) # [erg/s/cm2/A]

        magnorm_flag = np.ones(nmodel).astype(bool) 
        for ii in range(nmodel):
            templaterand = np.random.RandomState(templateseed[ii])

            zwave = self.basewave.astype(float) * (1.0 + redshift[ii])

            restflux = self.baseflux[templateid[ii]] #+ emflux[ii]
    
            # normalize spectra to match input apparent magnitude
            maggies = self.decamwise.get_ab_maggies(restflux, zwave, mask_invalid=True)
            emmaggies = self.decamwise.get_ab_maggies(emflux[ii], zwave, mask_invalid=True)
            if self.normfilter_south in self.decamwise.names:
                normmaggies = np.array(maggies[self.normfilter_south])
                norm_emmaggies = np.array(emmaggies[self.normfilter_south])
            else:
                normmaggies = np.array(self.normfilt.get_ab_maggies(
                    restflux, zwave, mask_invalid=True)[self.normfilter_south])
                norm_emmaggies = np.array(self.normfilt.get_ab_maggies(
                    emflux, zwave, mask_invalid=True)[self.normfilter_south])

            # populate the output flux vector (suitably normalized) and metadata table, 
            # convolve with the velocity dispersion, resample, and finish up.  
            # Note that the emission lines already have the velocity dispersion
            # line-width.
            if mag_em is None: 
                magnorm = (10**(-0.4*mag[ii]) - norm_emmaggies) / normmaggies
                blurflux = ((blurmatrix[vdisp[ii]] * restflux) + emflux[ii]) * magnorm
                synthnano = dict()
                for key in maggies.columns:
                    synthnano[key] = 1E9 * maggies[key] * magnorm # nanomaggies
            else: 
                magnorm0 = (10**(-0.4*mag_em[ii]) - norm_emmaggies) / normmaggies
                if magnorm0[0] < 0.: 
                    # this really shouldn't happen if the GAMA spectrophoto calibration
                    # is done correctly, but the magnitude from gama emission line flux 
                    # alone is brighter than the photometric magnitude...
                    # but since it happens set template flux to 0 
                    magnorm0 = 0.
                    if not silent: 
                        print('--------------------') 
                        print('the %i th galaxy has brighter emission lines than photometry...' % ii)
                    magnorm_flag[ii] = False
                    continue 

                norm_restflux = restflux * magnorm0 + emflux[ii] 
                maggies1 = self.decamwise.get_ab_maggies(norm_restflux, zwave, mask_invalid=True)
                if self.normfilter_south in self.decamwise.names:
                    normmaggies1 = np.array(maggies1[self.normfilter_south])
                else:
                    normmaggies1 = np.array(self.normfilt.get_ab_maggies(
                        norm_restflux, zwave, mask_invalid=True)[self.normfilter_south])
                magnorm1 = 10**(-0.4*mag[ii]) / normmaggies1
                # we checked to make sure these are the same 
                #magnorm1 = 10**(-0.4*mag[ii]) / 10**(-0.4*mag_em[ii]) 

                blurflux = ((blurmatrix[vdisp[ii]] * restflux * magnorm0) + emflux[ii]) * magnorm1
                synthnano = dict()
                for key in maggies1.columns:
                    synthnano[key] = 1E9 * maggies1[key] * magnorm1 # nanomaggies

            outflux[ii, :] = resample_flux(self.wave, zwave, blurflux, extrapolate=True)

        return 1e17 * outflux, self.wave, magnorm_flag 

    def _blurmatrix(self, vdisp):
        """Pre-compute the blur_matrix as a dictionary keyed by each unique value of
        vdisp.

        """
        uvdisp = list(set(vdisp))

        blurmatrix = dict()
        for uvv in uvdisp:
            sigma = 1.0 + (self.basewave * uvv / LIGHT)
            blurmatrix[uvv] = pxs.gauss_blur_matrix(self.pixbound, sigma).astype('f4')

        return blurmatrix

    def _oldSpectra(self, r_mag, zred, vdisp, seed=None, templateid=None, silent=True):
        ''' ***DEFUNCT*** keeping it around for testing purposes
        Given r-band magnitude, redshift 
        '''
        np.random.seed(seed) # set random seed

        # initialize the templates once:
        self.bgs_templates = BGS(wave=self.wave, normfilter_south='decam2014-r') 
        #normfilter='sdss2010-r') # Need to generalize this!
        self.bgs_templates.normline = None # no emission lines!

        # meta data of 'mag', 'redshift', 'vdisp'
        input_meta = empty_metatable(nmodel=len(r_mag), objtype='BGS')
        input_meta['SEED'] = np.random.randint(2**32, size=len(r_mag)) 
        input_meta['MAG'] = r_mag # r band apparent magnitude
        input_meta['REDSHIFT'] = zred # redshift
        input_meta['VDISP'] = vdisp 
        input_meta['TEMPLATEID'] = templateid

        flux, _, meta = self.bgs_templates.make_templates(input_meta=input_meta,
                                                          nocolorcuts=True, 
                                                          novdisp=False,
                                                          verbose=(not silent))
        return flux, self.wave, meta

    def _oldaddEmissionLines(self, wave, flux, gama_data, gama_indices, dr_gama=3, silent=True): 
        '''***DEFUNCT*** keeping it around for testing purposes
        add emission lines to spectra
        '''
        assert flux.shape[0] == len(gama_indices)
        if dr_gama != 3: raise ValueError("Only supported for GAMA DR3") 
        _flux = flux.copy() 
        # emission lines
        emline_keys = ['oiib', 'oiir', 'hb',  'oiiib', 'oiiir', 'oib', 'oir', 'niib', 'ha', 'niir', 'siib', 'siir']
        emline_lambda = [3726., 3729., 4861., 4959., 5007., 6300., 6364., 6548., 6563., 6583., 6717., 6731.]
    
        # gama spectra data
        gama_sdata = gama_data['gama-spec']

        # redshifts 
        z_gama = gama_data['gama-spec']['z'][gama_indices]

        # loop through emission lines and add them on! 
        for i_k, k in enumerate(emline_keys): 
            # galaxies with measured emission line (DR3 allows for negative emission lines...) 
            hasem = (gama_sdata[k+'_flux'][gama_indices] > 0.)
            n_hasem = np.sum(hasem) 
            if n_hasem == 0: 
                if not silent: print('no galaxies with emission line %s' % k) 
                continue
            
            em_lineflux = gama_sdata[k+'_flux'][gama_indices][hasem] # line flux [10^(-17) erg/s/cm^2]
            # width of Gaussian emission line 
            em_sig = gama_sdata['sig_'+k][gama_indices][hasem] # Angstrom
            assert em_sig.min() > 0. 

            # normalization of the Gaussian
            A = em_lineflux/np.sqrt(2. * np.pi * em_sig**2)

            lambda_eml_red = emline_lambda[i_k] * (1 + z_gama[hasem]) 

            emline_flux = A[:,None] * \
                    np.exp(-0.5*(np.tile(wave, n_hasem).reshape(n_hasem, len(wave)) - lambda_eml_red[:,None])**2/em_sig[:,None]**2)
            _flux[hasem] += emline_flux 

        return wave, _flux 


class fakeDESIspec(object): 
    ''' simulate exposure for DESI spectrograph. 
    This is sort of a giant wrapper for specsim. 
    '''
    def __init__(self): 
        pass

    def simExposure(self, wave, flux, airmass=1.0, exptime=1000, seeing=1.1, 
            seed=1, skyerr=0.0, Isky=None, nonoise=False, dwave_out=0.8, filename=None): 
        ''' simulate exposure for input source flux(wavelength). keyword arguments (airmass, seeing) 
        specify a number of observational conditions. These are used to calculate the extinction
        factor. The sky surface brightness is dictated by `skyconditions` kwarg. 
        '''
        nspec, _ = flux.shape # number of spectra 

        # observation conditions
        obvs_dict = dict(
                AIRMASS=airmass, 
                EXPTIME=exptime, # s 
                SEEING=seeing)   # arc sec

        tileid  = 0
        dateobs = time.gmtime()
        night   = get_night(utc=dateobs)
        
        frame_fibermap = desispec.io.fibermap.empty_fibermap(nspec) # empty fibermap ndarray
        frame_fibermap.meta["FLAVOR"] = "custom"
        frame_fibermap.meta["NIGHT"] = night
        frame_fibermap.meta["EXPID"] = 0 
        # add DESI_TARGET
        tm = desitarget.targetmask.desi_mask
        frame_fibermap['DESI_TARGET'] = tm.BGS_ANY
        frame_fibermap['TARGETID'] =  np.arange(nspec).astype(int)
    
        # spectra fibermap has two extra fields : night and expid
        # This would be cleaner if desispec would provide the spectra equivalent
        # of desispec.io.empty_fibermap()
        spectra_fibermap = desispec.io.empty_fibermap(nspec)
        spectra_fibermap = desispec.io.util.add_columns(spectra_fibermap,
                           ['NIGHT', 'EXPID', 'TILEID'],
                           [np.int32(night), np.int32(0), np.int32(tileid)],
                           )
        for s in range(nspec):
            for tp in frame_fibermap.dtype.fields:
                spectra_fibermap[s][tp] = frame_fibermap[s][tp]

        # ccd wavelength limit 
        params = desimodel.io.load_desiparams()
        wavemin = params['ccd']['b']['wavemin']
        wavemax = params['ccd']['z']['wavemax']

        if wave[0] > wavemin or wave[-1] < wavemax:
            print('%f > %f or %f < %f' % (wave[0], wavemin, wave[-1], wavemax))
            raise ValueError

        wlim = (wavemin <= wave) & (wave <= wavemax) # wavelength limit 
        wave = wave[wlim]*u.Angstrom

        flux_unit = 1e-17 * u.erg / (u.Angstrom * u.s * u.cm ** 2 )
        flux = flux[:,wlim]*flux_unit

        sim = self._simulate_spectra(wave, flux, fibermap=frame_fibermap, Isky=Isky, 
                obsconditions=obvs_dict, redshift=None, dwave_out=dwave_out,
                seed=seed, psfconvolve=True)

        for table in sim.camera_output :
            tbl = table['num_source_electrons']
            if tbl.min() < 0.: 
                neg = (tbl.min(axis=0) < 0) 
                print('--------------------') 
                print('the following galaxies have negative num_source_electrons')
                print(np.arange(tbl.shape[1])[neg])
                table['num_source_electrons'][:,neg] = 0. #np.zeros(tbl.shape[0])

        # put in random noise 
        random_state = np.random.RandomState(seed)
        if not nonoise: 
            sim.generate_random_noise(random_state)

        scale=1e17
        specdata = None

        resolution={}
        for camera in sim.instrument.cameras:
            R = Resolution(camera.get_output_resolution_matrix())
            resolution[camera.name] = np.tile(R.to_fits_array(), [nspec, 1, 1])

        # imperfect sky subtraction    
        skyscale = skyerr * random_state.normal(size=sim.num_fibers)

        for table in sim.camera_output :
            wave = table['wavelength'].astype(float)
            flux = (table['observed_flux']+table['random_noise_electrons']*table['flux_calibration']).T.astype(float)

            # imperfect sky subtraction 
            if np.any(skyscale):
                flux += ((table['num_sky_electrons']*skyscale)*table['flux_calibration']).T.astype(float)
            
            ivar = table['flux_inverse_variance'].T.astype(float)
            
            band  = table.meta['name'].strip()[0]
            
            flux = flux * scale
            ivar = ivar / scale**2
            mask  = np.zeros(flux.shape).astype(int)
            
            spec = Spectra([band], {band : wave}, {band : flux}, {band : ivar}, 
                           resolution_data={band : resolution[band]}, 
                           mask={band : mask}, 
                           fibermap=spectra_fibermap, 
                           meta=None,
                           single=True)
            if specdata is None :
                specdata = spec
            else:
                specdata.update(spec)
        if filename is None: 
            return specdata  
        else: 
            desispec.io.write_spectra(filename, specdata)
            return specdata  

    def _simulate_spectra(self, wave, flux, fibermap=None, Isky=None, obsconditions=None, 
            redshift=None, dwave_out=None, seed=None, psfconvolve=True, specsim_config_file = "desi"):
        ''' A more streamlined BGS version of the method `desisim.simexp.simulate_spectra`, which 
        simulates an exposure 

        :param wave: 
            1D wavelengths in Angstroms

        :param flux: 
            2D[nspec,nwave] flux in 1e-17 erg/s/cm2/Angstrom or astropy Quantity with flux units

        :param fibermap: (optional) 
            table from fiberassign or fibermap; uses X/YFOCAL_DESIGN, TARGETID, DESI_TARGET

        :param Isky: (optional) 
            2 element array [wave, Isky]  

        :param obsconditions:
            observation metadata including: 
            SEEING (arcsec), EXPTIME (sec), AIRMASS, MOONFRAC (0-1), MOONALT (deg), MOONSEP (deg)

        :param redshift: 
            list/array with each index being the redshifts for that target

        :param seed: 
            random seed

        :param psfconvolve: 
            passed to simspec.simulator.Simulator camera_output.
            If True, convolve with PSF and include per-camera outputs. (default: True) 

        :param specsim_config_file:
             path to DESI instrument config file.
            default is desi config in specsim package.

        Returns a specsim.simulator.Simulator object
        '''
        # Input cosmology to calculate the angular diameter distance of the galaxy's redshift
        LCDM = FlatLambdaCDM(H0=70, Om0=0.3)
        ang_diam_dist = LCDM.angular_diameter_distance
        
        random_state = np.random.RandomState(seed)

        nspec, nwave = flux.shape

        # Generate specsim config object for a given wavelength grid
        config = desisim.simexp._specsim_config_for_wave(wave.to('Angstrom').value, 
                dwave_out=dwave_out, specsim_config_file=specsim_config_file)

        # if no sky surface brightness is specified, use dark sky 
        surface_brightness_dict = config.load_table(config.atmosphere.sky, 'surface_brightness', as_dict=True)
        # dark sky surface brightness 
        sky_surface_brightness = surface_brightness_dict['dark'] 

        # sky surface brightness  
        if Isky is not None: 
            wave_sky, bright_sky = Isky[0], Isky[1] 
            sky_surface_brightness = np.interp(wave.to_value(), wave_sky, bright_sky) * sky_surface_brightness.unit
        
        #- Create simulator
        desi = SimulatorHacked(config, num_fibers=nspec, camera_output=psfconvolve)

        if obsconditions is None: raise ValueError

        desi.atmosphere.seeing_fwhm_ref = obsconditions['SEEING'] * u.arcsec
        desi.observation.exposure_time = obsconditions['EXPTIME'] * u.s
        desi.atmosphere.airmass = obsconditions['AIRMASS']

        #- Set fiber locations from meta Table or default fiberpos
        fiberpos = desimodel.io.load_fiberpos()
        if len(fiberpos) != len(fibermap):
            ii = np.in1d(fiberpos['FIBER'], fibermap['FIBER'])
            fiberpos = fiberpos[ii]

        #- Extract fiber locations from meta Table -> xy[nspec,2]
        assert np.all(fibermap['FIBER'] == fiberpos['FIBER'][0:nspec])
        if 'XFOCAL_DESIGN' in fibermap.dtype.names:
            xy = np.vstack([fibermap['XFOCAL_DESIGN'], fibermap['YFOCAL_DESIGN']]).T * u.mm
        elif 'X' in fibermap.dtype.names:
            xy = np.vstack([fibermap['X'], fibermap['Y']]).T * u.mm
        else:
            xy = np.vstack([fiberpos['X'], fiberpos['Y']]).T * u.mm

        if 'TARGETID' in fibermap.dtype.names:
            unassigned = (fibermap['TARGETID'] == -1)
            if np.any(unassigned):
                #- see https://github.com/astropy/astropy/issues/5961
                #- for the units -> array -> units trick
                xy[unassigned,0] = np.asarray(fiberpos['X'][unassigned], dtype=xy.dtype) * u.mm
                xy[unassigned,1] = np.asarray(fiberpos['Y'][unassigned], dtype=xy.dtype) * u.mm
            
        randstate = np.random.get_state()
        np.random.seed(seed)
        desi.simulate(sky_surface_brightness, source_fluxes=flux, focal_positions=xy)
        np.random.set_state(randstate)
        return desi


class SimulatorHacked(Simulator): 
    def __init__(self, config, num_fibers=2, camera_output=True, verbose=False):
        super().__init__(config, num_fibers=num_fibers, camera_output=camera_output, 
                verbose=verbose) 

    def simulate(self, sky_surface_brightness, sky_positions=None, focal_positions=None,
            source_fluxes=None):
        ''' The main function that I'm going to hack. 
        
        notes
        ----- 
        * calibration feature removed
        * fiberloss calculation also removed #commented out 
        '''
        # Get references to our results columns. Since table rows index
        # wavelength, the shape of each column is (nwlen, nfiber) and
        # therefore some transposes are necessary to match with the shape
        # (nfiber, nwlen) of source_fluxes and fiber_acceptance_fraction,
        # and before calling the camera downsample() and apply_resolution()
        # methods (which expect wavelength in the last index).
        wavelength = self.simulated['wavelength']
        source_flux = self.simulated['source_flux']
        fiberloss = self.simulated['fiberloss']
        source_fiber_flux = self.simulated['source_fiber_flux']
        sky_fiber_flux = self.simulated['sky_fiber_flux']
        num_source_photons = self.simulated['num_source_photons']
        num_sky_photons = self.simulated['num_sky_photons']
        nwlen = len(wavelength)

        # Position each fiber.
        assert focal_positions is not None
        if len(focal_positions) != self.num_fibers:
            raise ValueError(
                'Expected {0:d} focal_positions.'.format(self.num_fibers))
        try:
            focal_positions = focal_positions.to(u.mm)
        except (AttributeError, u.UnitConversionError):
            raise ValueError('Invalid units for focal_positions.')
        self.focal_x, self.focal_y = focal_positions.T

        # Check that all sources are within the field of view.
        focal_r = np.sqrt(self.focal_x ** 2 + self.focal_y ** 2)
        if np.any(focal_r > self.instrument.field_radius):
            raise RuntimeError(
                'A source is located outside the field of view: r > {0:.1f}'
                .format(self.instrument.field_radius))

        # Calculate the on-sky fiber areas at each focal-plane location.
        radial_fiber_size = (
            0.5 * self.instrument.fiber_diameter /
            self.instrument.radial_scale(focal_r))
        azimuthal_fiber_size = (
            0.5 * self.instrument.fiber_diameter /
            self.instrument.azimuthal_scale(focal_r))
        self.fiber_area = np.pi * radial_fiber_size * azimuthal_fiber_size

        # Get the source fluxes incident on the atmosphere.
        try:
            source_flux[:] = source_fluxes.to(source_flux.unit).T
        except AttributeError:
            raise ValueError('Missing units for source_fluxes.')
        except u.UnitConversionError:
            raise ValueError('Invalid units for source_fluxes.')

        # Calculate the source flux entering a fiber.
        source_fiber_flux[:] = (
            source_flux *
            self.atmosphere.extinction[:, np.newaxis] #* fiberloss
            ).to(source_fiber_flux.unit)

        # check that input sky_surface_brightness is the same size 
        # as the source_flux 
        if source_flux.shape[0] != sky_surface_brightness.shape[0]: 
            print(source_flux.shape)
            print(sky_surface_brightness.shape)
            raise ValueError

        # Calculate the sky flux entering a fiber from input 
        # sky surface_brightness  
        sky_fiber_flux[:] = (
            sky_surface_brightness[:, np.newaxis] *
            self.fiber_area
            ).to(sky_fiber_flux.unit)

        # Calculate the calibration from constant unit source flux above
        # the atmosphere to number of source photons entering the fiber.
        # We use this below to calculate the flux inverse variance in
        # each camera.
        source_flux_to_photons = (
            self.atmosphere.extinction[:, np.newaxis] * # fiberloss *
            self.instrument.photons_per_bin[:, np.newaxis] *
            self.observation.exposure_time
            ).to(source_flux.unit ** -1).value

        # Calculate the mean number of source photons entering the fiber
        # per simulation bin.
        num_source_photons[:] = (
            source_fiber_flux *
            self.instrument.photons_per_bin[:, np.newaxis] *
            self.observation.exposure_time
            ).to(1).value

        # Calculate the mean number of sky photons entering the fiber
        # per simulation bin.
        num_sky_photons[:] = (
            sky_fiber_flux *
            self.instrument.photons_per_bin[:, np.newaxis] *
            self.observation.exposure_time
            ).to(1).value

        # Calculate the high-resolution inputs to each camera.
        for camera in self.instrument.cameras:
            # Get references to this camera's columns.
            num_source_electrons = self.simulated[
                'num_source_electrons_{0}'.format(camera.name)]
            num_sky_electrons = self.simulated[
                'num_sky_electrons_{0}'.format(camera.name)]
            num_dark_electrons = self.simulated[
                'num_dark_electrons_{0}'.format(camera.name)]
            read_noise_electrons = self.simulated[
                'read_noise_electrons_{0}'.format(camera.name)]

            # Calculate the mean number of source electrons detected in the CCD
            # without any resolution applied.
            num_source_electrons[:] = (
                num_source_photons * camera.throughput[:, np.newaxis])

            # Calculate the mean number of sky electrons detected in the CCD
            # without any resolution applied.
            num_sky_electrons[:] = (
                num_sky_photons * camera.throughput[:, np.newaxis])

            # Calculate the mean number of dark current electrons in the CCD.
            num_dark_electrons[:] = (
                camera.dark_current_per_bin[:, np.newaxis] *
                self.observation.exposure_time).to(u.electron).value

            # Copy the read noise in units of electrons.
            read_noise_electrons[:] = (
                camera.read_noise_per_bin[:, np.newaxis].to(u.electron).value)

        # Loop over cameras to calculate their individual responses
        # with resolution applied and downsampling to output pixels.
        for output, camera in zip(self.camera_output, self.instrument.cameras):

            # Get references to this camera's columns.
            num_source_electrons = self.simulated[
                'num_source_electrons_{0}'.format(camera.name)]
            num_sky_electrons = self.simulated[
                'num_sky_electrons_{0}'.format(camera.name)]
            num_dark_electrons = self.simulated[
                'num_dark_electrons_{0}'.format(camera.name)]
            read_noise_electrons = self.simulated[
                'read_noise_electrons_{0}'.format(camera.name)]

            # Apply resolution to the source and sky detected electrons on
            # the high-resolution grid.
            num_source_electrons[:] = camera.apply_resolution(
                num_source_electrons)
            num_sky_electrons[:] = camera.apply_resolution(
                num_sky_electrons)

            # Calculate the corresponding downsampled output quantities.
            output['num_source_electrons'][:] = (
                camera.downsample(num_source_electrons))
            output['num_sky_electrons'][:] = (
                camera.downsample(num_sky_electrons))
            output['num_dark_electrons'][:] = (
                camera.downsample(num_dark_electrons))
            output['read_noise_electrons'][:] = np.sqrt(
                camera.downsample(read_noise_electrons ** 2))
            output['variance_electrons'][:] = (
                output['num_source_electrons'] +
                output['num_sky_electrons'] +
                output['num_dark_electrons'] +
                output['read_noise_electrons'] ** 2)
            mean_electrons = (output['num_source_electrons'] +
                    output['num_sky_electrons'] +
                    output['num_dark_electrons'])
            if mean_electrons.min() < 0.: 
                print(output['num_source_electrons'])
                print(output['num_sky_electrons'])
                print(output['num_dark_electrons'])

            # Calculate the effective calibration from detected electrons to
            # source flux above the atmosphere, downsampled to output pixels.
            output['flux_calibration'][:] = 1.0 / camera.downsample(
                camera.apply_resolution(
                    source_flux_to_photons * camera.throughput.reshape(-1, 1)))

            # Calculate the calibrated flux in this camera.
            output['observed_flux'][:] = (
                output['flux_calibration'] * output['num_source_electrons'])

            # Calculate the corresponding flux inverse variance.
            output['flux_inverse_variance'][:] = (
                output['flux_calibration'] ** -2 *
                output['variance_electrons'] ** -1)

            # Zero our random noise realization column.
            output['random_noise_electrons'][:] = 0.
        return None 
