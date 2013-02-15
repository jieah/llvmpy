from binding import *
from namespace import llvm
from ADT.StringRef import StringRef
from Module import Module
from LLVMContext import LLVMContext

llvm.includes.add('llvm/Linker.h')

Linker = llvm.Class()

@Linker
class Linker:
    ControlFlags = Enum('Verbose, QuietWarnings, QuietErrors')
    LinkerMode = Enum('DestroySource, PreserveSource')

    _new_w_empty = Constructor(cast(str, StringRef),
                               cast(str, StringRef),
                               ref(LLVMContext),
                               cast(int, Unsigned)).require_only(3)

    _new_w_existing = Constructor(cast(str, StringRef),
                                  ptr(Module),
                                  cast(int, Unsigned)).require_only(2)

    @CustomPythonStaticMethod
    def new(progname, module_or_name, *args):
        if isinstance(module_or_name, Module):
            return _new_w_existing(progname, module_or_name, *args)
        else:
            return _new_w_empty(progname, module_or_name, *args)

    delete = Destructor()

    getModule = Method(ptr(Module))
    releaseModule = Method(ptr(Module))
    getLastError = Method(cast(ConstStdString, str))

    LinkInModule = CustomMethod('Linker_LinkInModule',
                                PyObjectPtr, # boolean
                                ptr(Module),
                                PyObjectPtr, # errmsg
                                )

    LinkModules = CustomStaticMethod('Linker_LinkModules',
                                     PyObjectPtr, # boolean
                                     ptr(Module),
                                     ptr(Module),
                                     LinkerMode,
                                     PyObjectPtr, # errsg
                                     )
