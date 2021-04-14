# -*- coding: utf-8 -*-

"""The ``signalpdf`` module contains possible signal PDF models for the
likelihood function.
"""

import numpy as np

from skyllh.core import display
from skyllh.core.py import (
    classname,
    issequenceof
)
from skyllh.core.livetime import Livetime
from skyllh.core.pdf import (
    PDFAxis,
    IsSignalPDF,
    MultiDimGridPDF,
    MultiDimGridPDFSet,
    NDPhotosplinePDF,
    SpatialPDF,
    TimePDF
)
from skyllh.core.source_hypothesis import SourceHypoGroupManager
from skyllh.physics.source import PointLikeSource
from skyllh.physics.flux_profile import TimeFluxProfile


class GaussianPSFPointLikeSourceSignalSpatialPDF(SpatialPDF, IsSignalPDF):
    """This spatial signal PDF model describes the spatial PDF for a point
    source smeared with a 2D gaussian point-spread-function (PSF).
    Mathematically, it's the convolution of a point in the sky, i.e. the source
    location, with the PSF. The result of this convolution has the gaussian form

        1/(2*\pi*\sigma^2) * exp(-1/2*(r / \sigma)**2),

    where \sigma is the spatial uncertainty of the event and r the distance on
    the sphere between the source and the data event.

    This PDF requires the `src_array` data field, that is numpy record ndarray
    with the data fields `ra` and `dec` holding the right-ascention and
    declination of the point-like sources, respectively.
    """

    def __init__(self, ra_range=None, dec_range=None):
        """Creates a new spatial signal PDF for point-like sources with a
        gaussian point-spread-function (PSF).

        Parameters
        ----------
        ra_range : 2-element tuple | None
            The range in right-ascention this spatial PDF is valid for.
            If set to None, the range (0, 2pi) is used.
        dec_range : 2-element tuple | None
            The range in declination this spatial PDF is valid for.
            If set to None, the range (-pi/2, +pi/2) is used.
        """
        if(ra_range is None):
            ra_range = (0, 2*np.pi)
        if(dec_range is None):
            dec_range = (-np.pi/2, np.pi/2)

        super(GaussianPSFPointLikeSourceSignalSpatialPDF, self).__init__(
            ra_range=ra_range,
            dec_range=dec_range)

    def get_prob(self, tdm, fitparams=None, tl=None):
        """Calculates the spatial signal probability of each event for all given
        sources.

        Parameters
        ----------
        tdm : instance of TrialDataManager
            The TrialDataManager instance holding the trial event data for which
            to calculate the PDF values. The following data fields need to be
            present:

            'src_array' : numpy record ndarray
                The numpy record ndarray with the following data fields:

                `ra`: float
                    The right-ascention of the point-like source.
                `dec`: float
                    The declination of the point-like source.

            'ra' : float
                The right-ascention in radian of the data event.
            'dec' : float
                The declination in radian of the data event.
            'ang_err': float
                The reconstruction uncertainty in radian of the data event.
        fitparams : None
            Unused interface argument.
        tl : TimeLord instance | None
            The optional TimeLord instance to use for measuring timing
            information.

        Returns
        -------
        prob : (N_sources,N_events) shaped 2D ndarray
            The ndarray holding the spatial signal probability on the sphere for
            each source and event.
        """
        get_data = tdm.get_data

        ra = get_data('ra')
        dec = get_data('dec')
        sigma = get_data('ang_err')

        # Make the source position angles two-dimensional so the PDF value can
        # be calculated via numpy broadcasting automatically for several
        # sources. This is useful for stacking analyses.
        src_ra = get_data('src_array')['ra'][:, np.newaxis]
        src_dec = get_data('src_array')['dec'][:, np.newaxis]

        # Calculate the cosine of the distance of the source and the event on
        # the sphere.
        cos_r = np.cos(src_ra - ra) * np.cos(src_dec) * \
            np.cos(dec) + np.sin(src_dec) * np.sin(dec)

        # Handle possible floating precision errors.
        cos_r[cos_r < -1.] = -1.
        cos_r[cos_r > 1.] = 1.
        r = np.arccos(cos_r)

        prob = 0.5/(np.pi*sigma**2) * np.exp(-0.5*(r / sigma)**2)

        grads = np.array([], dtype=np.float)

        # The new interface returns the pdf only for a single source.
        return (prob[0], grads)


