# -*- coding: utf-8 -*-

import abc
import copy
import pickle
import os.path
import numpy as np
import sys

from skyllh.core.py import (
    classname,
    get_byte_size_prefix,
    getsizeof,
    issequence,
    issequenceof,
    range
)
from skyllh.core import display as dsp


# Define a file loader registry that holds the FileLoader classes for different
# file formats.
_FILE_LOADER_REG = dict()

def register_FileLoader(formats, fileloader_cls):
    """Registers the given file formats (file extensions) to the given
    FileLoader class.

    Parameters
    ----------
    formats : str | list of str
        The list of file name extensions that should be mapped to the FileLoader
        class.
    fileloader_cls : FileLoader
        The subclass of FileLoader that should be used for the given file
        formats.
    """
    if(isinstance(formats, str)):
        formats = [ formats ]
    if(not issequence(formats)):
        raise TypeError('The "formats" argument must be a sequence!')
    if(not issubclass(fileloader_cls, FileLoader)):
        raise TypeError('The "fileloader_cls" argument must be a subclass of FileLoader!')

    for fmt in formats:
        if(fmt in _FILE_LOADER_REG.keys()):
            raise KeyError('The format "%s" is already registered!'%(fmt))
        _FILE_LOADER_REG[fmt] = fileloader_cls

def create_FileLoader(pathfilenames, **kwargs):
    """Creates the appropriate FileLoader object for the given file names.
    It looks up the FileLoader class from the FileLoader registry for the
    file name extension of the first file name in the given list.

    Parameters
    ----------
    pathfilenames : str | sequence of str
        The sequence of fully qualified file names of the files that should be
        loaded.

    Additional Parameters
    ---------------------
    Additional parameters will be passed to the constructor method of the
    chosen FileLoader class.

    Returns
    -------
    fileloader : FileLoader
        The appropiate FileLoader instance for the given type of data files.
    """
    if(isinstance(pathfilenames, str)):
        pathfilenames = [pathfilenames]
    if(not issequenceof(pathfilenames, str)):
        raise TypeError('The pathfilenames argument must be a sequence of str!')

    # Sort the file names extensions with shorter extensions before longer ones
    # to support a format that is sub-string of another format.
    formats = sorted(_FILE_LOADER_REG.keys())
    for fmt in formats:
        l = len(fmt)
        if(pathfilenames[0][-l:].lower() == fmt.lower()):
            cls = _FILE_LOADER_REG[fmt]
            return cls(pathfilenames, **kwargs)

    raise RuntimeError('No FileLoader class is suitable to load the data file "%s"!'%(pathfilenames[0]))

def assert_file_exists(pathfilename):
    """Checks if the given file exists and raises a RuntimeError if it does
    not exist.
    """
    if(not os.path.isfile(pathfilename)):
        raise RuntimeError('The data file "%s" does not exist!'%(pathfilename))


class FileLoader:
    __metaclass__ = abc.ABCMeta

    def __init__(self, pathfilenames, **kwargs):
        """Initializes a new FileLoader instance.

        Parameters
        ----------
        pathfilenames : str | sequence of str
            The sequence of fully qualified file names of the data files that
            need to be loaded.
        """
        self.pathfilename_list = pathfilenames

    @property
    def pathfilename_list(self):
        """The list of fully qualified file names of the data files.
        """
        return self._pathfilename_list
    @pathfilename_list.setter
    def pathfilename_list(self, pathfilenames):
        if(isinstance(pathfilenames, str)):
            pathfilenames = [ pathfilenames ]
        if(not issequence(pathfilenames)):
            raise TypeError('The pathfilename_list property must be of type '
                'str or a sequence of type str!')
        self._pathfilename_list = list(pathfilenames)

    @abc.abstractmethod
    def load_data(self, **kwargs):
        """This method is supposed to load the data from the file.
        """
        pass


