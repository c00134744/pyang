import re
import copy
import time

from debug import dbg
import util
from util import attrsearch, keysearch
from error import err_add
import types
import syntax
import grammar

### Exceptions

class NotFound(Exception):
    """used when a referenced item is not found"""
    pass

class Abort(Exception):
    """used to abort an iteration"""
    pass

### Validation

def validate_module(ctx, module):
    """Validate `module`, which is a Statement representing a (sub)module"""

    def iterate(stmt, phase):
        # if the grammar is not yet checked or if it is checked and
        # valid, then we continue.
        if (hasattr(stmt, 'is_grammatically_valid') and
            stmt.is_grammatically_valid == False):
            return
        # first check an exact match
        key = (phase, stmt.keyword)
        res = 'recurse'
        if key in _validation_map:
            f = _validation_map[key]
            res = f(ctx, stmt)
            if res == 'stop':
                raise Abort
        # then also run match by special variable
        for (var_name, var_f) in _validation_variables:
            if var_f(stmt.keyword) == True:
                key = (phase, var_name)
                if key in _validation_map:
                    f = _validation_map[key]
                    res = f(ctx, stmt)
                    if res == 'stop':
                        raise Abort
        # then run wildcard
        wildcard = (phase, '*')
        if wildcard in _validation_map:
            f = _validation_map[wildcard]
            res = f(ctx, stmt)
            if res == 'stop':
                raise Abort
        if res == 'continue':
            pass
        else:
            # default is to recurse
            if phase in _v_i_children:
                if hasattr(stmt, 'i_children'):
                    for s in stmt.i_children:
                        iterate(s, phase)
                for s in stmt.substmts:
                    if hasattr(s, 'i_has_i_children'):
                        iterate(s, phase)
            else:
                for s in stmt.substmts:
                    iterate(s, phase)

    module.i_is_validated = 'in_progress'
    try:
        for phase in _validation_phases:
            iterate(module, phase)
    except Abort:
        pass
    module.i_is_validated = True

_validation_phases = [
    # init phase:
    #   initalizes the module/submodule statement, and maps
    #   the prefix in all extensions to their modulename
    #   from this point, extensions will be validated just as the
    #   other statements
    'init',

    # grammar phase:
    #   verifies that the statement hierarchy is correct
    #   and that all arguments are of correct type
    #   complex arguments are parsed and saved in statement-specific
    #   variables
    'grammar',

    # import and include phase:
    #   tries to load each imported and included (sub)module
    'import',

    # type and grouping phase:
    #   verifies all typedefs, types and groupings
    'type',

    # expansion phases:
    #   first expansion: copy data definition stmts into i_children
    'expand_1',

    # inherit properties phase:
    #   set i_config
    'inherit_properties',

    #   second expansion: expand augmentations into i_children
    'expand_2',

    # unique name check phase:
    'unique_name',

    # reference phase:
    #   verifies all references; e.g. keyref, unique, key for config
    'reference_1',
    'reference_2',
    'reference_3',

    # unused definitions phase:
    #   add warnings for unused definitions
    'unused',
    ]

_validation_map = {
    ('init', 'module'):lambda ctx, s: v_init_module(ctx, s),
    ('init', 'submodule'):lambda ctx, s: v_init_module(ctx, s),
    ('init', '$extension'):lambda ctx, s: v_init_extension(ctx, s),
    ('init', '$has_children'):lambda ctx, s: v_init_has_children(ctx, s),
    ('init', '*'):lambda ctx, s: v_init_stmt(ctx, s),

    ('grammar', 'module'):lambda ctx, s: v_grammar_module(ctx, s),
    ('grammar', 'submodule'):lambda ctx, s: v_grammar_module(ctx, s),
    ('grammar', 'typedef'):lambda ctx, s: v_grammar_typedef(ctx, s),
    ('grammar', '*'):lambda ctx, s: v_grammar_unique_defs(ctx, s),

    ('import', 'module'):lambda ctx, s: v_import_module(ctx, s),
    ('import', 'submodule'):lambda ctx, s: v_import_module(ctx, s),

    ('type', 'typedef'):lambda ctx, s: v_type_typedef(ctx, s),
    ('type', 'type'):lambda ctx, s: v_type_type(ctx, s),
    ('type', 'leaf'):lambda ctx, s: v_type_leaf(ctx, s),
    ('type', 'leaf-list'):lambda ctx, s: v_type_leaf_list(ctx, s),
    ('type', 'grouping'):lambda ctx, s: v_type_grouping(ctx, s),
    ('type', 'augment'):lambda ctx, s: v_type_augment(ctx, s),
    ('type', 'uses'):lambda ctx, s: v_type_uses(ctx, s),
    ('type', 'feature'):lambda ctx, s: v_type_feature(ctx, s),
    ('type', 'if-feature'):lambda ctx, s: v_type_if_feature(ctx, s),
    ('type', 'identity'):lambda ctx, s: v_type_identity(ctx, s),
    ('type', 'base'):lambda ctx, s: v_type_base(ctx, s),
    ('type', '$extension'): lambda ctx, s: v_type_extension(ctx, s),

    ('expand_1', 'module'):lambda ctx, s: v_expand_1_children(ctx, s),
    ('expand_1', 'submodule'):lambda ctx, s: v_expand_1_children(ctx, s),

    ('inherit_properties', 'module'): \
        lambda ctx, s: v_inherit_properties_module(ctx, s),
    ('inherit_properties', 'submodule'): \
        lambda ctx, s: v_inherit_properties_module(ctx, s),

    ('expand_2', 'augment'):lambda ctx, s: v_expand_2_augment(ctx, s),

    ('unique_name', '$has_children'): \
        lambda ctx, s: v_unique_names_children(ctx, s),

    ('reference_1', 'list'):lambda ctx, s:v_reference_list(ctx, s),
    ('reference_2', 'leaf'):lambda ctx, s:v_reference_leaf_keyref(ctx, s),
    ('reference_2', 'leaf-list'):lambda ctx, s:v_reference_leaf_keyref(ctx, s),
    ('reference_3', 'must'):lambda ctx, s:v_reference_must(ctx, s),
    ('reference_3', 'when'):lambda ctx, s:v_reference_when(ctx, s),

    ('unused', 'module'):lambda ctx, s: v_unused_module(ctx, s),
    ('unused', 'submodule'):lambda ctx, s: v_unused_module(ctx, s),
    ('unused', 'typedef'):lambda ctx, s: v_unused_typedef(ctx, s),
    ('unused', 'grouping'):lambda ctx, s: v_unused_grouping(ctx, s),
    }

_v_i_children = {
    'unique_name':True,
    'reference_1':True,
    'reference_2':True,
}
"""Phases in this dict are run over the stmts which has i_children."""

keyword_with_children = {
    'module':True,
    'submodule':True,
    'container':True,
    'list':True,
    'case':True,
    'choice':True,
    'grouping':True,
    'uses':True,
    'augment':True,
    'input':True,
    'output':True,
    'notification':True,
    'rpc':True,
    }

_validation_variables = [
    ('$has_children', lambda keyword: keyword in keyword_with_children),
    ('$extension', lambda keyword: util.is_prefixed(keyword)),
    ]

def add_validation_phase(phase, before=None, after=None):
    """Add a validation phase to the framework.

    Can be used by plugins to do special validation of extensions."""
    idx = 0
    for x in _validation_phases:
        if x[1] == before:
            _validation_phases.insert(idx, phase)
            return
        elif x[1] == after:
            _validation_phases.insert(idx+1, phase)
            return
        idx = idx + 1
    # otherwise append at the end
    _validation_phases.append(phase)

