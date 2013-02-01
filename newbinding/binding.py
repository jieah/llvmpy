import inspect, textwrap
import functools
import codegen as cg

_rank = 0
namespaces = {}

RESERVED = frozenset(['None'])

class Namespace(object):
    def __init__(self, name):
        self.name = name
        self.enums = []
        self.classes = []
        self.functions = []
        self.includes = set()
        namespaces[name] = self

    def Class(self, *bases):
        cls = Class(self, *bases)
        self.classes.append(cls)
        return cls

    def Function(self, *args):
        fn = Function(self, *args)
        self.functions.append(fn)
        return fn

    def Enum(self, name, *value_names):
        enum = Enum(*value_names)
        enum.parent = self
        enum.name = name
        self.enums.append(enum)
        return enum

    @property
    def fullname(self):
        return self.name

    def __str__(self):
        return self.name

class _Type(object):
    pass

class BuiltinTypes(_Type):
    def __init__(self, name):
        self.name = name

    @property
    def fullname(self):
        return self.name

    def wrap(self, writer, var):
        return var

    def unwrap(self, writer, var):
        return var

Void = BuiltinTypes('void')
Unsigned = BuiltinTypes('unsigned')
UnsignedLongLong = BuiltinTypes('unsigned long long') # used in llvm-3.2
LongLong = BuiltinTypes('long long')
Float = BuiltinTypes('float')
Double = BuiltinTypes('double')
Uint64 = BuiltinTypes('uint64_t')
Size_t = BuiltinTypes('size_t')
VoidPtr = BuiltinTypes('void*')
Bool = BuiltinTypes('bool')
StdString = BuiltinTypes('std::string')
ConstStdString = BuiltinTypes('const std::string')
ConstCharPtr = BuiltinTypes('const char*')
PyObjectPtr = BuiltinTypes('PyObject*')
PyObjectPtr.format='O'

class Class(_Type):
    format = 'O'

    def __init__(self, ns, *bases):
        self.ns = ns
        self.bases = bases
        self._is_defined = False
        self.methods = []
        self.pymethods = []
        self.enums = []
        self.includes = set()
        self.downcastables = set()

    def __call__(self, defn):
        assert not self._is_defined
        # process the definition in "defn"
        self.name = defn.__name__
        for k, v in defn.__dict__.items():
            if isinstance(v, Method):
                self.methods.append(v)
                if isinstance(v, Constructor):
                    for sig in v.signatures:
                        sig[0] = ptr(self)
                v.name = k
                v.parent = self
            elif isinstance(v, Enum):
                self.enums.append(v)
                v.name = k
                v.parent = self
                setattr(self, k, v)
            elif isinstance(v, CustomPythonMethod):
                self.pymethods.append(v)
            elif k == '_include_':
                if isinstance(v, str):
                    self.includes.add(v)
                else:
                    for i in v:
                        self.includes.add(i)
            elif k == '_realname_':
                self.realname = v
            elif k == '_downcast_':
                if isinstance(v, Class):
                    self.downcastables.add(v)
                else:
                    for i in v:
                        self.downcastables.add(i)
        return self

    def compile_cpp(self, writer):
        # generate methods
        for meth in self.methods:
            meth.compile_cpp(writer)

        # generate method table
        writer.println('static')
        writer.println('PyMethodDef %s[] = {' % cg.mangle(self.fullname))
        with writer.indent():
            fmt = '{ "%(name)s", (PyCFunction)%(func)s, METH_VARARGS, NULL },'
            for meth in self.methods:
                name = meth.name
                func = meth.c_name
                writer.println(fmt % locals())
            writer.println('{ NULL },')
        writer.println('};')
        writer.println()

    def compile_py(self, writer):
        clsname = self.name
        bases = 'capsule.Wrapper'
        if self.bases:
            bases = ', '.join(x.name for x in self.bases)
        writer.println('@capsule.register_class("%s")' % self.fullname)
        with writer.block('class %(clsname)s(%(bases)s):' % locals()):
            writer.println('_llvm_type_ = "%s"' % self.fullname)
            for enum in self.enums:
                enum.compile_py(writer)
            for meth in self.methods:
                meth.compile_py(writer)
            for meth in self.pymethods:
                meth.compile_py(writer)
        writer.println()

    @property
    def capsule_name(self):
        if self.bases:
            return self.bases[-1].capsule_name
        else:
            return self.fullname

    @property
    def fullname(self):
        try:
            name = self.realname
        except AttributeError:
            name = self.name
        return '::'.join([self.ns.fullname, name])

    def __str__(self):
        return self.fullname

    def unwrap(self, writer, val):
        fmt = 'PyCapsule_GetPointer(%(val)s, "%(name)s")'
        name = self.capsule_name
        raw = writer.declare('void*', fmt % locals())
        writer.die_if_false(raw)
        ptrty = ptr(self).fullname
        ty = self.fullname
        fmt = 'typecast<%(ty)s >::from(%(raw)s)'
        casted = writer.declare(ptrty, fmt % locals())
        writer.die_if_false(casted)
        return casted

    def wrap(self, writer, val):
        copy = 'new %s(%s)' % (self.fullname, val)
        return writer.pycapsule_new(copy, self.capsule_name, self.fullname)


