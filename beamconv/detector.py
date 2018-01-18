import sys
import time
import warnings
import glob
import os
import inspect
import numpy as np
import tools

class Beam(object):
    '''
    A class representing detector centroid and beam information
    '''
    def __init__(self, az=0., el=0., polang=0., name=None,
         pol='A', btype='Gaussian', fwhm=None, lmax=700, mmax=None,
         dead=False, ghost=False, amplitude=1., po_file=None, 
         eg_file=None, cross_pol=True, deconv_q=True,
         normalize=True):
        '''
        Keyword arguments
        ---------
        az : float 
            Azimuthal location of detector relative to boresight
            in degrees (default : 0.)
        el : float 
            Elevation location of detector relative to boresight
            in degrees (default : 0.)
        polang : float (default: 0.)
            The polarization orientation of the beam/detector [deg]
        name : str (default: None)
            The callsign of this particular beam
        pol : str (default: A)
            The polarization callsign of the beam (A or B)
        dead : bool (default: False)
            True if the beam is dead (not functioning)
        btype : str (default: Gaussian)
            Type of detector spatial response model. Can be one of three
            Gaussian : A symmetric Gaussian beam, definied by centroids and FWHM
            Gaussian_map : A symmetric Gaussian, defined by centroids and a map
            EG       : An elliptical Gaussian
            PO       : A realistic beam based on optical simulations or beam maps
        fwhm : float 
            Detector beam FWHM in arcmin (default : 43)
        lmax : int
            Bandlimit beam. If None, use 1.4*2*pi/fwhm. (default : None)
        mmax : int 
            Azimuthal band-limit beam. If None, use lmax (default : None)
        ghost : bool
            Whether the beam is a ghost or not (default : False)
        amplitude : scalar
            Total throughput of beam, i.e. integral of beam over the sphere. 
            ( \int d\omega B(\omega) Y_00(\omega) \equiv amplitude ). This
            means that b00 = amplitude / sqrt(4 pi) (default : 1.)
        po_file : str, None
            Absolute or relative path to .npy file with blm array for the
            (unpolarized) Physical Optics beam (default : None)
        eg_file : str, None
            Absolute or relative path to .npy file with blm array for the
            (unpolarized) Elliptical Gaussian beam (default : None)
        cross_pol : bool
            Whether to use the cross-polar response of the beam (requires
            blm .npy file to be of shape (3,), containing blm, blmm2 and blmp2
            (default : True)
        deconv_q : bool
            Multiply loaded blm's by sqrt(4 pi / (2 ell + 1)) before 
            computing spin harmonic coefficients. Needed when using 
            blm that are true SH coeff. (default : True)
        normalize : bool 
            Normalize loaded up blm's such that 00 component is 1.
            Done after deconv_q operation if that option is set.
        '''

        self.az = az
        self.el = el
        self.polang = polang
        self.name = name
        self.pol = pol
        self.btype = btype
        self.dead = dead
        self.amplitude = amplitude
        self.po_file = po_file
        self.eg_file = eg_file
        self.cross_pol = cross_pol

        self.lmax = lmax           
        self.mmax = mmax
        self.fwhm = fwhm
        self.deconv_q = deconv_q
        self.normalize = normalize

        self.__ghost = ghost
        # ghosts are not allowed to have ghosts
        if not self.ghost:
            self.__ghosts = []
            self.ghost_count = 0

    @property
    def ghost(self):
        return self.__ghost

    @property
    def ghosts(self):
        return self.__ghosts

    @property
    def ghost_count(self):
        return self.__ghost_count

    @ghost_count.setter
    def ghost_count(self, count):
        if not self.ghost:
            self.__ghost_count = count
        else:
            raise ValueErrror("ghost cannot have ghost_count")

    @property
    def ghost_idx(self):
        '''
        If two ghosts share ghost_idx, they share blm
        '''
        return self.__ghost_idx

    @ghost_idx.setter
    def ghost_idx(self, val):
        if self.ghost:
            self.__ghost_idx = val
        else:
            raise ValueError("main beam cannot have ghost_idx")

    @property
    def dead(self):
        return self.__dead

    @dead.setter
    def dead(self, val):
        '''
        Make sure ghosts are also declared dead when main beam is
        '''
        self.__dead = val
        try:
            for ghost in self.ghosts:
                ghost.__dead = val
        except AttributeError:
            # instance is ghost
            pass

    @property
    def lmax(self):
        return self.__lmax
    
    @lmax.setter
    def lmax(self, val):
        '''
        Make sure lmax is >= 0 and defaults to something sensible
        '''
        if val is None and fwhm:
            # Going up to 1.4 naieve Nyquist frequency set by beam scale 
            self.__lmax = int(2 * np.pi / np.radians(self.fwhm/60.) * 1.4)
        else:
            self.__lmax = max(val, 0)

    @property
    def fwhm(self):
        return self.__fwhm

    @fwhm.setter
    def fwhm(self, val):
        '''
        Set beam fwhm. Returns absolute value of 
        input and returns 1.4 * 2 * pi / lmax if
        fwhm is None.        
        '''
        if not val and self.lmax:
            val = (1.4 * 2. * np.pi) / self.lmax
            self.__fwhm = np.degrees(val) * 60
        else:
            self.__fwhm = np.abs(val)
            
    @property
    def mmax(self):
        return self.__mmax

    @mmax.setter
    def mmax(self, mmax):
        '''
        Set mmax to lmax if not set        
        '''
        self.__mmax = min(i for i in [mmax, self.lmax] \
                              if i is not None)

    @property
    def blm(self):
        '''
        Get blm arrays by either creating them or 
        loading them (depending on `btype` attr.

        Notes
        -----
        If blm attribute is already initialized and 
        btype is changes, blm will not be updated,
        first delete blm attribute in that case.
        '''
        try:
            return self.__blm
        except AttributeError:

            if self.btype == 'Gaussian':
                self.gen_gaussian_blm()
                return self.__blm

            else:
                # NOTE, if blm's are direct map2alm resuls, use deconv_q

                if self.btype == 'PO':
                    self.load_blm(self.po_file, deconv_q=self.deconv_q,
                                  normalize=self.normalize)
                    return self.__blm

                elif self.btype == 'EG':
                    self.load_blm(self.eg_file, deconv_q=self.deconv_q, 
                                  normalize=self.normalize)
                    return self.__blm

                else:
                    raise ValueError("btype = {} not recognized".format(self.btype))

    @blm.setter
    def blm(self, val):
        self.__blm = val

    @blm.deleter
    def blm(self):
        del self.__blm

    def __str__(self):

        return "name   : {} \nbtype  : {} \nalive  : {} \nFWHM"\
            "   : {} arcmin \naz     : {} deg \nel     : {} deg "\
            "\npolang : {} deg\n".format(self.name, self.btype,
            str(not self.dead), self.fwhm, self.az, self.el,
            self.polang)

    def gen_gaussian_blm(self):
        '''
        Generate symmetric Gaussian beam coefficients
        (I and pol) using FWHM and lmax.

        Notes
        -----
        Harmonic coefficients are multiplied by factor
        sqrt(4 pi / (2 ell + 1)) and scaled by 
        `amplitude` attribute (see `Beam.__init__()`).
        '''
        
        blm = tools.gauss_blm(self.fwhm, self.lmax, pol=False)
        if self.amplitude != 1:
            blm *= self.amplitude
        blm = tools.get_copol_blm(blm, c2_fwhm=self.fwhm)

        self.btype = 'Gaussian'
        self.blm = blm

    def load_blm(self, filename, **kwargs):
        '''
        Load a .npy file containing with blm array(s), 
        and use array(s) to populate `blm` attribute.

        Arguments
        ---------
        filename : str
            Absolute or relative path to file

        Keyword arguments
        -----------------
        kwargs : {tools.get_copol_blm_opts}

        Notes
        -----
        Loaded blm are automatically scaled by given the `amplitude` 
        attribute.

        blm file can be rank 1 or 2. If rank is 1: array is blm and 
        blmm2 and blmp2 are created assuming only the co-polar response
        If rank is 2, shape has to be (3,), with blm, blmm2 and blmp2
        '''
        
        pname, ext = os.path.splitext(filename)
        if not ext:
            # assume .npy extension
            ext = '.npy'
        blm = np.load(os.path.join(pname+ext))
        blm = np.atleast_2d(blm)

        if blm.shape[0] == 3 and self.cross_pol:
            cross_pol = True
        else:
            cross_pol = False
            blm = blm[0]

        if cross_pol:
            # assume co- and cross-polar beams are provided
            # c2_fwhm has no meaning if cross-pol is known
            kwargs.pop('c2_fwhm', None)
            blm = tools.scale_blm(blm, **kwargs)
            
            if self.amplitude != 1:
                # scale beam if needed
                blm *= self.amplitude

            self.blm = blm[0], blm[1], blm[2]

        else:
            # assume co-polarized beam

            if self.amplitude != 1:
                # scale beam if needed
                blm *= self.amplitude

            # create spin \pm 2 components
            self.blm = tools.get_copol_blm(blm, **kwargs)

    def create_ghost(self, tag='ghost', **kwargs):
        '''
        Append a ghost Beam object to the `ghosts` attribute.
        This method will raise an error when called from a 
        ghost Beam object.

        Keyword Arguments
        -----------------
        tag : str
            Identifier string appended like <name>_<tag>
            where <name> is parent beam's name. If empty string,
            or None, just use parent Beam name. (default : ghost)            
        kwargs : {beam_opts}
        
        Notes
        ----
        Valid Keyword arguments are those accepted by 
        `Beam.__init__()` with the exception of `name`,
        which is ignored and `ghost`, which is always set.
        Unspecified kwargs are copied from parent beam.
        '''
        
        if self.ghost:
            raise RuntimeError('Ghost cannot have ghosts')

        parent_name = self.name
        kwargs.pop('name', None)
        if tag:
            if parent_name:
                name = parent_name + ('_' + tag)
            else:
                name = tag
        else:
            name = parent_name

        # mostly default to parent kwargs
        ghost_opts = dict(az=self.az,
                           el=self.el,
                           polang=self.polang,
                           name=name,
                           pol=self.pol,
                           btype=self.btype,
                           fwhm=self.fwhm,
                           dead=self.dead,                          
                           lmax=self.lmax,
                           mmax=self.mmax)

        # update options with specified kwargs
        ghost_opts.update(kwargs)
        ghost_opts.update(dict(ghost=True))
        ghost = Beam(**ghost_opts)

        # set ghost_idx
        ghost.ghost_idx = self.ghost_count
        self.ghost_count += 1

        self.ghosts.append(ghost)

    def reuse_blm(self, partner):
        '''
        Copy pointers to already initialized beam by
        another Beam instance. If both beams are 
        ghosts, beam takes partner's `ghost_idx`.

        Arguments
        ---------
        partner : Beam object
        '''
        
        if not isinstance(partner, Beam):
            raise TypeError('partner must be Beam object')

        if partner.ghost and self.ghost:
            self.ghost_idx = partner.ghost_idx

        self.blm = partner.blm
        self.btype = partner.btype
        self.lmax = partner.lmax
        self.mmax = partner.mmax
        self.amplitude = partner.amplitude

    def delete_blm(self, del_ghosts_blm=True):
        '''
        Remove the `blm` attribute of the object. Does the same
        for ghosts, if specified.

        Keyword arguments
        -----------------
        del_ghost_blm : bool
            If True, also remove blm attributes of all ghosts
            (default : True)
        '''

        try:
            del(self.blm)
        except AttributeError:
            # no blm attribute to begin with
            pass

        if any(self.ghosts) and del_ghosts_blm:
            for ghost in self.ghosts:
                try:
                    del(ghost.blm)
                except AttributeError:
                    pass

    def get_offsets(self):
        '''
        Return (unrotated) detector offsets. 
        
        Returns
        -------
        az : float
            Azimuth of offset in degrees
        el : float
            Elevation of offset in degrees
        polang : float 
            Polarization angle in degrees

        Notes
        -----
        Detector offsets are defined
        as the sequence Rz(polang), Ry(el), Rx(az). Rz is defined 
        as the rotation around the boresight by angle `polang`
        which is measured relative to the southern side of 
        the local meridian in a clockwise manner when looking 
        towards the sky (Rh rot.), (i.e. the `Healpix convention`). 
        Followed by Ry and Rx, which are rotations in elevation 
        and azimuth with respect to the local horizon and meridian.
        '''
        
        return self.az, self.el, self.polang