class SignalTimePDF(TimePDF, IsSignalPDF):
    """This class provides a time PDF class for a signal source. It consists of
    a Livetime instance and a TimeFluxProfile instance. Together they construct
    the actual signal time PDF, which has detector down-time taking into
    account.
    """

    def __init__(self, livetime, time_flux_profile):
        """Creates a new signal time PDF instance for a given time profile of
        the source.

        Parameters
        ----------
        livetime : Livetime instance
            An instance of Livetime, which provides the detector live-time
            information.
        time_flux_profile : TimeFluxProfile instance
            The time flux profile of the source.
        """
        super(SignalTimePDF, self).__init__()

        self.livetime = livetime
        self.time_flux_profile = time_flux_profile

        # Define the time axis with the time boundaries of the live-time.
        self.add_axis(PDFAxis(
            name='time',
            vmin=self._livetime.time_window[0],
            vmax=self._livetime.time_window[1]))

        # Get the total integral, I, of the time profile and the sum, S, of the
        # integrals for each detector on-time interval during the time profile,
        # in order to be able to rescale the time profile to unity with
        # overlapping detector off-times removed.
        (self._I, self._S) = self._calculate_time_flux_profile_I_and_S()

    @property
    def livetime(self):
        """The instance of Livetime, which provides the detector live-time
        information.
        """
        return self._livetime

    @livetime.setter
    def livetime(self, lt):
        if(not isinstance(lt, Livetime)):
            raise TypeError(
                'The livetime property must be an instance of Livetime!')
        self._livetime = lt

    @property
    def time_flux_profile(self):
        """The instance of TimeFluxProfile providing the (assumed) physical
        flux time profile of the source.
        """
        return self._time_flux_profile

    @time_flux_profile.setter
    def time_flux_profile(self, tfp):
        if(not isinstance(tfp, TimeFluxProfile)):
            raise TypeError(
                'The time_flux_profile property must be an instance of '
                'TimeFluxProfile!')
        self._time_flux_profile = tfp

    def __str__(self):
        """Pretty string representation of the signal time PDF.
        """
        s = '%s(\n' % (classname(self))
        s += ' '*display.INDENTATION_WIDTH + \
            'livetime = %s,\n' % (str(self._livetime))
        s += ' '*display.INDENTATION_WIDTH + \
            'time_flux_profile = %s\n' % (str(self._time_flux_profile))
        s += ')'
        return s

    def _calculate_time_flux_profile_I_and_S(self):
        """Calculates the total integral, I, of the time flux profile and the
        sum, S, of the time-flux-profile integrals during the detector on-time
        intervals.

        Returns
        -------
        I : float
            The total integral of the source time-profile.
        S : float
            The sum of the source time-profile integrals during the detector
            on-time intervals.
        """
        ontime_intervals = self._livetime.get_ontime_intervals_between(
            self._time_flux_profile.t_start, self._time_flux_profile.t_end)

        I = self._time_flux_profile.get_total_integral()
        S = np.sum(self._time_flux_profile.get_integral(
            ontime_intervals[:, 0], ontime_intervals[:, 1]))

        return (I, S)

    def assert_is_valid_for_trial_data(self, tdm):
        """Checks if the time PDF is valid for all the given trial data.
        It checks if the time of all events is within the defined time axis of
        the PDF.

        Parameters
        ----------
        tdm : TrialDataManager instance
            The TrialDataManager instance holding the trial data. The following
            data fields must exist:

            - 'time' : float
                The MJD time of the data event.

        Raises
        ------
        ValueError
            If some of the data is outside the time range of the PDF.
        """
        time_axis = self.get_axis('time')
        data_time = tdm.get_data('time')

        if(np.any((data_time < time_axis.vmin) |
                  (data_time > time_axis.vmax))):
            raise ValueError('Some data is outside the time range '
                '(%.3f, %.3f)!'%(time_axis.vmin, time_axis.vmax))

    def get_prob(self, tdm, params=None, tl=None):
        """Calculates the signal time probability of each event for the given
        set of signal time parameter values.

        Parameters
        ----------
        tdm : instance of TrialDataManager
            The instance of TrialDataManager holding the trial event data for
            which to calculate the PDF value. The following data fields must
            exist:

            - 'time' : float
                The MJD time of the event.
        params : dict | None
            The dictionary holding the signal time parameter values for which
            the signal time probability should be calculated.
            This can be ``Ǹone`` if the PDF that do not depend on any
            parameters.

        Returns
        -------
        prob : array of float
            The (N,)-shaped ndarray holding the probability for each event.
        """
        # Update the time-profile if its parameter values have changed and
        # recalculate self._I and self._S if an update was actually performed.
        if(params is not None):
            updated = self._time_flux_profile.set_params(params)
            if(updated):
                (self._I, self._S) = self._calculate_time_flux_profile_I_and_S()

        events_time = tdm.get_data('time')

        # Get a mask of the event times which fall inside a detector on-time
        # interval.
        on = self._livetime.is_on(events_time)

        # The sum of the on-time integrals of the time profile, S, will be zero
        # if the time flux profile is entirly during detector off-time.
        prob = np.zeros((tdm.n_selected_events,), dtype=np.float)
        if(self._S > 0):
            prob[on] = self._time_flux_profile(events_time[on]) / (
                self._I * self._S)

        return prob