class Enum(object):
    format = 'O'
    
    def __init__(self, *value_names):
        self.parent = None
        self.value_names = value_names
        self.includes = set()

    @property
    def fullname(self):
        try:
            name = self.realname
        except AttributeError:
            name = self.name
        return '::'.join([self.parent.fullname, name])

    def __str__(self):
        return self.fullname

    def wrap(self, writer, val):
        ret = writer.declare('PyObject*', 'NULL')
        with writer.block('switch(%s) ' % val):
            for v in self.value_names:
                writer.println('case %s::%s:' % (self.parent, v))
                with writer.indent():
                    fmt = '%(ret)s = PyString_FromString("%(v)s");'
                    writer.println(fmt % locals())
                    writer.println('break;')
            else:
                writer.println('default:')
                with writer.indent():
                    writer.raises(ValueError, 'Invalid enum %s' % v)
        return ret

    def unwrap(self, writer, val):
        tostring = 'PyString_AsString(%(val)s)' % locals()
        string = writer.declare('const char*', tostring)
        ret = writer.declare('%s::%s' % (self.parent, self.name))
        parent = self.parent
        iffmt = 'if (string_equal(%(string)s, "%(v)s"))'
        for i, v in enumerate(self.value_names):
            with writer.block(iffmt % locals()):
                fmt = '%(ret)s = %(parent)s::%(v)s;'
                writer.println(fmt % locals())
            if i == 0:
                iffmt = 'else ' + iffmt
        with writer.block('else'):
            writer.raises(ValueError, 'Invalid enum.')
        return ret

    def compile_cpp(self, writer):
        pass

    def compile_py(self, writer):
        with writer.block('class %s:' % self.name):
            writer.println('_llvm_type_ = "%s"' % self.fullname)
            for v in self.value_names:
                if v in RESERVED:
                    k = '%s_' % v
                else:
                    k = v
                writer.println('%(k)s = "%(v)s"' % locals())
        writer.println()

