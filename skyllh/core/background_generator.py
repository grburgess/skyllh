# -*- coding: utf-8 -*-

from skyllh.core.background_generation import BackgroundGenerationMethod
from skyllh.core.dataset import Dataset, DatasetData
from skyllh.core.py import issequenceof
from skyllh.core.random import RandomStateService


class BackgroundGenerator(object):
    """This is the general background generator class, which provides a method
    to generate background events. It does not depend on the detector or
    background hypothesis. These dependencies are out-sourced to a class derived
    from the BackgroundGenerationMethod class.
    """
    def __init__(self, bkg_gen_method, dataset_list, data_list):
        """Constructs a new background generator instance.

        Parameters
        ----------
        bkg_gen_method : instance of BackgroundGenerationMethod
            The background event generation method, which should be used to
            generate events.
        dataset_list : list of Dataset instances
            The list of Dataset instances for which background events should get
            generated for.
        data_list : list of DatasetData instances
            The list of DatasetData instances holding the actual data of each
            dataset. The order must match the order of ``dataset_list``.
        """
        super(BackgroundGenerator, self).__init__()

        self.bkg_gen_method = bkg_gen_method
        self.dataset_list = dataset_list
        self.data_list = data_list

    @property
    def bkg_gen_method(self):
        """The instance of BackgroundGenerationMethod which should be used to
        generate background events.
        """
        return self._bkg_gen_method
    @bkg_gen_method.setter
    def bkg_gen_method(self, method):
        if(not isinstance(method, BackgroundGenerationMethod)):
            raise TypeError('The bkg_gen_method property must be an instance '
                'of BackgroundGenerationMethod!')
        self._bkg_gen_method = method

    @property
    def dataset_list(self):
        """The list of Dataset instances for which background events should get
        generated for.
        """
        return self._dataset_list
    @dataset_list.setter
    def dataset_list(self, datasets):
        if(not issequenceof(datasets, Dataset)):
            raise TypeError('The dataset_list property must be a sequence of '
                'Dataset instances!')
        self._dataset_list = list(datasets)

    @property
    def data_list(self):
        """The list of DatasetData instances holding the actual data of each
        dataset. The order must match the order of the ``dataset_list``
        property.
        """
        return self._data_list
    @data_list.setter
    def data_list(self, datas):
        if(not issequenceof(datas, DatasetData)):
            raise TypeError('The data_list property must be a sequence of '
                'DatasetData instances!')
        self._data_list = datas

    def generate_background_events(self, rss, dataset_idx, mean, **kwargs):
        """Generates a mean number of background events for the given dataset.

        Parameters
        ----------
        rss : instance of RandomStateService
            The instance of RandomStateService that should be used to generate
            random numbers from.
        dataset_idx : int
            The index of the dataset for which background events should get
            generated for.
        mean : float
            The mean number of background events to generate.
        **kwargs
            Additional keyword arguments, which will be passed to the
            ``generate_events`` method of the background generation method
            instance.

        Returns
        -------
        bkg_events : numpy record array
            The numpy record arrays holding the generated background events.
        """
        ds = self._dataset_list[dataset_idx]
        data = self._data_list[dataset_idx]

        bkg_events = self._bkg_gen_method.generate_events(rss, ds, data, mean, **kwargs)

        return bkg_events