def add_validation_fun(phase, keywords, f):
    """Add a validation function to some phase in the framework.

    Function `f` is called for each valid occurance of each keyword in
    `keywrods`.
    Can be used by plugins to do special validation of extensions."""
    for keyword in keywords:
        _validation_map[(phase, keyword)] = f

def add_validation_var(var_name, var_dict):
    """Add a validation variable to the framework.

    Can be used by plugins to do special validation of extensions."""
    _validation_variables.append((var_name, var_dict))

def set_phase_i_children(phase):
    """Marks that the phase is run over the expanded i_children.
    
    Default is to run over substmts."""
    _v_i_children[phase] = True

###

def v_init_module(ctx, stmt):
    ## remember that the grammar is not validated
    # create a prefix map in the module: <prefix string> -> <module statement>
    stmt.i_prefixes = {}
    # keep track of unused prefixes: <prefix string> -> <import statement>
    stmt.i_unused_prefixes = {}
    # keep track of missing prefixes, to supress mulitple errors
    stmt.i_missing_prefixes = {}
    # insert our own prefix into the map
    prefix = None
    if stmt.keyword == 'module':
        prefix = stmt.search_one('prefix')
        modname = stmt.arg
    else:
        belongs_to = stmt.search_one('belongs-to')
        if belongs_to is not None and belongs_to.arg is not None:
            prefix = belongs_to.search_one('prefix')
            modname = belongs_to.arg

    if prefix is not None and prefix.arg is not None:
        stmt.i_prefixes[prefix.arg] = stmt.arg
        stmt.i_prefix = prefix.arg
    else:
        stmt.i_prefix = None
    # next we try to add prefixes for each import
    for i in stmt.search('import'):
        p = i.search_one('prefix')
        # verify that the prefix is not used
        if p is not None:
            prefix = p.arg
            # check if the prefix is already used by someone else
            if prefix in stmt.i_prefixes:
                err_add(ctx.errors, p.pos, 'PREFIX_ALREADY_USED',
                        (prefix, stmt.i_prefixes[prefix]))
            # add the prefix to the unused prefixes
            if i.arg is not None and p.arg is not None:
                stmt.i_prefixes[p.arg] = i.arg
                stmt.i_unused_prefixes[p.arg] = i

    # save a pointer to the context
    stmt.i_ctx = ctx
    # keep track of created augment nodes
    stmt.i_undefined_augment_nodes = {}
    # next, set the attribute 'i_module' in each statement to point to the
    # module where the statement is defined.
    def set_i_module(s):
        s.i_module = s.top
        return
    iterate_stmt(stmt, set_i_module)

def v_init_extension(ctx, stmt):
    """find the modulename of the prefix, and set `stmt.keyword`"""
    (prefix, identifier) = stmt.raw_keyword
    modname = prefix_to_modulename(stmt.i_module, prefix, stmt.pos, ctx.errors)
    stmt.keyword = (modname, identifier)

def v_init_stmt(ctx, stmt):
    stmt.i_typedefs = {}
    stmt.i_groupings = {}
    stmt.i_uniques = []

def v_init_has_children(ctx, stmt):
    stmt.i_children = []

### grammar phase

def v_grammar_module(ctx, stmt):
    # check the statement hierarchy
    grammar.chk_module_statements(ctx, stmt, ctx.canonical)

def v_grammar_typedef(ctx, stmt):
    if types.is_base_type(stmt.arg):
        err_add(ctx.errors, stmt.pos, 'BAD_TYPE_NAME', stmt.arg)

def v_grammar_unique_defs(ctx, stmt):
    """Verify that all typedefs and groupings are unique
    Called for every statement.
    Stores all typedefs in stmt.i_typedef, groupings in stmt.i_grouping
    """
    defs = [('typedef', 'TYPE_ALREADY_DEFINED', stmt.i_typedefs),
            ('grouping', 'GROUPING_ALREADY_DEFINED', stmt.i_groupings)]
    if stmt.parent is None:
        defs.extend([('feature', 'FEATURE_ALREADY_DEFINED', {}),
                     ('identity', 'IDENTITY_ALREADY_DEFINED', {})])
    for (keyword, errcode, dict) in defs:
        for definition in stmt.search(keyword):
            if definition.arg in dict:
                other = dict[definition.arg]
                err_add(ctx.errors, definition.pos,
                        errcode, (definition.arg, other.pos))
            else:
                dict[definition.arg] = definition

### import and include phase

def v_import_module(ctx, stmt):
    imports = stmt.search('import')
    includes = stmt.search('include')
    for i in imports + includes:
        # check if the module to import is already added
        modulename = i.arg
        m = ctx.get_module(modulename)
        if m is not None and m.i_is_validated == 'in_progress':
            err_add(ctx.errors, i.pos,
                    'CIRCULAR_DEPENDENCY', ('module', modulename))
        # try to add the module to the context
        module = ctx.search_module(i.pos, modulename)

### type phase

def v_type_typedef(ctx, stmt):
    if hasattr(stmt, 'i_is_validated'):
        if stmt.i_is_validated == True:
            # this type has already been validated
            return
        elif stmt.i_is_circular == True:
            return
        elif stmt.i_is_validated == 'in_progress':
            err_add(ctx.errors, stmt.pos,
                    'CIRCULAR_DEPENDENCY', ('type', stmt.arg) )
            stmt.i_is_circular = True
            return

    stmt.i_is_circular = False
    stmt.i_is_validated = 'in_progress'
    stmt.i_default = None
    stmt.i_is_unused = True

    name = stmt.arg
    if stmt.parent.parent is not None:
        # non-top-level typedef; check if it is already defined
        ptype = search_typedef(stmt.parent.parent, name)
        if ptype is not None:
            err_add(ctx.errors, stmt.pos, 'TYPE_ALREADY_DEFINED',
                    (name, ptype.pos))
    type = stmt.search_one('type')
    if type is None or type.is_grammatically_valid == False:
        # error is already reported by grammar check
        return
    # ensure our type is validated
    v_type_type(ctx, type)

    def check_circular_typedef(ctx, type):
        # ensure the type is validated
        v_type_type(ctx, type)
        # check the direct typedef
        if (type.i_typedef is not None and 
            type.i_typedef.is_grammatically_valid == True):
            v_type_typedef(ctx, type.i_typedef)
        # check all union's types
        membertypes = type.search('type')
        for t in membertypes:
            check_circular_typedef(ctx, t)

    check_circular_typedef(ctx, type)

    stmt.i_is_validated = True

    # check if we have a default value
    default = stmt.search_one('default')
    # ... or if we don't; check if our base typedef has one
    if (default is None and
        type.i_typedef is not None and
        type.i_typedef.i_default is not None):
        # validate that the base type's default value is still valid
        stmt.i_default = type.i_typedef.i_default
        type.i_type_spec.validate(ctx.errors, stmt.pos,
                                  stmt.i_default,
                                  ' for the inherited default value ')
    elif (default is not None and 
          default.arg is not None and
          type.i_type_spec is not None):
        stmt.i_default = type.i_type_spec.str_to_val(ctx.errors,
                                                     default.pos,
                                                     default.arg)
        if stmt.i_default is not None:
            type.i_type_spec.validate(ctx.errors, default.pos,
                                      stmt.i_default,
                                      ' for the default value')