class Method(object):
    _kind_ = 'meth'

    def __init__(self, return_type=Void, *args):
        self.parent = None
        self.signatures = []
        self.includes = set()
        self._add_signature(return_type, *args)

    def _add_signature(self, return_type, *args):
        prev_lens = set(map(len, self.signatures))
        cur_len = len(args) + 1
        if cur_len in prev_lens:
            raise Exception('Only support overloading with different number'
                            ' of arguments')
        self.signatures.append([return_type] + list(args))

    def __ior__(self, method):
        assert type(self) is type(method)
        for sig in method.signatures:
            self._add_signature(sig[0], *sig[1:])
        return self

    @property
    def fullname(self):
        return '::'.join([self.parent.fullname, self.realname])

    @property
    def realname(self):
        try:
            return self.__realname
        except AttributeError:
            return self.name

    @realname.setter
    def realname(self, v):
        self.__realname = v

    @property
    def c_name(self):
        return cg.mangle("%s_%s" % (self.parent, self.name))

    def __str__(self):
        return self.fullname

    def compile_cpp(self, writer):
        with writer.py_function(self.c_name):
            if len(self.signatures) == 1:
                sig = self.signatures[0]
                retty = sig[0]
                argtys = sig[1:]
                self.compile_cpp_body(writer, retty, argtys)
            else:
                nargs = writer.declare('Py_ssize_t', 'PyTuple_Size(args)')
                for sig in self.signatures:
                    retty = sig[0]
                    argtys = sig[1:]
                    expect = len(argtys)
                    if (not isinstance(self, StaticMethod) and
                        isinstance(self.parent, Class)):
                        # Is a instance method, add 1 for "this".
                        expect += 1
                    with writer.block('if (%(expect)d == %(nargs)s)' % locals()):
                        self.compile_cpp_body(writer, retty, argtys)
                writer.raises(TypeError, 'Invalid number of args')

    def compile_cpp_body(self, writer, retty, argtys):
        args = writer.parse_arguments('args', ptr(self.parent), *argtys)
        ret = writer.method_call(self.realname, retty.fullname, *args)
        writer.return_value(retty.wrap(writer, ret))

    def compile_py(self, writer):
        decl = writer.function(self.name, args=('self',), varargs='args')
        with decl as (this, varargs):
            unwrap_this = writer.unwrap(this)
            unwrapped = writer.unwrap_many(varargs)
            self.process_ownedptr_args(writer, unwrapped)
            
            func = '.'.join([self.parent.name, self.name])
            ret = writer.call('_api.%s' % func,
                              args=(unwrap_this,), varargs=unwrapped)

            wrapped = writer.wrap(ret, self.is_return_ownedptr())

            writer.return_value(wrapped)
            writer.println()

    def require_only(self, num):
        '''Require only "num" of argument.
        '''
        assert len(self.signatures) == 1
        sig = self.signatures[0]
        ret = sig[0]
        args = sig[1:]
        arg_ct = len(args)

        for i in range(num, arg_ct):
            self._add_signature(ret, *args[:i])

        return self

    def is_return_ownedptr(self):
        retty = self.signatures[0][0]
        return isinstance(retty, ownedptr)
    
    def process_ownedptr_args(self, writer, unwrapped):
        argtys = self.signatures[0][1:]
        for i, ty in enumerate(argtys):
            if isinstance(ty, ownedptr):
                with writer.block('if len(%s) > %d:' % (unwrapped, i)):
                    writer.release_ownership('%s[%d]' % (unwrapped, i))

class CustomMethod(Method):
    def __init__(self, methodname, retty, *argtys):
        super(CustomMethod, self).__init__(retty, *argtys)
        self.methodname = methodname

    def compile_cpp_body(self, writer, retty, argtys):
        args = writer.parse_arguments('args', ptr(self.parent), *argtys)
        ret = writer.call(self.methodname, retty.fullname, *args)
        writer.return_value(retty.wrap(writer, ret))

        
class StaticMethod(Method):

    def compile_cpp_body(self, writer, retty, argtys):
        assert isinstance(self.parent, Class)
        args = writer.parse_arguments('args', *argtys)
        ret = self.compile_cpp_call(writer, retty, args)
        writer.return_value(retty.wrap(writer, ret))

    def compile_cpp_call(self, writer, retty, args):
        ret = writer.call(self.fullname, retty.fullname, *args)
        return ret

    def compile_py(self, writer):
        writer.println('@staticmethod')
        decl = writer.function(self.name, varargs='args')
        with decl as varargs:
            unwrapped = writer.unwrap_many(varargs)
            self.process_ownedptr_args(writer, unwrapped)
            
            func = '.'.join([self.parent.name, self.name])
            ret = writer.call('_api.%s' % func, varargs=unwrapped)
            wrapped = writer.wrap(ret, self.is_return_ownedptr())
            writer.return_value(wrapped)
            writer.println()

class CustomStaticMethod(StaticMethod):
    def __init__(self, methodname, retty, *argtys):
        super(CustomStaticMethod, self).__init__(retty, *argtys)
        self.methodname = methodname

    def compile_cpp_body(self, writer, retty, argtys):
        args = writer.parse_arguments('args', *argtys)
        ret = writer.call(self.methodname, retty.fullname, *args)
        writer.return_value(retty.wrap(writer, ret))

class Function(Method):
    _kind_ = 'func'

    def __init__(self, parent, name, return_type=Void, *args):
        super(Function, self).__init__(return_type, *args)
        self.parent = parent
        self.name = name

    def compile_cpp_body(self, writer, retty, argtys):
        args = writer.parse_arguments('args', *argtys)
        ret = writer.call(self.fullname, retty.fullname, *args)
        writer.return_value(retty.wrap(writer, ret))

    def compile_py(self, writer):
        with writer.function(self.name, varargs='args') as varargs:
            unwrapped = writer.unwrap_many(varargs)
            self.process_ownedptr_args(writer, unwrapped)
            func = self.fullname.split('::', 1)[1].replace('::', '.')
            ret = writer.call('_api.%s' % func,
                              varargs=unwrapped)
            wrapped = writer.wrap(ret, self.is_return_ownedptr())
            writer.return_value(wrapped)
        writer.println()