class NPYFileLoader(FileLoader):
    """The NPYFileLoader class provides the data loading functionality for
    numpy data files containing numpy arrays. It uses the ``numpy.load``
    function for loading the data and the numpy.append function to concatenate
    several data files.
    """
    def __init__(self, pathfilenames, **kwargs):
        super(NPYFileLoader, self).__init__(pathfilenames)

    def _load_file_memory_efficiently(
            self, pathfilename, keep_fields, dtype_convertions,
            dtype_convertion_except_fields):
        """Loads a single file in a memory efficient way.

        Parameters
        ----------
        pathfilename : str
            The fully qualified file name of the to-be-loaded file.

        Returns
        -------
        data : DataFieldRecordArray instance
            An instance of DataFieldRecordArray holding the data.
        """
        assert_file_exists(pathfilename)
        # Create a memory map into the data file. This loads the data only when
        # accessing the data.
        mmap_ndarray = np.load(pathfilename, mmap_mode='r')
        field_names = mmap_ndarray.dtype.names
        fname_to_fidx = dict(
            [ (fname,idx) for (idx,fname) in enumerate(field_names) ])
        dt_fields = mmap_ndarray.dtype.fields
        n_rows = mmap_ndarray.shape[0]

        data = dict()

        # Create empty arrays for each column of length n_rows.
        for fname in field_names:
            # Ignore fields that should not get kept.
            if((keep_fields is not None) and (fname not in keep_fields)):
                continue

            # Get the original data type of the field.
            dt = dt_fields[fname][0]
            # Convert the data type if requested.
            if((fname not in dtype_convertion_except_fields) and
               (dt in dtype_convertions)):
                dt = dtype_convertions[dt]

            data[fname] = np.empty((n_rows,), dtype=dt)

        # Loop through the rows of the recarray.
        bs = 4096
        for ridx in range(0, n_rows):
            row = mmap_ndarray[ridx]
            for fname in data.keys():
                fidx = fname_to_fidx[fname]
                data[fname][ridx] = row[fidx]

            # Reopen the data file after each given blocksize.
            if(ridx % bs == 0):
                del mmap_ndarray
                mmap_ndarray = np.load(pathfilename, mmap_mode='r')

        # Close the memory map file.
        del mmap_ndarray

        # Create a DataFieldRecordArray out of the dictionary.
        data = DataFieldRecordArray(data, copy=False)

        return data

    def _load_file_time_efficiently(
            self, pathfilename, keep_fields, dtype_convertions,
            dtype_convertion_except_fields):
        """Loads a single file in a time efficient way. This will load the data
        column-wise.
        """
        assert_file_exists(pathfilename)
        # Create a memory map into the data file. This loads the data only when
        # accessing the data.
        mmap_ndarray = np.load(pathfilename, mmap_mode='r')

        # Create a DataFieldRecordArray out of the memory mapped file. We need
        # to copy the data, otherwise we get read-only numpy arrays.
        data = DataFieldRecordArray(
            mmap_ndarray,
            keep_fields=keep_fields,
            dtype_convertions=dtype_convertions,
            dtype_convertion_except_fields=dtype_convertion_except_fields,
            copy=True)

        # Close the memory map file.
        del mmap_ndarray

        return data

    def load_data(
            self, keep_fields=None, dtype_convertions=None,
            dtype_convertion_except_fields=None, efficiency_mode=None):
        """Loads the data from the files specified through their fully qualified
        file names.

        Parameters
        ----------
        keep_fields : str | sequence of str | None
            Load the data into memory only for these data fields. If set to
            ``None``, all in-file-present data fields are loaded into memory.
        dtype_convertions : dict | None
            If not None, this dictionary defines how data fields of specific
            data types get converted into the specified data types.
            This can be used to use less memory.
        dtype_convertion_except_fields : str | sequence of str | None
            The sequence of field names whose data type should not get
            converted.
        efficiency_mode : str | None
            The efficiency mode the data should get loaded with. Possible values
            are:

                - 'memory':
                    The data will be load in a memory efficient way. This will
                    require more time, because all data records of a file will
                    be loaded sequentially.
                - 'time'
                    The data will be loaded in a time efficient way. This will
                    require more memory, because each data file gets loaded in
                    memory at once.

            The default value is ``'time'``. If set to ``None``, the default
            value will be used.

        Returns
        -------
        data : DataFieldRecordArray
            The DataFieldRecordArray holding the loaded data.

        Raises
        ------
        RuntimeError if a file does not exist.
        """
        if(keep_fields is not None):
            if(isinstance(keep_fields, str)):
                keep_fields = [ keep_fields ]
            elif(not issequenceof(keep_fields, str)):
                raise TypeError('The keep_fields argument must be None, an '
                    'instance of type str, or a sequence of instances of '
                    'type str!')

        if(dtype_convertions is None):
            dtype_convertions = dict()
        elif(not isinstance(dtype_convertions, dict)):
            raise TypeError('The dtype_convertions argument must be None, '
                'or an instance of dict!')

        if(dtype_convertion_except_fields is None):
            dtype_convertion_except_fields = []
        elif(isinstance(dtype_convertion_except_fields, str)):
            dtype_convertion_except_fields = [ dtype_convertion_except_fields ]
        elif(not issequenceof(dtype_convertion_except_fields, str)):
            raise TypeError('The dtype_convertion_except_fields argument '
                'must be a sequence of str instances.')

        efficiency_mode2func = {
            'memory': self._load_file_memory_efficiently,
            'time': self._load_file_time_efficiently
        }
        if(efficiency_mode is None):
            efficiency_mode = 'time'
        if(not isinstance(efficiency_mode, str)):
            raise TypeError('The efficiency_mode argument must be an instance '
                'of type str!')
        if(efficiency_mode not in efficiency_mode2func):
            raise ValueError('The efficiency_mode argument value must be one '
                'of %s!'%(', '.join(efficiency_mode2func.keys())))
        load_file_func = efficiency_mode2func[efficiency_mode]

        # Load the first data file.
        data = load_file_func(
            self._pathfilename_list[0],
            keep_fields=keep_fields,
            dtype_convertions=dtype_convertions,
            dtype_convertion_except_fields=dtype_convertion_except_fields
        )

        # Load possible subsequent data files by appending to the first data.
        for i in range(1, len(self._pathfilename_list)):
            data.append(load_file_func(
                self._pathfilename_list[i],
                keep_fields=keep_fields,
                dtype_convertions=dtype_convertions,
                dtype_convertion_except_fields=dtype_convertion_except_fields
            ))

        return data