def v_type_type(ctx, stmt):
    if hasattr(stmt, 'i_is_validated'):
        # already validated
        return

    # set statement-specific variables
    stmt.i_is_validated = True
    stmt.i_is_derived = False
    stmt.i_type_spec = None
    stmt.i_typedef = None
    # Find the base type_spec
    name = stmt.arg
    if name.find(":") == -1:
        prefix = None
    else:
        [prefix, name] = name.split(':', 1)
    if prefix is None or stmt.i_module.i_prefix == prefix:
        # check local typedefs
        stmt.i_typedef = search_typedef(stmt, name)
        if stmt.i_typedef is None:
            # check built-in types
            try:
                stmt.i_type_spec = types.yang_type_specs[name]
            except KeyError:
                err_add(ctx.errors, stmt.pos,
                        'TYPE_NOT_FOUND', (name, stmt.i_module.arg))
                return
        else:
            # ensure the typedef is validated
            if stmt.i_typedef.is_grammatically_valid == True:
                v_type_typedef(ctx, stmt.i_typedef)
            stmt.i_typedef.i_is_unused = False
    else:
        # this is a prefixed name, check the imported modules
        pmodule = prefix_to_module(stmt.i_module, prefix, stmt.pos, ctx.errors)
        if pmodule is None:
            return
        stmt.i_typedef = search_typedef(pmodule, name)
        if stmt.i_typedef is None:
            err_add(ctx.errors, stmt.pos, 'TYPE_NOT_FOUND', (name, pmodule.arg))
            return
        else:
            stmt.i_typedef.i_is_unused = False

    if stmt.i_typedef is not None:
        typedef_type = stmt.i_typedef.search_one('type')
        if typedef_type is not None:
            # copy since we modify the typespec's definition
            stmt.i_type_spec = copy.copy(typedef_type.i_type_spec)
            if stmt.i_type_spec is not None:
                stmt.i_type_spec.definition = ('at ' +
                                               str(stmt.i_typedef.pos) +
                                               ' ')

    if stmt.i_type_spec is None:
        # an error has been added already; skip further validation
        return
        
    # check the range restriction
    stmt.i_ranges = []
    range = stmt.search_one('range')
    if (range is not None and
        'range' not in stmt.i_type_spec.restrictions()):
        err_add(ctx.errors, range.pos, 'BAD_RESTRICTION', 'range')
    elif range is not None:
        stmt.i_is_derived = True
        ranges_spec = types.validate_range_expr(ctx.errors, range, stmt)
        if ranges_spec is not None:
            stmt.i_ranges = ranges_spec[0]
            stmt.i_type_spec = types.RangeTypeSpec(stmt.i_type_spec,
                                                   ranges_spec)

    # check the length restriction
    stmt.i_lengths = []
    length = stmt.search_one('length')
    if (length is not None and
        'length' not in stmt.i_type_spec.restrictions()):
        err_add(ctx.errors, length.pos, 'BAD_RESTRICTION', 'length')
    elif length is not None:
        stmt.i_is_derived = True
        lengths_spec = types.validate_length_expr(ctx.errors, length)
        if lengths_spec is not None:
            stmt.i_lengths = lengths_spec[0]
            stmt.i_type_spec = types.LengthTypeSpec(stmt.i_type_spec,
                                                    lengths_spec)

    # check the pattern restrictions
    patterns = stmt.search('pattern')
    if (patterns != [] and
        'pattern' not in stmt.i_type_spec.restrictions()):
        err_add(ctx.errors, patterns[0].pos, 'BAD_RESTRICTION', 'pattern')
    elif patterns != []:
        stmt.i_is_derived = True
        pattern_specs = [types.validate_pattern_expr(ctx.errors, p)
                         for p in patterns]
        if None not in pattern_specs:
            # all patterns valid
            stmt.i_type_spec = types.PatternTypeSpec(stmt.i_type_spec,
                                                     pattern_specs)

    # check the path restriction
    path = stmt.search_one('path')
    if path is not None and stmt.arg != 'keyref':
        err_add(ctx.errors, path.pos, 'BAD_RESTRICTION', 'path')
    elif path is not None:
        stmt.i_is_derived = True
        path_spec = types.validate_path_expr(ctx.errors, path)
        if path_spec is not None:
            stmt.i_type_spec = types.PathTypeSpec(path_spec, path.pos)

    # check the base restriction
    base = stmt.search_one('base')
    if base is not None and stmt.arg != 'identityref':
        err_add(ctx.errors, base.pos, 'BAD_RESTRICTION', 'base')

    # check the enums - only applicable when the type is the builtin
    # enumeration type
    enums = stmt.search('enum')
    if enums != [] and stmt.arg != 'enumeration':
        err_add(ctx.errors, enums[0].pos, 'BAD_RESTRICTION', 'enum')
    elif stmt.arg == 'enumeration':
        stmt.i_is_derived = True
        enum_spec = types.validate_enums(ctx.errors, enums, stmt)
        if enum_spec is not None:
            stmt.i_type_spec = types.EnumerationTypeSpec(enum_spec)

    # check the bits - only applicable when the type is the builtin
    # bits type
    bits = stmt.search('bit')
    if bits != [] and stmt.arg != 'bits':
        err_add(ctx.errors, bits[0].pos, 'BAD_RESTRICTION', 'bit')
    elif stmt.arg == 'bits':
        stmt.i_is_derived = True
        bit_spec = types.validate_bits(ctx.errors, bits, stmt)
        if bit_spec is not None:
            stmt.i_type_spec = types.BitsTypeSpec(bit_spec)

    # check the union types
    membertypes = stmt.search('type')
    if membertypes != [] and stmt.arg != 'union':
        err_add(ctx.errors, membertypes[0].pos, 'BAD_RESTRICTION', 'union')
    elif membertypes == [] and stmt.arg == 'union':
        err_add(ctx.errors, stmt.pos, 'MISSING_TYPE_SPEC',
                ('union', 'type'))
    elif membertypes != []:
        stmt.i_is_derived = True
        for t in membertypes:
            if t.is_grammatically_valid == True:
                v_type_type(ctx, t)
        stmt.i_type_spec = types.UnionTypeSpec(membertypes)
        t = has_type(stmt, ['empty', 'keyref'])
        if t is not None:
            err_add(ctx.errors, stmt.pos, 'BAD_TYPE_IN_UNION', (t.arg, t.pos))
            return False
        
def v_type_leaf(ctx, stmt):
    stmt.i_default = None
    if _v_type_common_leaf(ctx, stmt) == False:
        return
    # check if we have a default value
    default = stmt.search_one('default')
    type = stmt.search_one('type')
    if default is not None and type.i_type_spec is not None :
        defval = type.i_type_spec.str_to_val(ctx.errors,
                                             default.pos,
                                             default.arg)
        stmt.i_default = defval
        if defval is not None:
            type.i_type_spec.validate(ctx.errors, default.pos,
                                      defval, ' for the default value')
    if default is not None:
        m = stmt.search_one('mandatory')
        if m is not None and m.arg == 'true':
            err_add(ctx.errors, stmt.pos, 'DEFAULT_AND_MANDATORY', ())
            return False
            

def v_type_leaf_list(ctx, stmt):
    _v_type_common_leaf(ctx, stmt)

def _v_type_common_leaf(ctx, stmt):
    stmt.i_keyrefs = [] # if this is a union, there might be several
    stmt.i_keyref_ptrs = [] # pointers to the keys the keyrefs refer to
    # check our type
    type = stmt.search_one('type')
    if type is None or type.is_grammatically_valid == False:
        # error is already reported by grammar check
        return False

    # ensure our type is validated
    v_type_type(ctx, type)

    # keep track of our keyrefs
    add_keyref_path(stmt.i_keyrefs, type)

