"""Define the Component class."""

from __future__ import division

import sys
import inspect

from fnmatch import fnmatchcase
import numpy
from itertools import product, chain
from six import string_types, iteritems
from scipy.sparse import issparse
from copy import deepcopy
from collections import OrderedDict

from openmdao.approximation_schemes.finite_difference import FiniteDifference
from openmdao.core.system import System, PathData
from openmdao.jacobians.global_jacobian import SUBJAC_META_DEFAULTS
from openmdao.utils.units import valid_units
from openmdao.utils.general_utils import \
    format_as_float_or_array, ensure_compatible, warn_deprecation


class Component(System):
    """
    Base Component class; not to be directly instantiated.

    Attributes
    ----------
    _var2meta : dict
        A mapping of local variable name to its metadata.
    _approx_schemes : OrderedDict
        A mapping of approximation types to the associated ApproximationScheme.
    """

    def __init__(self, **kwargs):
        """
        Initialize all attributes.

        Parameters
        ----------
        **kwargs : dict of keyword arguments
            available here and in all descendants of this system.
        """
        super(Component, self).__init__(**kwargs)
        self._var2meta = {}
        self._approx_schemes = OrderedDict()

    def add_input(self, name, val=1.0, shape=None, src_indices=None, units=None,
                  desc='', var_set=0):
        """
        Add an input variable to the component.

        Parameters
        ----------
        name : str
            name of the variable in this component's namespace.
        val : float or list or tuple or ndarray
            The initial value of the variable being added in user-defined units.
            Default is 1.0.
        shape : int or tuple or list or None
            Shape of this variable, only required if src_indices not provided and
            val is not an array. Default is None.
        src_indices : int or list of ints or tuple of ints or int ndarray or None
            The indices of the source variable to transfer data from.
            If val is given as an array_like object, the shapes of val and
            src_indices must match. A value of None implies this input depends
            on all entries of source. Default is None.
        units : str or None
            Units in which this input variable will be provided to the component
            during execution. Default is None, which means it has no units.
        desc : str
            description of the variable
        var_set : hashable object
            For advanced users only. ID or color for this variable, relevant for
            reconfigurability. Default is 0.
        """
        if inspect.stack()[1][3] == '__init__':
            warn_deprecation("In the future, the 'add_input' method must be "
                             "called from 'initialize_variables' rather than "
                             "in the '__init__' function.")

        # First, type check all arguments
        if not isinstance(name, str):
            raise TypeError('The name argument should be a string')
        if not numpy.isscalar(val) and not isinstance(val, (list, tuple, numpy.ndarray)):
            raise TypeError('The val argument should be a float, list, tuple, or ndarray')
        if shape is not None and not isinstance(shape, (int, tuple, list)):
            raise TypeError('The shape argument should be an int, tuple, or list')
        if src_indices is not None and not isinstance(src_indices, (int, list, tuple,
                                                                    numpy.ndarray)):
            raise TypeError('The src_indices argument should be an int, list, '
                            'tuple, or ndarray')
        if units is not None and not isinstance(units, str):
            raise TypeError('The units argument should be a str or None')

        # Check that units are valid
        if units is not None and not valid_units(units):
            raise ValueError("The units '%s' are invalid" % units)

        metadata = {}

        # value, shape: based on args, making sure they are compatible
        metadata['value'], metadata['shape'] = ensure_compatible(name, val,
                                                                 shape,
                                                                 src_indices)

        # src_indices: None or ndarray
        if src_indices is None:
            metadata['src_indices'] = None
        else:
            metadata['src_indices'] = numpy.atleast_1d(src_indices)

        # units: taken as is
        metadata['units'] = units

        # desc: taken as is
        metadata['desc'] = desc

        # var_set: taken as is
        metadata['var_set'] = var_set

        self._var_allprocs_names['input'].append(name)
        self._var_myproc_names['input'].append(name)
        self._var_myproc_metadata['input'].append(metadata)
        self._var2meta[name] = metadata

        # [REFACTOR]
        # We may not know the pathname yet, so we have to use name for now, instead of abs_name.
        abs_name = name
        self._varx_abs2data_io[abs_name] = {'prom': name, 'rel': name,
                                            'my_idx': len(self._varx_abs_names['input']),
                                            'type_': 'input', 'metadata': metadata}
        self._varx_abs_names['input'].append(abs_name)
        self._varx_allprocs_prom2abs_set['input'][name] = set([abs_name])

    def add_output(self, name, val=1.0, shape=None, units=None, res_units=None, desc='',
                   lower=None, upper=None, ref=1.0, ref0=0.0,
                   res_ref=1.0, res_ref0=0.0, var_set=0):
        """
        Add an output variable to the component.

        Parameters
        ----------
        name : str
            name of the variable in this component's namespace.
        val : float or list or tuple or ndarray
            The initial value of the variable being added in user-defined units. Default is 1.0.
        shape : int or tuple or list or None
            Shape of this variable, only required if val is not an array.
            Default is None.
        units : str or None
            Units in which the output variables will be provided to the component during execution.
            Default is None, which means it has no units.
        res_units : str or None
            Units in which the residuals of this output will be given to the user when requested.
            Default is None, which means it has no units.
        desc : str
            description of the variable.
        lower : float or list or tuple or ndarray or None
            lower bound(s) in user-defined units. It can be (1) a float, (2) an array_like
            consistent with the shape arg (if given), or (3) an array_like matching the shape of
            val, if val is array_like. A value of None means this output has no lower bound.
            Default is None.
        upper : float or list or tuple or ndarray or None
            upper bound(s) in user-defined units. It can be (1) a float, (2) an array_like
            consistent with the shape arg (if given), or (3) an array_like matching the shape of
            val, if val is array_like. A value of None means this output has no upper bound.
            Default is None.
        ref : float
            Scaling parameter. The value in the user-defined units of this output variable when
            the scaled value is 1. Default is 1.
        ref0 : float
            Scaling parameter. The value in the user-defined units of this output variable when
            the scaled value is 0. Default is 0.
        res_ref : float
            Scaling parameter. The value in the user-defined res_units of this output's residual
            when the scaled value is 1. Default is 1.
        res_ref0 : float
            Scaling parameter. The value in the user-defined res_units of this output's residual
            when the scaled value is 0. Default is 0.
        var_set : hashable object
            For advanced users only. ID or color for this variable, relevant for reconfigurability.
            Default is 0.
        """
        if inspect.stack()[1][3] == '__init__':
            warn_deprecation("In the future, the 'add_output' method must be "
                             "called from 'initialize_variables' rather than "
                             "in the '__init__' function.")

        # First, type check all arguments
        if not isinstance(name, str):
            raise TypeError('The name argument should be a string')
        if not numpy.isscalar(val) and not isinstance(val, (list, tuple, numpy.ndarray)):
            raise TypeError('The val argument should be a float, list, tuple, or ndarray')
        if shape is not None and not isinstance(shape, (int, tuple, list)):
            raise TypeError('The shape argument should be an int, tuple, or list')
        if units is not None and not isinstance(units, str):
            raise TypeError('The units argument should be a str or None')
        if res_units is not None and not isinstance(res_units, str):
            raise TypeError('The res_units argument should be a str or None')
        if lower is not None:
            lower = format_as_float_or_array('lower', lower)
        if upper is not None:
            upper = format_as_float_or_array('upper', upper)

        for item in [ref, ref0, res_ref, res_ref]:
            if not numpy.isscalar(item):
                raise TypeError('The %s argument should be a float' % (item.__name__))

        # Check that units are valid
        if units is not None and not valid_units(units):
            raise ValueError("The units '%s' are invalid" % units)

        metadata = {}

        # value, shape: based on args, making sure they are compatible
        metadata['value'], metadata['shape'] = ensure_compatible(name, val, shape)

        # units, res_units: taken as is
        metadata['units'] = units
        metadata['res_units'] = res_units

        # desc: taken as is
        metadata['desc'] = desc

        # lower, upper: check the shape if necessary
        if lower is not None and not numpy.isscalar(lower) and \
                numpy.atleast_1d(lower).shape != metadata['shape']:
            raise ValueError('The lower argument has the wrong shape')
        if upper is not None and not numpy.isscalar(upper) and \
                numpy.atleast_1d(upper).shape != metadata['shape']:
            raise ValueError('The upper argument has the wrong shape')
        metadata['lower'] = lower
        metadata['upper'] = upper

        # ref, ref0, res_ref, res_ref0: taken as is
        metadata['ref'] = ref
        metadata['ref0'] = ref0
        metadata['res_ref'] = res_ref
        metadata['res_ref0'] = res_ref0

        # var_set: taken as is
        metadata['var_set'] = var_set

        self._var_allprocs_names['output'].append(name)
        self._var_myproc_names['output'].append(name)
        self._var_myproc_metadata['output'].append(metadata)
        self._var2meta[name] = metadata

        # [REFACTOR]
        # We may not know the pathname yet, so we have to use name for now, instead of abs_name.
        abs_name = name
        self._varx_abs2data_io[abs_name] = {'prom': name, 'rel': name,
                                            'my_idx': len(self._varx_abs_names['output']),
                                            'type_': 'output', 'metadata': metadata}
        self._varx_abs_names['output'].append(abs_name)
        self._varx_allprocs_prom2abs_set['output'][name] = set([abs_name])

    def approx_partials(self, of, wrt, method='fd', **kwargs):
        """
        Inform the framework that the specified derivatives are to be approximated.

        Parameters
        ----------
        of : str or list of str
            The name of the residual(s) that derivatives are being computed for.
            May also contain a glob pattern.
        wrt : str or list of str
            The name of the variables that derivatives are taken with respect to.
            This can contain the name of any input or output variable.
            May also contain a glob pattern.
        method : str
            The type of approximation that should be used. Valid options include:
                - 'fd': Finite Difference
        **kwargs : dict
            Keyword arguments for controlling the behavior of the approximation.
        """
        supported_methods = {'fd': FiniteDifference}

        if method not in supported_methods:
            msg = 'Method "{}" is not supported, method must be one of {}'
            raise ValueError(msg.format(method, supported_methods.keys()))

        if method not in self._approx_schemes:
            self._approx_schemes[method] = supported_methods[method]()

        pattern_matches = self._find_partial_matches(of, wrt)

        for of_bundle, wrt_bundle in product(*pattern_matches):
            of_pattern, of_matches = of_bundle
            wrt_pattern, wrt_out, wrt_in = wrt_bundle
            if not of_matches:
                raise ValueError('No matches were found for of="{}"'.format(of_pattern))
            if not (wrt_out or wrt_in):
                raise ValueError('No matches were found for wrt="{}"'.format(wrt_pattern))

            for type_, wrt_matches in [('output', wrt_out), ('input', wrt_in)]:
                for key in product(of_matches, wrt_matches):
                    meta_changes = {
                        'method': method,
                        'type': type_
                    }
                    meta = self._subjacs_info.get(key, SUBJAC_META_DEFAULTS.copy())
                    meta.update(meta_changes)
                    meta.update(kwargs)
                    self._subjacs_info[key] = meta

    def declare_partials(self, of, wrt, dependent=True,
                         rows=None, cols=None, val=None):
        """
        Store subjacobian metadata for later use.

        Parameters
        ----------
        of : str or list of str
            The name of the residual(s) that derivatives are being computed for.
            May also contain a glob pattern.
        wrt : str or list of str
            The name of the variables that derivatives are taken with respect to.
            This can contain the name of any input or output variable.
            May also contain a glob pattern.
        dependent : bool(True)
            If False, specifies no dependence between the output(s) and the
            input(s). This is only necessary in the case of a sparse global
            jacobian, because if 'dependent=False' is not specified and
            set_subjac_info is not called for a given pair, then a dense
            matrix of zeros will be allocated in the sparse global jacobian
            for that pair.  In the case of a dense global jacobian it doesn't
            matter because the space for a dense subjac will always be
            allocated for every pair.
        rows : ndarray of int or None
            Row indices for each nonzero entry.  For sparse subjacobians only.
        cols : ndarray of int or None
            Column indices for each nonzero entry.  For sparse subjacobians only.
        val : float or ndarray of float or scipy.sparse
            Value of subjacobian.  If rows and cols are not None, this will
            contain the values found at each (row, col) location in the subjac.
        """
        # If only one of rows/cols is specified
        if (rows is None) ^ (cols is None):
            raise ValueError('If one of rows/cols is specified, then both must be specified')

        if val is not None and not issparse(val):
            val = numpy.atleast_1d(val)
            # numpy.promote_types  will choose the smallest dtype that can contain both arguments
            safe_dtype = numpy.promote_types(val.dtype, float)
            val = val.astype(safe_dtype, copy=False)

        if rows is not None:
            if isinstance(rows, (list, tuple)):
                rows = numpy.array(rows, dtype=int)
            if isinstance(cols, (list, tuple)):
                cols = numpy.array(cols, dtype=int)

            if rows.shape != cols.shape:
                raise ValueError('rows and cols must have the same shape,'
                                 ' rows: {}, cols: {}'.format(rows.shape, cols.shape))

            if val is not None and val.shape != (1,) and rows.shape != val.shape:
                raise ValueError('If rows and cols are specified, val must be a scalar or have the '
                                 'same shape, val: {}, rows/cols: {}'.format(val.shape, rows.shape))

        pattern_matches = self._find_partial_matches(of, wrt)

        multiple_items = False

        for of_bundle, wrt_bundle in product(*pattern_matches):
            of_pattern, of_matches = of_bundle
            wrt_pattern, wrt_out, wrt_in = wrt_bundle
            if not of_matches:
                raise ValueError('No matches were found for of="{}"'.format(of_pattern))
            if not (wrt_out or wrt_in):
                raise ValueError('No matches were found for wrt="{}"'.format(wrt_pattern))

            make_copies = (multiple_items
                           or len(of_matches) > 1
                           or (len(wrt_in) + len(wrt_out)) > 1)
            # Setting this to true means that future loop iterations (i.e. if there are multiple
            # items in either of or wrt) will make copies.
            multiple_items = True

            for type_, wrt_matches in [('output', wrt_out), ('input', wrt_in)]:
                for key in product(of_matches, wrt_matches):
                    meta_changes = {
                        'rows': rows,
                        'cols': cols,
                        'value': deepcopy(val) if make_copies else val,
                        'dependent': dependent,
                        'type': type_
                    }
                    meta = self._subjacs_info.get(key, SUBJAC_META_DEFAULTS.copy())
                    meta.update(meta_changes)
                    self._check_partials_meta(key, meta)
                    self._subjacs_info[key] = meta

    def _find_partial_matches(self, of, wrt):
        """
        Find all partial derivative matches from of and wrt.

        Parameters
        ----------
        of : str or list of str
            The name of the residual(s) that derivatives are being computed for.
            May also contain a glob pattern.
        wrt : str or list of str
            The name of the variables that derivatives are taken with respect to.
            This can contain the name of any input or output variable.
            May also contain a glob pattern.

        Returns
        -------
        tuple(list, list)
            Pair of lists containing pattern matches (if any). Returns (of_matches, wrt_matches)
            where of_matches is a list of tuples (pattern, matches) and wrt_matches is a list of
            tuples (pattern, output_matches, input_matches).
        """
        of_list = [of] if isinstance(of, string_types) else of
        wrt_list = [wrt] if isinstance(wrt, string_types) else wrt
        glob_patterns = {'*', '?', '['}
        outs = self._var_allprocs_names['output']
        ins = self._var_allprocs_names['input']

        def find_matches(pattern, var_list):
            if glob_patterns.intersection(pattern):
                return [name for name in var_list if fnmatchcase(name, pattern)]
            elif pattern in var_list:
                return [pattern]
            return []

        of_pattern_matches = [(pattern, find_matches(pattern, outs)) for pattern in of_list]
        wrt_pattern_matches = [(pattern, find_matches(pattern, outs), find_matches(pattern, ins))
                               for pattern in wrt_list]
        return of_pattern_matches, wrt_pattern_matches

    def _check_partials_meta(self, key, meta):
        """
        Check a given partial derivative and metadata for the correct shapes.

        Parameters
        ----------
        key : tuple(str,str)
            The of/wrt pair defining the partial derivative.
        meta : dict
            Metadata dictionary from declare_partials.
        """
        of, wrt = key
        if meta['dependent']:
            out_size = numpy.prod(self._var2meta[of]['shape'])
            in_size = numpy.prod(self._var2meta[wrt]['shape'])
            rows = meta['rows']
            cols = meta['cols']
            if rows is not None:
                if rows.min() < 0:
                    msg = '{}: d({})/d({}): row indices must be non-negative'
                    raise ValueError(msg.format(self.pathname, of, wrt))
                if cols.min() < 0:
                    msg = '{}: d({})/d({}): col indices must be non-negative'
                    raise ValueError(msg.format(self.pathname, of, wrt))
                if rows.max() >= out_size or cols.max() >= in_size:
                    msg = '{}: d({})/d({}): Expected {}x{} but declared at least {}x{}'
                    raise ValueError(msg.format(
                        self.pathname, of, wrt,
                        out_size, in_size,
                        rows.max() + 1, cols.max() + 1))
            elif meta['value'] is not None:
                val = meta['value']
                val_shape = val.shape
                if len(val_shape) == 1:
                    val_out, val_in = val_shape[0], 1
                else:
                    val_out, val_in = val.shape
                if val_out > out_size or val_in > in_size:
                    msg = '{}: d({})/d({}): Expected {}x{} but val is {}x{}'
                    raise ValueError(msg.format(
                        self.pathname, of, wrt,
                        out_size, in_size,
                        val_out, val_in))

    def _set_partials_meta(self):
        """
        Set subjacobian info into our jacobian.
        """
        with self._jacobian_context() as J:
            for key, meta in iteritems(self._subjacs_info):
                self._check_partials_meta(key, meta)
                J._set_partials_meta(key, meta)

                method = meta.get('method', False)
                if method and meta['dependent']:
                    self._approx_schemes[method].add_approximation(key, meta)

        for approx in self._approx_schemes:
            approx._init_approximations()

    def _setup_variables(self, recurse=False):
        """
        Assemble variable metadata and names lists.

        Sets the following attributes:
            _var_allprocs_names
            _var_myproc_names
            _var_myproc_metadata
            _var_pathdict
            _var_name2path

        Parameters
        ----------
        recurse : boolean
            Ignored.
        """
        super(Component, self)._setup_variables(False)

        # set up absolute path info
        self._var_pathdict = {}
        self._var_name2path = {'input': {}, 'output': {}}
        for typ in ['input', 'output']:
            names = self._var_allprocs_names[typ]
            if self.pathname:
                self._var_allprocs_pathnames[typ] = paths = [
                    '.'.join((self.pathname, n)) for n in names
                ]
            else:
                self._var_allprocs_pathnames[typ] = paths = names
            for idx, name in enumerate(names):
                path = paths[idx]
                self._var_pathdict[path] = PathData(name, idx, idx, typ)
                if typ is 'input':
                    self._var_name2path[typ][name] = (path,)
                else:
                    self._var_name2path[typ][name] = path

        # Now that variables are available, we can setup partials
        self.initialize_partials()

    def _setup_vector(self, vectors, vector_var_ids, use_ref_vector):
        r"""
        Add this vector and assign sub_vectors to subsystems.

        Sets the following attributes:

        - _vectors
        - _vector_transfers
        - _inputs*
        - _outputs*
        - _residuals*
        - _transfers*

        \* If vec_name is 'nonlinear'

        Parameters
        ----------
        vectors : {'input': <Vector>, 'output': <Vector>, 'residual': <Vector>}
            <Vector> objects corresponding to 'name'.
        vector_var_ids : ndarray[:]
            integer array of all relevant variables for this vector.
        use_ref_vector : bool
            if True, allocate vectors to store ref. values.
        """
        super(Component, self)._setup_vector(vectors, vector_var_ids,
                                             use_ref_vector)

        # Components must load their initial input and output values into the
        # vectors.

        # Note: It's possible for meta['value'] to not match
        #       meta['shape'], and input and output vectors are sized according
        #       to shape, so if, for example, value is not specified it
        #       defaults to 1.0 and the shape can be anything, resulting in the
        #       value of 1.0 being broadcast into all values in the vector
        #       that were allocated according to the shape.
        if vectors['input']._name is 'nonlinear':
            names = self._var_myproc_names['input']
            inputs = self._inputs
            for i, meta in enumerate(self._var_myproc_metadata['input']):
                inputs[names[i]] = meta['value']

        if vectors['output']._name is 'nonlinear':
            names = self._var_myproc_names['output']
            outputs = self._outputs
            for i, meta in enumerate(self._var_myproc_metadata['output']):
                outputs[names[i]] = meta['value']

    def _setupx_variables_myproc(self):
        """
        Compute variable dict/list for variables on the current processor.

        Sets the following attributes:
            _varx_abs2data_io
            _varx_abs_names
        """
        def get_abs_name(name):
            if self.pathname == '':
                abs_name = name
            else:
                abs_name = self.pathname + '.' + name
            return abs_name

        # Now that we know the pathname, convert _varx_abs_names from names to abs_names.
        for type_ in ['input', 'output']:
            abs_names = []
            for name in self._varx_abs_names[type_]:
                abs_name = get_abs_name(name)
                abs_names.append(abs_name)
            self._varx_abs_names[type_] = abs_names

        # Now that we know the pathname, convert _varx_abs2data_io from names to abs_names.
        abs2data_io = {}
        for name, data in iteritems(self._varx_abs2data_io):
            abs_name = get_abs_name(name)
            abs2data_io[abs_name] = data
        self._varx_abs2data_io = abs2data_io

    def _setupx_variable_allprocs_names(self):
        """
        Get the names for variables on all processors.

        Also, compute allprocs var counts and store in _varx_allprocs_idx_range.

        Sets the following attributes:
            _varx_allprocs_prom2abs_set

        Returns
        -------
        {'input': [str, ...], 'output': [str, ...]}
            List of absolute names of owned variables existing on current proc.
        """
        def get_abs_name(name):
            if self.pathname == '':
                abs_name = name
            else:
                abs_name = self.pathname + '.' + name
            return abs_name

        # Now that we know the pathname, convert _varx_abs_names from names to abs_names.
        for type_ in ['input', 'output']:
            allprocs_prom2abs_set = {}
            for name in self._varx_abs_names[type_]:
                abs_name = get_abs_name(name)
                allprocs_prom2abs_set[name] = set([abs_name])
            self._varx_allprocs_prom2abs_set[type_] = allprocs_prom2abs_set

        # If this is a component, myproc names = allprocs names
        # and _varx_allprocs_prom2abs_set was already computed in add_input / add_output.
        allprocs_abs_names = {'input': [], 'output': []}
        for type_ in ['input', 'output']:
            allprocs_abs_names[type_] = self._varx_abs_names[type_])

        # Now allprocs_abs_names is ready, so we get use it to
        # count the total number of allprocs variables and put it in _varx_allprocs_idx_range.
        for type_ in ['input', 'output']:
            self._varx_allprocs_idx_range[type_] = [0, len(allprocs_abs_names[type_])]

        return allprocs_abs_names

    def _setupx_variable_allprocs_indices(self, global_index):
        """
        Compute the global index range for variables on all processors.

        Computes the following attributes:
            _varx_allprocs_idx_range

        Parameters
        ----------
        global_index : {'input': int, 'output': int}
            current global variable counter.
        """
        # First, apply the global_index offset to make _varx_allprocs_idx_range correct.
        for type_ in ['input', 'output']:
            for ind in range(2):
                self._varx_allprocs_idx_range[type_][ind] += global_index[type_]

        # Reset index dict to the global variable counter on all procs.
        # Necessary for younger siblings to have proper index values.
        for type_ in ['input', 'output']:
            global_index[type_] = self._varx_allprocs_idx_range[type_][1]