class Destructor(Method):
    _kind_ = 'dtor'

    def __init__(self):
        super(Destructor, self).__init__()

    def compile_cpp_body(self, writer, retty, argtys):
        assert isinstance(self.parent, Class)
        assert not argtys
        args = writer.parse_arguments('args', ptr(self.parent), *argtys)
        writer.println('delete %s;' % args[0])
        writer.return_value(None)

    def compile_py(self, writer):
        func = '.'.join([self.parent.name, self.name])
        writer.println('_delete_ = _api.%s' % func)


class Constructor(StaticMethod):
    _kind_ = 'ctor'

    def __init__(self, *args):
        super(Constructor, self).__init__(Void, *args)

    def compile_cpp_call(self, writer, retty, args):
        alloctype = retty.fullname.rstrip(' *')
        arglist = ', '.join(args)
        stmt = 'new %(alloctype)s(%(arglist)s)' % locals()
        ret = writer.declare(retty.fullname, stmt)
        return ret

class ref(_Type):
    def __init__(self, element):
        assert isinstance(element, Class), type(element)
        self.element = element
        self.const = False

    def __str__(self):
        return self.fullname

    @property
    def fullname(self):
        if self.const:
            return 'const %s&' % self.element.fullname
        else:
            return '%s&' % self.element.fullname

    @property
    def capsule_name(self):
        return self.element.capsule_name

    @property
    def format(self):
        return self.element.format

    def wrap(self, writer, val):
        p = writer.declare(const(ptr(self.element)).fullname, '&%s' % val)
        return writer.pycapsule_new(p, self.capsule_name, self.element.fullname)

    def unwrap(self, writer, val):
        p = self.element.unwrap(writer, val)
        return writer.declare(self.fullname, '*%s' % p)


class ptr(_Type):
    def __init__(self, element):
        assert isinstance(element, Class)
        self.element = element
        self.const = False

    @property
    def fullname(self):
        if self.const:
            return 'const %s*' % self.element
        else:
            return '%s*' % self.element

    @property
    def format(self):
        return self.element.format

    def unwrap(self, writer, val):
        ret = writer.declare(self.fullname, 'NULL')
        with writer.block('if (%(val)s != Py_None)' % locals()):
            val = self.element.unwrap(writer, val)
            writer.println('%(ret)s = %(val)s;' % locals())
        return ret

    def wrap(self, writer, val):
        return writer.pycapsule_new(val, self.element.capsule_name,
                                    self.element.fullname)

class ownedptr(ptr):
    pass

def const(ptr_or_ref):
    ptr_or_ref.const = True
    return ptr_or_ref

class cast(_Type):
    format = 'O'

    def __init__(self, original, target):
        self.original = original
        self.target = target

    @property
    def fullname(self):
        return self.binding_type.fullname

    @property
    def python_type(self):
        if not isinstance(self.target, _Type):
            return self.target
        else:
            return self.original

    @property
    def binding_type(self):
        if isinstance(self.target, _Type):
            return self.target
        else:
            return self.original

    def wrap(self, writer, val):
        dst = self.python_type.__name__
        return writer.call('py_%(dst)s_from' % locals(), 'PyObject*', val)

    def unwrap(self, writer, val):
        src = self.python_type.__name__
        dst = self.binding_type.fullname
        ret = writer.declare(dst)
        status = writer.call('py_%(src)s_to' % locals(), 'int', val, ret)
        writer.die_if_false(status)
        return ret


class CustomPythonMethod(object):
    def __init__(self, fn):
        src = inspect.getsource(fn)
        lines = textwrap.dedent(src).splitlines()
        for i, line in enumerate(lines):
            if not line.startswith('@'):
                break
        self.sourcelines = lines[i:]

    def compile_py(self, writer):
        for line in self.sourcelines:
            writer.println(line)

class CustomPythonStaticMethod(CustomPythonMethod):
    def compile_py(self, writer):
        writer.println('@staticmethod')
        super(CustomPythonStaticMethod, self).compile_py(writer)