def v_type_grouping(ctx, stmt):
    if hasattr(stmt, 'i_is_validated'):
        if stmt.i_is_validated == True:
            # this grouping has already been validated
            return
        elif stmt.i_is_validated == 'in_progress':
            err_add(ctx.errors, stmt.pos,
                    'CIRCULAR_DEPENDENCY', ('grouping', stmt.arg) )
            return

    stmt.i_is_validated = 'in_progress'
    stmt.i_is_unused = True
    stmt.i_has_i_children = True

    name = stmt.arg
    if stmt.parent.parent is not None:
        # non-top-level grouping; check if it is already defined
        pgrouping = search_grouping(stmt.parent.parent, name)
        if pgrouping is not None:
            err_add(ctx.errors, stmt.pos, 'GROUPING_ALREADY_DEFINED',
                    (name, pgrouping.pos))

    # search for circular grouping definitions
    def validate_uses(s):
        if s.keyword == "uses" and s.is_grammatically_valid == True:
            v_type_uses(ctx, s, no_error_report=True)
    iterate_stmt(stmt, validate_uses)

    stmt.i_is_validated = True

def v_type_uses(ctx, stmt, no_error_report=False):
    # Find the grouping
    name = stmt.arg
    stmt.i_grouping = None
    if name.find(":") == -1:
        prefix = None
    else:
        [prefix, name] = name.split(':', 1)
    if prefix is None or stmt.i_module.i_prefix == prefix:
        # check local groupings
        pmodule = stmt.i_module
        stmt.i_grouping = search_grouping(stmt, name)
        if stmt.i_grouping is not None and stmt.is_grammatically_valid == True:
            v_type_grouping(ctx, stmt.i_grouping)
    else:
        # this is a prefixed name, check the imported modules
        pmodule = prefix_to_module(stmt.i_module, prefix, stmt.pos, ctx.errors)
        if pmodule is None:
            return
        stmt.i_grouping = search_grouping(pmodule, name)
    if stmt.i_grouping is None and no_error_report == False:
        err_add(ctx.errors, stmt.pos,
                'GROUPING_NOT_FOUND', (name, pmodule.arg))
    if stmt.i_grouping is not None:
        stmt.i_grouping.i_is_unused = False

def v_type_augment(ctx, stmt):
    if stmt.parent == stmt.i_module:
        # this is a top-level augment, make sure the _v_i_children phases
        # run over this one
        stmt.i_has_i_children = True

def v_type_extension(ctx, stmt):
    """verify that the extension matches the extension definition"""
    (modulename, identifier) = stmt.keyword
    module = modulename_to_module(stmt.i_module, modulename)
    if module is None:
        return
    ext = module.search_one('extension', identifier)
    if ext is None:
        err_add(ctx.errors, stmt.pos, 'EXTENSION_NOT_DEFINED',
                (identifier, module.arg))
        return
    stmt.i_extension = ext
    ext_arg = ext.search_one('argument')
    if stmt.arg is not None and ext_arg is None:
        err_add(ctx.errors, stmt.pos, 'EXTENSION_ARGUMENT_PRESENT',
                identifier)
    elif stmt.arg is None and ext_arg is not None:
        err_add(ctx.errors, stmt.pos, 'EXTENSION_NO_ARGUMENT_PRESENT',
                identifier)

def v_type_feature(ctx, stmt):
    if hasattr(stmt, 'i_is_validated'):
        if stmt.i_is_validated == True:
            # this feature has already been validated
            return
        elif stmt.i_is_validated == 'in_progress':
            err_add(ctx.errors, stmt.pos,
                    'CIRCULAR_DEPENDENCY', ('feature', stmt.arg) )
            return

    stmt.i_is_validated = 'in_progress'

    name = stmt.arg

    # search for circular feature definitions
    def validate_if_feature(s):
        if s.keyword == "if-feature":
            v_type_if_feature(ctx, s, no_error_report=True)
    iterate_stmt(stmt, validate_if_feature)

    stmt.i_is_validated = True

def v_type_if_feature(ctx, stmt, no_error_report=False):
    """verify that the referenced feature exists."""
    # Find the feature
    name = stmt.arg
    stmt.i_feature = None
    if name.find(":") == -1:
        prefix = None
    else:
        [prefix, name] = name.split(':', 1)
    if prefix is None or stmt.i_module.i_prefix == prefix:
        # check local features
        pmodule = stmt.i_module
        stmt.i_feature = stmt.i_module.search_one('feature', name)
        if stmt.i_feature is not None:
            v_type_feature(ctx, stmt.i_feature)
    else:
        # this is a prefixed name, check the imported modules
        pmodule = prefix_to_module(stmt.i_module, prefix, stmt.pos, ctx.errors)
        if pmodule is None:
            return
        stmt.i_feature = pmodule.search_one('feature', name)
    if stmt.i_feature is None and no_error_report == False:
        err_add(ctx.errors, stmt.pos,
                'FEATURE_NOT_FOUND', (name, pmodule.arg))

def v_type_identity(ctx, stmt):
    if hasattr(stmt, 'i_is_validated'):
        if stmt.i_is_validated == True:
            # this identity has already been validated
            return
        elif stmt.i_is_validated == 'in_progress':
            err_add(ctx.errors, stmt.pos,
                    'CIRCULAR_DEPENDENCY', ('identity', stmt.arg) )
            return

    stmt.i_is_validated = 'in_progress'

    name = stmt.arg

    # search for circular identity definitions
    def validate_base(s):
        if s.keyword == "base":
            v_type_base(ctx, s, no_error_report=True)
    iterate_stmt(stmt, validate_base)

    stmt.i_is_validated = True

def v_type_base(ctx, stmt, no_error_report=False):
    """verify that the referenced identity exists."""
    # Find the identity
    name = stmt.arg
    stmt.i_identity = None
    if name.find(":") == -1:
        prefix = None
    else:
        [prefix, name] = name.split(':', 1)
    if prefix is None or stmt.i_module.i_prefix == prefix:
        # check local identities
        pmodule = stmt.i_module
        stmt.i_identity = stmt.i_module.search_one('identity', name)
        if stmt.i_identity is not None:
            v_type_identity(ctx, stmt.i_identity)
    else:
        # this is a prefixed name, check the imported modules
        pmodule = prefix_to_module(stmt.i_module, prefix, stmt.pos, ctx.errors)
        if pmodule is None:
            return
        stmt.i_identity = pmodule.search_one('identity', name)
    if stmt.i_identity is None and no_error_report == False:
        err_add(ctx.errors, stmt.pos,
                'IDENTITY_NOT_FOUND', (name, pmodule.arg))

    
### Expand phases

data_keywords = ['leaf', 'leaf-list', 'container', 'list', 'choice', 'case',
                 'anyxml', 'rpc', 'notification']