class SignalMultiDimGridPDF(MultiDimGridPDF, IsSignalPDF):
    """This class provides a multi-dimensional signal PDF. The PDF is created
    from pre-calculated PDF data on a grid. The grid data is interpolated using
    a :class:`scipy.interpolate.RegularGridInterpolator` instance.
    """

    def __init__(self, axis_binnings, path_to_pdf_splinetable=None,
                 pdf_grid_data=None, norm_factor_func=None):
        """Creates a new signal PDF instance for a multi-dimensional PDF given
        as PDF values on a grid. The grid data is interpolated with a
        :class:`scipy.interpolate.RegularGridInterpolator` instance. As grid
        points the bin edges of the axis binning definitions are used.

        Parameters
        ----------
        axis_binnings : sequence of BinningDefinition
            The sequence of BinningDefinition instances defining the binning of
            the PDF axes. The name of each BinningDefinition instance defines
            the event field name that should be used for querying the PDF.
        path_to_pdf_splinetable : str
            The path to the file containing the spline table.
            The spline table contains a  pre-computed fit to pdf_grid_data.
        pdf_grid_data : n-dimensional numpy ndarray
            The n-dimensional numpy ndarray holding the PDF values at given grid
            points. The grid points must match the bin edges of the given
            BinningDefinition instances of the `axis_binnings` argument.
        norm_factor_func : callable | None
            The function that calculates a possible required normalization
            factor for the PDF value based on the event properties.
            The call signature of this function
            must be `__call__(pdf, events, fitparams)`, where `pdf` is this PDF
            instance, `events` is a numpy record ndarray holding the events for
            which to calculate the PDF values, and `fitparams` is a dictionary
            with the current fit parameter names and values.
        """
        super(SignalMultiDimGridPDF, self).__init__(
            axis_binnings=axis_binnings,
            path_to_pdf_splinetable=path_to_pdf_splinetable,
            pdf_grid_data=pdf_grid_data,
            norm_factor_func=norm_factor_func)


class SignalMultiDimGridPDFSet(MultiDimGridPDFSet, IsSignalPDF):
    """This class extends the MultiDimGridPDFSet PDF class to be a signal PDF.
    See the documentation of the :class:`skyllh.core.pdf.MultiDimGridPDFSet`
    class for what this PDF provides.
    """

    def __init__(self, param_set, param_grid_set, gridparams_pdfs,
                 interpolmethod=None, **kwargs):
        """Creates a new SignalMultiDimGridPDFSet instance, which holds a set of
        MultiDimGridPDF instances, one for each point of a parameter grid set.

        Parameters
        ----------
        param_set : Parameter instance | sequence of Parameter instances |
                    ParameterSet instance
            The set of parameters defining the model parameters of this PDF.
        param_grid_set : ParameterGrid instance | ParameterGridSet instance
            The set of ParameterGrid instances, which define the grid values of
            the model parameters, the given MultiDimGridPDF instances belong to.
        gridparams_pdfs : sequence of (dict, MultiDimGridPDF) tuples
            The sequence of 2-element tuples which define the mapping of grid
            values to PDF instances.
        interpolmethod : subclass of GridManifoldInterpolationMethod
            The class specifying the interpolation method. This must be a
            subclass of ``GridManifoldInterpolationMethod``.
            If set to None, the default grid manifold interpolation method
            ``Linear1DGridManifoldInterpolationMethod`` will be used.
        """
        super(SignalMultiDimGridPDFSet, self).__init__(
            param_set=param_set,
            param_grid_set=param_grid_set,
            gridparams_pdfs=gridparams_pdfs,
            interpolmethod=interpolmethod,
            **kwargs)


class SignalNDPhotosplinePDF(NDPhotosplinePDF, IsSignalPDF):
    """This class provides a multi-dimensional signal PDF created from a
    n-dimensional photospline fit. The photospline package is used to evaluate
    the PDF fit.
    """

    def __init__(
            self,
            axis_binnings,
            param_set,
            path_to_pdf_splinefit,
            norm_factor_func=None):
        """Creates a new signal PDF instance for a n-dimensional photospline PDF
        fit.

        Parameters
        ----------
        axis_binnings : BinningDefinition | sequence of BinningDefinition
            The sequence of BinningDefinition instances defining the binning of
            the PDF axes. The name of each BinningDefinition instance defines
            the event field name that should be used for querying the PDF.
        param_set : Parameter | ParameterSet
            The Parameter instance or ParameterSet instance defining the
            parameters of this PDF. The ParameterSet holds the information
            which parameters are fixed and which are floating (i.e. fitted).
        path_to_pdf_splinefit : str
            The path to the file containing the photospline fit.
        norm_factor_func : callable | None
            The function that calculates a possible required normalization
            factor for the PDF value based on the event properties.
            The call signature of this function must be
            `__call__(pdf, tdm, params)`, where `pdf` is this PDF
            instance, `tdm` is an instance of TrialDataManager holding the
            event data for which to calculate the PDF values, and `params` is a
            dictionary with the current parameter names and values.
        """
        super(SignalNDPhotosplinePDF, self).__init__(
            axis_binnings=axis_binnings,
            param_set=param_set,
            path_to_pdf_splinefit=path_to_pdf_splinefit,
            norm_factor_func=norm_factor_func
        )
