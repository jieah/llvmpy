from binding import *
from namespace import llvm
from Module import Module
from JITMemoryManager import JITMemoryManager
from CodeGen import CodeGenOpt, Reloc, CodeModel
from StringRef import StringRef
from ExecutionEngine import ExecutionEngine
from TargetMachine import TargetMachine
from Triple import Triple

EngineBuilder = llvm.Class()

@llvm.Class() # a fake class (actually a namespace)
class EngineKind:
    Kind = Enum('JIT', 'Interpreter')

@EngineBuilder
class EngineBuilder:
    new = Constructor(ownedptr(Module))
    delete = Destructor()

    def _setter(*args):
        return Method(ref(EngineBuilder), *args)

    setEngineKind = _setter(EngineKind.Kind)
    setJITMemoryManager = _setter(ptr(JITMemoryManager))

    setErrorStr = CustomMethod('EngineBuilder_setErrorStr',
                                PyObjectPtr, PyObjectPtr)

    setOptLevel = _setter(CodeGenOpt.Level)
    #setTargetOptions =
    setRelocationModel = _setter(Reloc.Model)
    setCodeModel = _setter(CodeModel.Model)
    setAllocateGVsWithCode = _setter(cast(bool, Bool))
    setMArch = _setter(cast(str, StringRef))
    setMCPU = _setter(cast(str, StringRef))
    setUseMCJIT = _setter(cast(bool, Bool))
    _setMAttrs = CustomMethod('EngineBuilder_setMAttrs',
                              PyObjectPtr, PyObjectPtr)
    @CustomPythonMethod
    def setMAttrs(self, attrs):
        attrlist = list(str(a) for a in attrs)
        return self._setMAttrs(attrlist)

    create = Method(ptr(ExecutionEngine),
                    ownedptr(TargetMachine)).require_only(0)

    _selectTarget0 = Method(ptr(TargetMachine))
    _selectTarget0.realname = 'selectTarget'

    _selectTarget1 = CustomMethod('EngineBuilder_selectTarget',
                                 const(ref(Triple)), cast(str, StringRef),
                                 cast(str, StringRef), PyObjectPtr),

    @CustomPythonMethod
    def selectTarget(self, *args):
        if not args:
            return self._selectTarget0()
        else:
            return self._selectTarget1(*args)