def v_expand_1_children(ctx, stmt):
    if (hasattr(stmt, 'is_grammatically_valid') and
        stmt.is_grammatically_valid == False):
        return
    if stmt.keyword == 'grouping' and hasattr(stmt, "i_expanded"):
        # already expanded
        return
    elif stmt.keyword == 'choice':
        shorthands = ['leaf', 'leaf-list', 'container', 'list', 'anyxml']
        for s in stmt.substmts:
            if s.keyword in shorthands:
                # create an artifical case node for the shorthand
                new_case = Statement(s.top, s.parent, s.pos, 'case', s.arg)
                v_init_stmt(ctx, new_case)
                new_child = s.copy(new_case)
                new_case.i_children = [new_child]
                new_case.i_module = s.i_module
                stmt.i_children.append(new_case)
                v_expand_1_children(ctx, new_child)
            elif s.keyword == 'case':
                stmt.i_children.append(s)
                v_expand_1_children(ctx, s)
        return
    elif stmt.keyword == 'rpc':
        input = stmt.search_one('input')
        if input is None:
            # create the implicitly defined input node
            input = Statement(stmt.top, stmt, stmt.pos, 'input', 'input')
            v_init_stmt(ctx, input)
            input.i_children = []
            input.i_module = stmt.i_module
            stmt.i_children.append(input)

        output = stmt.search_one('output')
        if output is None:
            # create the implicitly defined output node
            output = Statement(stmt.top, stmt, stmt.pos, 'output', 'output')
            v_init_stmt(ctx, output)
            output.i_children = []
            output.i_module = stmt.i_module
            stmt.i_children.append(output)

    if stmt.keyword == 'grouping':
        stmt.i_expanded = False
    for s in stmt.substmts:
        if s.keyword in ['input', 'output']:
            # must create a copy of the statement which sets the argument
            news = s.copy()
            news.i_groupings = s.i_groupings
            news.i_typedefs = s.i_typedefs
            news.arg = news.keyword
            stmt.i_children.append(news)
            v_expand_1_children(ctx, news)
        elif s.keyword == 'uses':
            v_expand_1_uses(ctx, s)
        elif s.keyword in data_keywords:
            stmt.i_children.append(s)
            v_expand_1_children(ctx, s)
        elif s.keyword in keyword_with_children:
            v_expand_1_children(ctx, s)
    if stmt.keyword == 'grouping':
        stmt.i_expanded = True
        return 'continue'
              
def v_expand_1_uses(ctx, stmt):
    if stmt.i_grouping is None:
        return
    
    # possibly expand any uses within the grouping
    v_expand_1_children(ctx, stmt.i_grouping)
    
    def find_refine_node(refinement):
        # parse the path into a list of two-tuples of (prefix,identifier)
        pstr = '/' + refinement.arg
        path = [(m[1], m[2]) \
                    for m in syntax.re_schema_node_id_part.findall(pstr)]
        node = stmt.parent
        # recurse down the path
        for (prefix, identifier) in path:
            module = prefix_to_module(stmt.i_module, prefix, refinement.pos,
                                      ctx.errors)
            if hasattr(node, 'i_children'):
                if module is None:
                    return None
                child = search_child(node.i_children, module.arg, identifier)
                if child is None:
                    err_add(ctx.errors, refinement.pos, 'NODE_NOT_FOUND',
                            (module.arg, identifier))
                    return None
                node = child
            else:
                err_add(ctx.errors, refinement.pos, 'BAD_NODE_IN_REFINE',
                        (module.arg, identifier))
                return None
        return node

    def replace_from_refinement(target, refinement, keyword, valid_keywords,
                                v_fun=None):
        new = refinement.search_one(keyword)
        if new is not None and target.keyword in valid_keywords:
            old = target.search_one(keyword)
            if old is not None:
                target.substmts.remove(old)
            if v_fun is not None:
                v_fun(target, new)
            target.substmts.append(new)
        elif new is not None:
            err_add(ctx.errors, refinement.pos, 'BAD_REFINEMENT',
                    (target.keyword, target.i_module.arg, target.arg, keyword))
            return

    # first, copy the grouping into our i_children
    for g in stmt.i_grouping.i_children:
        # don't copy the type since it cannot be modified anyway.
        # not copying the type also works better for some plugins that
        # generate output from the i_children list, e.g. the XSD plugin.
        def post_copy(old, new):
            # inline the definition into our module
            new.i_module = stmt.i_module
            new.i_children = []
            # build the i_children list of pointers
            if hasattr(old, 'i_children'):
                for x in old.i_children:
                    # check if this i_child is a pointer to a substmt
                    if x in old.substmts:
                        # if so, create an equivalent pointer
                        idx = old.substmts.index(x)
                        new.i_children.append(new.substmts[idx])
                    else:
                        # otherwise, copy the i_child
                        newx = x.copy(new, stmt.pos,
                                      nocopy=['type','uses',
                                              'typedef','grouping'],
                                      copyf=post_copy)
                        new.i_children.append(newx)
        newg = g.copy(stmt.parent, stmt.pos,
                      nocopy=['type','uses','typedef','grouping'],
                      copyf=post_copy)
        stmt.parent.i_children.append(newg)

    def v_default(target, default):
        type = target.search_one('type')
        if (type is not None and
            type.i_type_spec is not None):
            defval = type.i_type_spec.str_to_val(ctx.errors,
                                                 default.pos,
                                                 default.arg)
            if defval is not None:
                type.i_type_spec.validate(ctx.errors, default.pos,
                                          defval, ' for the default value')
    # keep track of already refined nodes
    refined = {}
    # then apply all refinements
    for refinement in stmt.search('refine'):
        target = find_refine_node(refinement)
        if target is None:
            continue
        if target in refined:
            err_add(ctx.errors, refinement.pos, 'MULTIPLE_REFINE',
                    (target.arg, refined[target]))
            continue
        refined[target] = refinement.pos
        replace_from_refinement(target, refinement, 'description',
                                ['container', 'leaf', 'leaf-list', 'list',
                                 'choice', 'case', 'anyxml'])
        replace_from_refinement(target, refinement, 'reference',
                                ['container', 'leaf', 'leaf-list', 'list',
                                 'choice', 'case', 'anyxml'])
        replace_from_refinement(target, refinement, 'config',
                                ['container', 'leaf', 'leaf-list', 'list',
                                 'choice', 'anyxml'])
        replace_from_refinement(target, refinement, 'presence',
                                ['container'])
        replace_from_refinement(target, refinement, 'must',
                                ['container', 'leaf', 'leaf-list', 'list'])
        replace_from_refinement(target, refinement, 'default',
                                ['leaf', 'choice'], v_default)
        replace_from_refinement(target, refinement, 'mandatory',
                                ['leaf', 'choice'])
        replace_from_refinement(target, refinement, 'min-elements',
                                ['leaf-list', 'list'])
        replace_from_refinement(target, refinement, 'max-elements',
                                ['leaf-list', 'list'])
        replace_from_refinement(target, refinement, 'reference',
                                ['container', 'leaf', 'leaf-list', 'list',
                                 'choice', 'case', 'anyxml'])

def v_inherit_properties_module(ctx, module):
    def iter(s, config_value, allow_explicit):
        cfg = s.search_one('config')
        if cfg is not None:
            if config_value is None and not allow_explicit:
                err_add(ctx.errors, cfg.pos, 'CONFIG_IGNORED', ())
            elif cfg.arg == 'true' and config_value == False:
                err_add(ctx.errors, cfg.pos, 'INVALID_CONFIG', ())
            elif cfg.arg == 'true':
                config_value = True
            elif cfg.arg == 'false':
                config_value = False
        s.i_config = config_value
        if (hasattr(s, 'is_grammatically_valid') and
            s.is_grammatically_valid == False):
            return
        if s.keyword in keyword_with_children:
            for ch in s.i_children:
                iter(ch, config_value, allow_explicit)

    for s in module.search('grouping'):
        iter(s, None, True)
    for s in (module.i_children + module.search('augment')):
        if s.keyword in ['rpc', 'notification']:
            iter(s, None, False)
        else:
            iter(s, True, True)

    # do not recurse in this phase
    return 'continue'

