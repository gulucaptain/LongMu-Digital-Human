"""运行上下文：并行线程/调用使用各自配置，不改写模块全局变量。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from longmu.config import RuntimeConfig

@dataclass
class RunContext:
    config: RuntimeConfig

_current = ContextVar('longmu_context', default=None)
_default = RunContext(RuntimeConfig())

def current_context():
    return _current.get() or _default

@contextmanager
def use_context(context):
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)

class SettingsView:
    """迁移期内部视图，读取当前RunContext；方便保留现有推理与测试行为。"""
    def __getattr__(self,name):
        return getattr(current_context().config,name)
    def __setattr__(self,name,value):
        setattr(current_context().config,name,value)
    def __delattr__(self,name):
        delattr(current_context().config,name)

settings = SettingsView()
