import optimize.data as optdata
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

class RVData(optdata.Data):
    
    def __init__(self, t, rv, rverr, instname, **kwargs):
        super().__init__(t, rv, yerr=rverr, mask=None, label=instname)
        for key in kwargs:
            setattr(self, key, kwargs[key])
        
    @property
    def t(self):
        return self.x
    
    @property
    def rv(self):
        return self.y
    
    @property
    def rverr(self):
        return self.yerr
    
    @property
    def instname(self):
        return self.label
    
    @property
    def wavelength(self):
        if hasattr(self, "wavelength"):
            return self.wavelength
        else:
            return None
        
    def __repr__(self):
        return "RVs from " + self.instname

class MixedRVData(optdata.MixedData):
    
    @property
    def instnames(self):
        return [d.instname for d in self.items()]

    @classmethod
    def from_radvel_file(cls, fname):
        """Constructs a new RV data object from a standard radvel csv file.

        Args:
            fname (str): The full path to the file.

        Returns:
            MixedRVData: The MixedRVData set.
        """
        data = cls()
        rvdf = pd.read_csv(fname, sep=',', comment='#')
        tel_vec_unq = rvdf.tel.unique()
        tel_vec = rvdf.tel.to_numpy().astype('<U50')
        t_all = rvdf.time.to_numpy()
        rv_all = rvdf.mnvel.to_numpy()
        rverr_all = rvdf.errvel.to_numpy()
        for tel in tel_vec_unq:
            inds = np.where(tel_vec == tel)[0]
            data[tel] = RVData(t_all[inds], rv_all[inds], rverr_all[inds], instname=tel)
        return data
    
    def make_tel_vec(self):
        tel_vec = np.array([], dtype='<U50')
        t_all = self.get_vec('x', sort=False)
        for instname in self:
            tel_vec = np.concatenate((tel_vec, np.full(len(self[instname].t), fill_value=instname, dtype='<U50')))
        ss = np.argsort(t_all)
        tel_vec = tel_vec[ss]
        return tel_vec
    
    def get_inds(self, label):
        tel_vec = self.make_tel_vec()
        inds = np.where(tel_vec == label)[0]
        return inds