def v_expand_2_augment(ctx, stmt):
    """
    One-pass augment expansion algorithm: First observation: since we
    validate each imported module, all nodes that are augmented by
    other modules already exist.  For each node in the path to the
    target node, if it does not exist, it might get created by an
    augment later in this module.  This only applies to nodes defined
    in our namespace (since all other modules already are validated).
    For each such node, we add a temporary Statement instance, and
    store a pointer to it.  If we find such a temporary node in the
    nodes we add, we replace it with our real node, and delete it from
    the list of temporary nodes created.  When we're done with all
    augment statements, the list of temporary nodes should be empty,
    otherwise it is an error.
    """
    stmt.i_target_node = None

    # parse the path into a list of two-tuples of (prefix,identifier)
    stmt.i_path = [(m[1], m[2]) \
                   for m in syntax.re_schema_node_id_part.findall(stmt.arg)]
    # find the module of the first node in the path 
    (prefix, identifier) = stmt.i_path[0]
    module = prefix_to_module(stmt.i_module, prefix, stmt.pos, ctx.errors)
    if module is None:
        # error is reported by prefix_to_module
        return
    # find the first node
    node = search_child(module.i_children, module.arg, identifier)
    if node is None:
        # check all our submodules
        for inc in module.search('include'):
            submod = ctx.get_module(inc.arg)
            node = search_child(submod.i_children, submod.arg, identifier)
            if node is not None:
                break
        if node is None:
            err_add(ctx.errors, stmt.pos, 'NODE_NOT_FOUND',
                    (module.arg, identifier))
            return

    # then recurse down the path
    for (prefix, identifier) in stmt.i_path[1:]:
        if hasattr(node, 'i_children'):
            module = prefix_to_module(stmt.i_module, prefix, stmt.pos,
                                      ctx.errors)
            if module is None:
                return
            child = search_child(node.i_children, module.arg, identifier)
            if child is None and module == stmt.i_module:
                # create a temporary statement
                child = Statement(node.top, node, stmt.pos, '__tmp_augment__',
                                  identifier)
                v_init_stmt(ctx, child)
                child.i_module = module
                child.i_children = []
                child.i_config = node.i_config
                node.i_children.append(child)
                # keep track of this temporary statement
                stmt.i_module.i_undefined_augment_nodes[child] = child
            elif child is None:
                err_add(ctx.errors, stmt.pos, 'NODE_NOT_FOUND',
                        (module.arg, identifier))
                return
            node = child
        else:
            err_add(ctx.errors, stmt.pos, 'BAD_NODE_IN_AUGMENT',
                    (module.arg, identifier))
            return

    if not hasattr(node, 'i_children'):
        err_add(ctx.errors, stmt.pos, 'BAD_NODE_IN_AUGMENT',
                (module.arg, node.arg))
        return
        
    stmt.i_target_node = node

    # copy the expanded children into the target node
    def add_tmp_children(node, tmp_children):
        for tmp in tmp_children:
            ch = search_child(node.i_children, stmt.i_module.arg, tmp.arg)
            if ch is not None:
                del stmt.i_module.i_undefined_augment_nodes[tmp]
                if not hasattr(ch, 'i_children'):
                    err_add(ctx.errors, tmp.pos, 'BAD_NODE_IN_AUGMENT',
                            (stmt.i_module.arg, ch.arg))
                    raise Abort
                add_tmp_children(ch, tmp.i_children)
            else:
                node.i_children.append(tmp)

    for c in stmt.i_children:
        if (stmt.i_target_node.i_config == False and
            c.i_config == True):
            err_add(ctx.errors, c.pos, 'INVALID_CONFIG', ())

        ch = search_child(stmt.i_target_node.i_children, stmt.i_module.arg,
                          c.arg)
        if ch is not None:
            if ch.keyword == '__tmp_augment__':
                # replace this node with the proper one,
                # and also do this recursively
                del stmt.i_module.i_undefined_augment_nodes[ch]
                if not hasattr(c, 'i_children'):
                    err_add(ctx.errors, stmt.pos, 'BAD_NODE_IN_AUGMENT',
                            (stmt.i_module.arg, c.arg))
                    return
                idx = stmt.i_target_node.i_children.index(ch)
                stmt.i_target_node.i_children[idx] = c
                try:
                    add_tmp_children(c, ch.i_children)
                except Abort:
                    return
            else:
                err_add(ctx.errors, c.pos, 'DUPLICATE_CHILD_NAME',
                        (stmt.arg, stmt.pos, identifier, ch.pos))
                return                
        else:
            stmt.i_target_node.i_children.append(c)


### Unique name check phase

def v_unique_names_children(ctx, stmt):
    """Make sure that each child of stmt has a unique name"""

    def sort_pos(p1, p2):
        if p1.line < p2.line:
            return (p1,p2)
        else:
            return (p2,p1)

    dict = {}
    for c in stmt.i_children:
        if c.arg in dict:
            dup = dict[c.arg]
            (minpos, maxpos) = sort_pos(c.pos, dup.pos)
            pos = chk_uses_pos(c, maxpos)
            err_add(ctx.errors, pos,
                    'DUPLICATE_CHILD_NAME', (stmt.arg, stmt.pos, c.arg, minpos))
        else:
            dict[c.arg] = c
        # also check all data nodes in the cases
        if c.keyword == 'choice':
            for case in c.i_children:
                for c in case.i_children:
                    if c.arg in dict:
                        dup = dict[c.arg]
                        (minpos, maxpos) = sort_pos(c.pos, dup.pos)
                        pos = chk_uses_pos(stmt, maxpos)
                        err_add(ctx.errors, pos,
                                'DUPLICATE_CHILD_NAME',
                                (stmt.arg, stmt.pos, c.arg, minpos))
                    else:
                        dict[c.arg] = c

### Reference phase

def v_reference_list(ctx, stmt):
    def v_key():
        key = stmt.search_one('key')
        if (stmt.i_config == True) and (key is None):
            if hasattr(stmt, 'i_uses_pos'):
                err_add(ctx.errors, stmt.i_uses_pos, 'NEED_KEY_USES', (stmt.pos))
            else:
                err_add(ctx.errors, stmt.pos, 'NEED_KEY', ())

        stmt.i_key = []
        if key is not None:
            found = []
            for x in key.arg.split():
                if x == '':
                    continue
                ptr = attrsearch(x, 'arg', stmt.i_children)
                if x in found:
                    err_add(ctx.errors, key.pos, 'DUPLICATE_KEY', x)
                    return
                elif ((ptr is None) or (ptr.keyword != 'leaf')):
                    err_add(ctx.errors, key.pos, 'BAD_KEY', x)
                    return
                type = ptr.search_one('type')
                if type is not None:
                    t = has_type(type, ['empty'])
                    if t is not None:
                        err_add(ctx.errors, key.pos, 'BAD_TYPE_IN_KEY',
                                (t.arg, x))
                        return
                default = ptr.search_one('default')
                if default is not None:
                    err_add(ctx.errors, default.pos, 'KEY_HAS_DEFAULT', ())
                    
                stmt.i_key.append(ptr)
                found.append(x)

    def v_unique():
        stmt.i_unique = []
        uniques = stmt.search('unique')
        for u in uniques:
            found = []
            for expr in u.arg.split():
                if expr == '':
                    continue
                ptr = stmt
                for x in expr.split('/'):
                    if x == '':
                        continue
                    if ptr.keyword not in ['container', 'list',
                                           'choice', 'case']:
                        err_add(ctx.errors, u.pos, 'BAD_UNIQUE_PART', x)
                        return
                    ptr = attrsearch(x, 'arg', ptr.i_children)
                    if ptr is None:
                        err_add(ctx.errors, u.pos, 'BAD_UNIQUE', expr)
                        return
                if ((ptr is None) or (ptr.keyword != 'leaf')):
                    err_add(ctx.errors, u.pos, 'BAD_UNIQUE', expr)
                    return
                if ptr in found:
                    err_add(ctx.errors, u.pos, 'DUPLICATE_UNIQUE', expr)
                ptr.i_uniques.append(u)
                found.append(ptr)
            if found == []:
                err_add(ctx.errors, u.pos, 'BAD_UNIQUE', u.arg)
                return
            stmt.i_unique.append(found)

    v_key()
    v_unique()