class PKLFileLoader(FileLoader):
    """The PKLFileLoader class provides the data loading functionality for
    pickled Python data files containing Python data structures. It uses the
    `pickle.load` function for loading the data from the file.
    """
    def __init__(self, pathfilenames, pkl_encoding=None, **kwargs):
        """Creates a new file loader instance for a pickled data file.

        Parameters
        ----------
        pathfilenames : str | sequence of str
            The sequence of fully qualified file names of the data files that
            need to be loaded.
        pkl_encoding : str | None
            The encoding of the pickled data files. If None, the default
            encodings 'ASCII' and 'latin1' will be tried to load the data.
        """
        super(PKLFileLoader, self).__init__(pathfilenames)

        self.pkl_encoding = pkl_encoding

    @property
    def pkl_encoding(self):
        """The encoding of the pickled data files. Can be None.
        If None, the default encodings 'ASCII' and 'latin1' will be tried to
        load the data.
        """
        return self._pkl_encoding
    @pkl_encoding.setter
    def pkl_encoding(self, encoding):
        if(encoding is not None):
            if(not isinstance(encoding, str)):
                raise TypeError('The pkl_encoding property must be None or of '
                    'type str!')
        self._pkl_encoding = encoding

    def load_data(self, **kwargs):
        """Loads the data from the files specified through their fully qualified
        file names.

        Returns
        -------
        data : Python object | list of Python objects
            The de-pickled Python object. If more than one file was specified,
            this is a list of Python objects, i.e. one object for each file.
            The file <-> object mapping order is preserved.

        Raises
        ------
        RuntimeError if a file does not exist.
        """
        # Define the possible encodings of the pickled files.
        encodings = ['ASCII', 'latin1']
        if(self._pkl_encoding is not None):
            encodings = [self._pkl_encoding] + encodings

        data = []
        for pathfilename in self.pathfilename_list:
            assert_file_exists(pathfilename)
            with open(pathfilename, 'rb') as ifile:
                enc_idx = 0
                load_ok = False
                obj = None
                while (not load_ok) and (enc_idx < len(encodings)):
                    try:
                        encoding = encodings[enc_idx]
                        obj = pickle.load(ifile, encoding=encoding)
                    except UnicodeDecodeError:
                        enc_idx += 1
                        # Move the file pointer back to the beginning of the
                        # file.
                        ifile.seek(0)
                    else:
                        load_ok = True
                if(obj is None):
                    raise RuntimeError('The file "%s" could not get unpickled! '
                        'No correct encoding available!'%(pathfilename))
                data.append(obj)

        if(len(data) == 1):
            data = data[0]

        return data