def v_reference_leaf_keyref(ctx, stmt):
    """Verify that all keyrefs in a leaf or leaf-list have correct path"""

    for (path, pos) in stmt.i_keyrefs:
        ptr = validate_keyref_path(ctx, stmt, path, pos)
        if ptr is not None:
            stmt.i_keyref_ptrs.append((ptr, pos))
        

def v_reference_must(ctx, stmt):
    # we should do a proper parsing of the xpath expression.
    # right now, we do a conservative search for all prefixes; and
    # if we find something that looks likes a prefix, we check it in
    # order to avoid the warning about unused import, but we do not
    # report the error since it might be a false alarm.
    for (_p, prefix, _identifier) in syntax.re_keyword.findall(stmt.arg):
        prefix_to_module(stmt.i_module, prefix, stmt.pos, [])

def v_reference_when(ctx, stmt):
    # see comment in v_reference_must
    for (_p, prefix, _identifier) in syntax.re_keyword.findall(stmt.arg):
        prefix_to_module(stmt.i_module, prefix, stmt.pos, [])

### Unused definitions phase

def v_unused_module(ctx, module):
    for prefix in module.i_unused_prefixes:
        import_ = module.i_unused_prefixes[prefix]
        err_add(ctx.errors, import_.pos,
                'UNUSED_IMPORT', import_.arg)

    for s in module.i_undefined_augment_nodes:
        err_add(ctx.errors, s.pos, 'NODE_NOT_FOUND',
                (s.i_module.arg, s.arg))

def v_unused_typedef(ctx, stmt):
    if stmt.parent.parent is not None:
        # this is a locallay scoped typedef
        if stmt.i_is_unused == True:
            err_add(ctx.errors, stmt.pos,
                    'UNUSED_TYPEDEF', stmt.arg)
            
def v_unused_grouping(ctx, stmt):
    if stmt.parent.parent is not None:
        # this is a locallay scoped grouping
        if stmt.i_is_unused == True:
            err_add(ctx.errors, stmt.pos,
                    'UNUSED_GROUPING', stmt.arg)
            

### Utility functions

def chk_uses_pos(s, pos):
    if hasattr(s, 'i_uses_pos'):
        return s.i_uses_pos
    else:
        return pos

def prefix_to_modulename(module, prefix, pos, errors):
    if prefix == '':
        return module.arg
    try:
        modulename = module.i_prefixes[prefix]
    except KeyError:
        if prefix not in module.i_missing_prefixes:
            err_add(errors, pos, 'PREFIX_NOT_DEFINED', prefix)
        module.i_missing_prefixes[prefix] = True
        return None
    # remove the prefix from the unused
    if prefix in module.i_unused_prefixes:
        del module.i_unused_prefixes[prefix]
    return modulename

def prefix_to_module(module, prefix, pos, errors):
    modulename = prefix_to_modulename(module, prefix, pos, errors)
    return modulename_to_module(module, modulename)

def modulename_to_module(module, modulename):
    if modulename == module.arg:
        return module
    # even if the prefix is defined, the module might not be
    # loaded; the load might have failed
    try:
        module = module.i_ctx.modules[modulename]
    except KeyError:
        return None
    return module

def has_type(type, names):
    """Return type with name if `type` has name as one of its base types,
    and name is in the `names` list.  otherwise, return None."""
    if type.arg in names:
        return type
    for t in type.search('type'): # check all union's member types
        r = has_type(t, names)
        if r is not None:
            return r
    if type.i_typedef is not None and type.i_typedef.i_is_circular == False:
        t = type.i_typedef.search_one('type')
        if t is not None:
            return has_type(t, names)
    return None


def search_child(children, modulename, identifier):
    for child in children:
        if ((child.arg == identifier) and
            (child.i_module.arg == modulename)):
            return child
    return None

def search_data_node(children, modulename, identifier):
    for child in children:
        if child.keyword in ['choice', 'case']:
            r = search_data_node(child.i_children,
                                 modulename, identifier)
            if r is not None:
                return r
        elif ((child.arg == identifier) and
              (child.i_module.arg == modulename)):
            return child
    return None

def search_typedef(stmt, name):
    while stmt is not None:
        if name in stmt.i_typedefs:
            return stmt.i_typedefs[name]
        if stmt.parent == None: # module or submodule
            for i in stmt.search('include'):
                modulename = i.arg
                m = stmt.i_ctx.get_module(modulename)
                if m is not None and name in m.i_typedefs:
                    return m.i_typedefs[name]
        stmt = stmt.parent
    return None

def search_grouping(stmt, name):
    while stmt is not None:
        if name in stmt.i_groupings:
            return stmt.i_groupings[name]
        if stmt.parent == None: # module or submodule
            for i in stmt.search('include'):
                modulename = i.arg
                m = stmt.i_ctx.get_module(modulename)
                if m is not None and name in m.i_groupings:
                    return m.i_groupings[name]
        stmt = stmt.parent
    return None

def iterate_stmt(stmt, f):
    def _iterate(stmt):
        res = f(stmt)
        if res == 'stop':
            raise Abort
        elif res == 'continue':
            pass
        else:
            # default is to recurse
            for s in stmt.substmts:
                _iterate(s)

    try:
        _iterate(stmt)
    except Abort:
        pass

def add_keyref_path(keyrefs, type_):
    type_spec = type_.i_type_spec
    if type(type_spec) == types.PathTypeSpec:
        keyrefs.append((type_spec.path, type_spec.pos))
    if type(type_spec) == types.UnionTypeSpec:
        for t in type_spec.types: # union
            add_keyref_path(keyrefs, t)

def validate_keyref_path(ctx, stmt, path, pathpos):
    def find_identifier(identifier):
        if util.is_prefixed(identifier):
            (prefix, name) = identifier
            pmodule = prefix_to_module(stmt.i_module, prefix, stmt.pos,
                                       ctx.errors)
            if pmodule is None:
                raise NotFound
            return (pmodule, name)
        else: # local identifier
            return (stmt.i_module, identifier)

    def is_identifier(x):
        if util.is_local(x):
            return True
        if type(x) == type(()) and len(x) == 2:
            return True
        return False

    def is_predicate(x):
        if type(x) == type(()) and len(x) == 4 and x[0] == 'predicate':
            return True
        return False
    
    def follow_path(ptr, up, dn):
        if up == -1: # absolute path
            (pmodule, name) = find_identifier(dn[0])
            ptr = search_child(pmodule.i_children, pmodule.arg, name)
            if ptr is None:
                err_add(ctx.errors, pathpos, 'KEYREF_IDENTIFIER_NOT_FOUND',
                        (pmodule.arg, name, stmt.arg, stmt.pos))
                raise NotFound
            dn = dn[1:]
        else:
            while up > 0:
                if ptr is None or ptr.keyword == 'grouping':
                    err_add(ctx.errors, pathpos, 'KEYREF_TOO_MANY_UP',
                            (stmt.arg, stmt.pos))
                    raise NotFound
                ptr = ptr.parent
                up = up - 1
        i = 0
        key_list = None
        keys = []
        while i < len(dn):
            if is_identifier(dn[i]) == True:
                (pmodule, name) = find_identifier(dn[i])
                module_name = pmodule.arg
            elif ptr.keyword == 'list': # predicate on a list, good
                key_list = ptr
                keys = []
                # check each predicate
                while i < len(dn) and is_predicate(dn[i]) == True:
                    # unpack the predicate
                    (_tag, keyleaf, pup, pdn) = dn[i]
                    (pmodule, pname) = find_identifier(keyleaf)
                    # make sure the keyleaf is really a key in the list
                    pleaf = search_child(ptr.i_key, pmodule.arg, pname)
                    if pleaf is None:
                        err_add(ctx.errors, pathpos, 'KEYREF_NO_KEY',
                                (pmodule.arg, pname, stmt.arg, stmt.pos))
                        raise NotFound
                    # make sure it's not already referenced
                    if keyleaf in keys:
                        err_add(ctx.errors, pathpos, 'KEYREF_MULTIPLE_KEYS',
                                (pmodule.arg, pname, stmt.arg, stmt.pos))
                        raise NotFound
                    keys.append((pmodule.arg, pname))
                    # check what this predicate refers to; make sure it's
                    # another leaf; either of type keyref to keyleaf, OR same
                    # type as the keyleaf
                    (xkey_list, x_key, xleaf) = follow_path(stmt, pup, pdn)
                    if xleaf.i_keyref_ptrs == []:
                        err_add(ctx.errors, pathpos, 'KEYREF_BAD_PREDICATE_PTR',
                                (pmodule.arg, pname, stmt.arg, stmt.pos))
                    for (xptr, xpos) in xleaf.i_keyref_ptrs:
                        if xptr != pleaf:
                            err_add(ctx.errors, xpos,
                                    'KEYREF_BAD_PREDICATE_PTR',
                                    (pmodule.arg, pname, stmt.arg, stmt.pos))
                            raise NotFound
                    i = i + 1
                continue
            else:
                err_add(ctx.errors, pathpos, 'KEYREF_BAD_PREDICATE',
                        (ptr.i_module.arg, ptr.arg, stmt.arg, stmt.pos))
                raise NotFound
            if ptr.keyword in ['list', 'container', 'case', 'grouping',
                               'module', 'submodule']:
                ptr = search_data_node(ptr.i_children, module_name, name)
                if ptr is None:
                    err_add(ctx.errors, pathpos, 'KEYREF_IDENTIFIER_NOT_FOUND',
                            (module_name, name, stmt.arg, stmt.pos))
                    raise NotFound
            else:
                err_add(ctx.errors, pathpos, 'KEYREF_IDENTIFIER_BAD_NODE',
                        (module_name, name, stmt.arg, stmt.pos,
                         util.keyword_to_str(ptr.keyword)))
                raise NotFound
            i = i + 1
        return (key_list, keys, ptr)

    try:
        if path is None: # e.g. invalid path
            return None
        (up, dn) = path
        (key_list, keys, ptr) = follow_path(stmt, up, dn)
        # ptr is now the node that the keyref path points to
        # check that it is a key in a list
        if not (ptr.keyword == 'leaf' and
                ptr.parent.keyword == 'list' and
                ptr in ptr.parent.i_key):
            err_add(ctx.errors, pathpos, 'KEYREF_NOT_LEAF_KEY',
                    (stmt.arg, stmt.pos))
            return None
        if key_list == ptr.parent and (ptr.i_module.arg, ptr.arg) in keys:
            err_add(ctx.errors, pathpos, 'KEYREF_MULTIPLE_KEYS',
                    (ptr.i_module.arg, ptr.arg, stmt.arg, stmt.pos))
        if stmt.i_config == True and ptr.i_config == False:
            err_add(ctx.errors, pathpos, 'KEYREF_BAD_CONFIG',
                    (stmt.arg, stmt.pos))
        return ptr
    except NotFound:
        return None

### structs used to represent a YANG module

## Each statement in YANG is represented as an instance of Statement.

class Statement(object):
    def __init__(self, top, parent, pos, keyword, arg=None):
        self.top = top
        """pointer to the top-level Statement"""

        self.parent = parent
        """pointer to the parent Statement"""

        self.pos = copy.copy(pos)
        """position in input strea, for error reporting"""

        self.raw_keyword = keyword
        """the name of the statement
        one of: string() | (prefix::string(), string())"""

        self.keyword = keyword
        """the name of the statement
        one of: string() | (modulename::string(), string())"""

        self.ext_mod = None
        """the name of the module where the extension is defined, if any"""

        self.arg = arg
        """the statement's argument;  a string or None"""
        
        self.substmts = []
        """the statement's substatements; a list of Statements"""

    def search(self, keyword=None, arg=None):
        """Return list of receiver's substmts with `keyword` and/or `arg`.

        If `keyword` is ``None``, only the following substatements are
        taken into account: ``leaf``, ``leaf-list``, ``list``,
        ``container``, ``choice``, ``rpc``, ``notification``.
        """
        if arg is None:
            return [ ch for ch in self.substmts if ch.keyword == keyword ]
        elif keyword is None:
            kws = ["leaf", "leaf-list", "list", "container",
                   "choice", "rpc", "notification"]
        else:                   # both specified
            kws = [keyword]
        return [ ch for ch in self.substmts
                 if ch.keyword in kws and ch.arg == arg ]

    def search_one(self, keyword, arg=None):
        """Return receiver's substmt with `keyword` and optionally `arg`.
        """
        for ch in self.substmts:
            if ch.keyword == keyword and (arg is None or ch.arg == arg):
                return ch
        return None

    def copy(self, parent=None, uses_pos=None, nocopy=[], ignore=[], copyf=None):
        new = copy.copy(self)
        if uses_pos is not None:
            new.i_uses_pos = uses_pos
        if parent == None:
            new.parent = self.parent
        else:
            new.parent = parent
        new.substmts = []
        for s in self.substmts:
            if s.keyword in ignore:
                pass
            elif s.keyword in nocopy:
                new.substmts.append(s)
            else:
                new.substmts.append(s.copy(new, uses_pos, nocopy, ignore, copyf))
        if copyf is not None:
            copyf(self, new)
        return new

    # FIXME: remove / rewrite
    def full_path(self):
        """Return full path of the receiver.

        This function makes sense mostly for definition statements
        ('typedef' and 'grouping'). The returned value is a list of
        data tree node identifiers containing receiver's argument and
        arguments of all ancestor statements up to but not including
        'module' or 'submodule' (in reverse order).
        """
        path = [self.arg]
        node = self.parent
        while node.parent is not None:
            path.insert(0, node.arg)
            node = node.parent
        return path

    def pprint(self, indent='', f=None):
        print indent + self.__class__.__name__ + " " + self.arg
        if f is not None:
             f(self, indent)
        for x in self.substmts:
            x.pprint(indent + ' ', f)

## FIXME: not used
def validate_status(errors, x, y, defn, ref):
    xstatus = x.status
    if xstatus is None:
        xstatus = 'current'
    ystatus = y.status
    if ystatus is None:
        ystatus = 'current'
    if xstatus == 'current' and ystatus == 'deprecated':
        err_add(x.pos, 'CURRENT_USES_DEPRECATED', (defn, ref))
    elif xstatus == 'current' and ystatus == 'obsolete':
        err_add(x.pos, 'CURRENT_USES_OBSOLETE', (defn, ref))
    elif xstatus == 'deprecated' and ystatus == 'obsolete':
        err_add(x.pos, 'DEPRECATED_USES_OBSOLETE', (defn, ref))