class DataFieldRecordArray(object):
    """The DataFieldRecordArray class provides a data container similar to a numpy
    record ndarray. But the data fields are stored as individual numpy ndarray
    objects. Hence, access of single data fields is much faster compared to
    access on the record ndarray.
    """
    def __init__(self, data, keep_fields=None, dtype_convertions=None,
            dtype_convertion_except_fields=None, copy=True):
        """Creates a DataFieldRecordArray from the given numpy record ndarray.

        Parameters
        ----------
        data : numpy record ndarray | dict | DataFieldRecordArray | None
            The numpy record ndarray that needs to get transformed into the
            DataFieldRecordArray instance. Alternative a dictionary with field
            names as keys and numpy ndarrays as values can be provided. If an
            instance of DataFieldRecordArray is provided, the new
            DataFieldRecordArray gets constructed from the copy of the data of
            the provided DataFieldRecordArray instance.
            If set to `None`, the DataFieldRecordArray instance is initialized
            with no data and the length of the array is set to 0.
        keep_fields : str | sequence of str | None
            If not None (default), this specifies the data fields that should
            get kept from the given data. Otherwise all data fields get kept.
        dtype_convertions : dict | None
            If not None, this dictionary defines how data fields of specific
            data types get converted into the specified data types.
            This can be used to use less memory.
        dtype_convertion_except_fields : str | sequence of str | None
            The sequence of field names whose data type should not get
            converted.
        copy : bool
            Flag if the input data should get copied. Default is True. If a
            DataFieldRecordArray instance is provided, this option is set to
            `True` automatically.
        """
        self._data_fields = dict()
        self._len = None

        if(data is None):
            data = dict()

        if(keep_fields is not None):
            if(isinstance(keep_fields, str)):
                keep_fields = [ keep_fields ]
            elif(not issequenceof(keep_fields, str)):
                raise TypeError('The keep_fields argument must be None, an '
                    'instance of type str, or a sequence of instances of '
                    'type str!')

        if(dtype_convertions is None):
            dtype_convertions = dict()
        elif(not isinstance(dtype_convertions, dict)):
            raise TypeError('The dtype_convertions argument must be None, '
                'or an instance of dict!')

        if(dtype_convertion_except_fields is None):
            dtype_convertion_except_fields = []
        elif(isinstance(dtype_convertion_except_fields, str)):
            dtype_convertion_except_fields = [ dtype_convertion_except_fields ]
        elif(not issequenceof(dtype_convertion_except_fields, str)):
            raise TypeError('The dtype_convertion_except_fields argument '
                'must be a sequence of str instances.')

        if(isinstance(data, np.ndarray)):
            field_names = data.dtype.names
            fname2dtype = dict(
                [(k,v[0]) for (k,v) in data.dtype.fields.items() ])
            length = data.shape[0]
        elif(isinstance(data, dict)):
            field_names = list(data.keys())
            fname2dtype = dict(
                [ (fname, data[fname].dtype) for fname in field_names ])
            length = 0
            if(len(field_names) > 0):
                length = data[field_names[0]].shape[0]
        elif(isinstance(data, DataFieldRecordArray)):
            field_names = data.field_name_list
            fname2dtype = dict(
                [ (fname, data[fname].dtype) for fname in field_names ])
            length = len(data)
            copy = True
        else:
            raise TypeError('The data argument must be an instance of ndarray, '
                'dict, or DataFieldRecordArray!')

        for fname in field_names:
            # Ignore fields that should not get kept.
            if((keep_fields is not None) and (fname not in keep_fields)):
                continue

            copy_field = copy
            dt = fname2dtype[fname]
            if((fname not in dtype_convertion_except_fields) and
               (dt in dtype_convertions)):
                dt = dtype_convertions[dt]
                # If a data type convertion is needed, the data of the field
                # needs to get copied.
                copy_field = True

            if(copy_field is True):
                # Create a ndarray with the final data type and then assign the
                # values from the data, which technically is a copy.
                field_arr = np.empty((length,), dtype=dt)
                field_arr[:] = data[fname]
            else:
                field_arr = data[fname]
            if(self._len is None):
                self._len = len(field_arr)
            elif(len(field_arr) != self._len):
                raise ValueError('All field arrays must have the same length. '
                    'Field "%s" has length %d, but must be %d!'%(
                    fname, len(field_arr), self._len))

            self._data_fields[fname] = field_arr

        if(self._len is None):
            # The DataFieldRecordArray is initialized with no fields, i.e. also
            # also no data.
            self._len = 0

        self._field_name_list = list(self._data_fields.keys())
        self._indices = None

    def __getitem__(self, name):
        """Implements data field value access.

        Parameters
        ----------
        name : str | numpy ndarray of int or bool
            The name of the data field. If a numpy ndarray is given, it must
            contain the indices for which to retrieve a data selection of the
            entire DataFieldRecordArray. A numpy ndarray of bools can be given
            as well to define a mask.

        Returns
        -------
        data : numpy ndarray | DataFieldRecordArray
            The requested field data or a DataFieldRecordArray holding the
            requested selection of the entire data.
        """
        if(isinstance(name, np.ndarray)):
            return self.get_selection(name)

        if(name not in self._data_fields):
            raise KeyError('The data field "%s" is not present in the '
                'DataFieldRecordArray instance.'%(name))

        return self._data_fields[name]

    def __setitem__(self, name, arr):
        """Implements data field value assigment.

        Parameters
        ----------
        name : str | numpy ndarray of int or bool
            The name of the data field, or a numpy ndarray holding the indices
            or mask of a selection of this DataFieldRecordArray.
        arr : numpy ndarray | instance of DataFieldRecordArray
            The numpy ndarray holding the field values. It must be of the same
            length as this DataFieldRecordArray. If `name` is a numpy ndarray,
            `arr` must be a DataFieldRecordArray.
        """
        if(isinstance(name, np.ndarray)):
            self.set_selection(name, arr)
            return

        # We set a particular data field.
        if(len(arr) != self._len):
            raise ValueError('The length of the to-be-set data (%d) must '
                'match the length (%d) of the DataFieldRecordArray instance!'%(
                len(arr), self._len))

        self._data_fields[name] = arr

    def __len__(self):
        return self._len

    def __sizeof__(self):
        """Calculates the size in bytes of this DataFieldRecordArray instance
        in memory.

        Returns
        -------
        memsize : int
            The memory size in bytes that this DataFieldRecordArray instance
            has.
        """
        memsize = getsizeof([
            self._data_fields,
            self._len,
            self._field_name_list,
            self._indices
        ])
        return memsize

    def __str__(self):
        """Creates a pretty informative string representation of this
        DataFieldRecordArray instance.
        """
        (size, prefix) = get_byte_size_prefix(sys.getsizeof(self))

        max_field_name_len = np.max(
            [len(fname) for fname in self._field_name_list])

        # Generates a pretty string representation of the given field name.
        def _pretty_str_field(name):
            field = self._data_fields[name]
            s = '%s: {dtype: %s, vmin: % .3e, vmax: % .3e}'%(
                name.ljust(max_field_name_len), str(field.dtype), np.min(field),
                np.max(field))
            return s

        indent_str = ' '*dsp.INDENTATION_WIDTH
        s = '%s: %d fields, %d entries, %.0f %sbytes '%(
            classname(self), len(self._field_name_list), self.__len__(),
            np.round(size, 0), prefix)
        if(len(self._field_name_list) > 0):
            s += '\n' + indent_str + 'fields = {'
            s += '\n' + indent_str*2 + _pretty_str_field(self._field_name_list[0])
            for fname in self._field_name_list[1:]:
                s += '\n' + indent_str*2 + _pretty_str_field(fname)
            s += '\n' + indent_str + '}'
        return s

    @property
    def field_name_list(self):
        """(read-only) The list of the field names of this DataFieldRecordArray.
        """
        return self._field_name_list

    @property
    def indices(self):
        """(read-only) The numpy ndarray holding the indices of this
        DataFieldRecordArray.
        """
        if(self._indices is None):
            self._indices = np.indices((self._len,))[0]
        return self._indices

    def append(self, arr):
        """Appends the given DataFieldRecordArray to this DataFieldRecordArray
        instance.

        Parameters
        ----------
        arr : instance of DataFieldRecordArray
            The instance of DataFieldRecordArray that should get appended to
            this DataFieldRecordArray. It must contain the same data fields.
            Additional data fields are ignored.
        """
        if(not isinstance(arr, DataFieldRecordArray)):
            raise TypeError('The arr argument must be an instance of '
                'DataFieldRecordArray!')

        for fname in self._field_name_list:
            self._data_fields[fname] = np.append(
                self._data_fields[fname], arr[fname])

        self._len += len(arr)
        self._indices = None

    def append_field(self, name, data):
        """Appends a field and its data to this DataFieldRecordArray instance.

        Parameters
        ----------
        name : str
            The name of the new data field.
        data : numpy ndarray
            The numpy ndarray holding the data.
        """
        if(not isinstance(name, str)):
            raise TypeError('The name argument must be an instance of str!')
        if(not isinstance(data, np.ndarray)):
            raise TypeError('The data argument must be an instance of ndarray!')
        if(len(data) != self._len):
            raise ValueError('The length of the given data is %d, but must '
                'be %d!'%(len(data), self._len))

        self._data_fields[name] = data
        self._field_name_list.append(name)

    def as_numpy_record_array(self):
        """Creates a numpy record ndarray instance holding the data of this
        DataFieldRecordArray instance.

        Returns
        -------
        arr : numpy record ndarray
            The numpy recarray ndarray holding the data of this
            DataFieldRecordArray instance.
        """
        dt = np.dtype(
            [(name, self._data_fields[name].dtype)
             for name in self.field_name_list])

        arr = np.empty((len(self),), dtype=dt)
        for name in self.field_name_list:
            arr[name] = self[name]

        return arr

    def copy(self, keep_fields=None):
        """Creates a new DataFieldRecordArray that is a copy of this
        DataFieldRecordArray instance.

        Parameters
        ----------
        keep_fields : str | sequence of str | None
            If not None (default), this specifies the data fields that should
            get kept from this DataFieldRecordArray. Otherwise all data fields
            get kept.
        """
        return DataFieldRecordArray(self, keep_fields=keep_fields)

    def remove_field(self, name):
        """Removes the given field from this array.

        Parameters
        ----------
        name : str
            The name of the data field that is to be removed.
        """
        self._data_fields.pop(name)
        self._field_name_list.remove(name)

    def get_field_dtype(self, name):
        """Returns the numpy dtype object of the given data field.
        """
        return self._data_fields[name].dtype

    def convert_dtypes(self, convertions, except_fields=None):
        """Converts the data type of the data fields of this
        DataFieldRecordArray. This method can be used to compress the data.

        Parameters
        ----------
        convertions : dict of `old_dtype` -> `new_dtype`
            The sequence of 2-element tuples that define the old and the new
            data type as numpy dtype instances.
        except_fields : list of str | None
            The list of field names, which should not get converted.
        """
        if(not isinstance(convertions, dict)):
            raise TypeError('The convertions argument must be an instance of '
                'dict!')

        if(except_fields is None):
            except_fields = []
        if(not issequenceof(except_fields, str)):
            raise TypeError('The except_fields argument must be a sequence '
                'of str!')

        _data_fields = self._data_fields
        for fname in self._field_name_list:
            if(fname in except_fields):
                continue
            old_dtype = _data_fields[fname].dtype
            if(old_dtype in convertions):
                new_dtype = convertions[old_dtype]
                _data_fields[fname] = _data_fields[fname].astype(new_dtype)

    def get_selection(self, indices):
        """Creates an DataFieldRecordArray that contains a selection of the data
        of this DataFieldRecordArray instance.

        Parameters
        ----------
        indices : (N,)-shaped numpy ndarray of int or bool
            The numpy ndarray holding the indices for which to select the data.

        Returns
        -------
        data_field_array : DataFieldRecordArray
            The DataFieldRecordArray that contains the selection of the
            original DataFieldRecordArray. The selection data is a copy of the
            original data.
        """
        data = dict()
        for fname in self._field_name_list:
            # Get the data selection from the original data. This creates a
            # copy.
            data[fname] = self._data_fields[fname][indices]
        return DataFieldRecordArray(data, copy=False)

    def set_selection(self, indices, arr):
        """Sets a selection of the data of this DataFieldRecordArray instance
        to the data given in arr.

        Parameters
        ----------
        indices : (N,)-shaped numpy ndarray of int or bool
            The numpy ndarray holding the indices or mask for which to set the
            data.
        arr : instance of DataFieldRecordArray
            The instance of DataFieldRecordArray holding the selection data.
            It must have the same fields defined as this DataFieldRecordArray
            instance.
        """
        if(not isinstance(arr, DataFieldRecordArray)):
            raise TypeError('The arr argument must be an instance of '
                'DataFieldRecordArray!')

        for fname in self._field_name_list:
            self._data_fields[fname][indices] = arr[fname]

    def rename_fields(self, convertions, must_exist=False):
        """Renames the given fields of this array.

        Parameters
        ----------
        convertions : dict of `old_name` -> `new_name`
            The dictionary holding the old and new names of the data fields.
        must_exist : bool
            Flag if the given fields must exist. If set to ``True`` and a field
            does not exist, a KeyError is raised.

        Raises
        ------
        KeyError
            If ``must_exist`` is set to ``True`` and a given field does not
            exist.
        """
        for (old_fname, new_fname) in convertions.items():
            if(old_fname in self.field_name_list):
                self._data_fields[new_fname] = self._data_fields[old_fname]
                self._data_fields.pop(old_fname)
            elif(must_exist is True):
                raise KeyError('The required field "%s" does not exist!'%(
                    old_fname))

        self._field_name_list = list(self._data_fields.keys())

    def tidy_up(self, keep_fields):
        if(not issequenceof(keep_fields, str)):
            raise TypeError('The keep_fields argument must be a sequence of '
                'str!')

        # We need to make a copy of the field_name_list because that list will
        # get changed by the `remove_field` method.
        field_name_list = copy.copy(self._field_name_list)
        for fname in field_name_list:
            if(fname not in keep_fields):
                self.remove_field(fname)

    def sort_by_field(self, name):
        """Sorts the data along the given field name is ascending order.

        Parameters
        ----------
        name : str
            The name of the field along the events should get sorted.

        Raises
        ------
        KeyError
            If the given data field does not exist.
        """
        if(name not in self._data_fields):
            raise KeyError('The data field "{}" does not exist in this '
                'DataFieldRecordArray instance!'.format(name))

        sorted_idxs = np.argsort(self._data_fields[name])

        for fname in self.field_name_list:
            self._data_fields[fname] = self._data_fields[fname][sorted_idxs]


register_FileLoader(['.npy'], NPYFileLoader)
register_FileLoader(['.pkl'], PKLFileLoader)
