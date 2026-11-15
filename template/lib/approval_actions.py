"""One explicit registry for all processes that execute approved actions."""
import importlib
import os
import importlib.util
import threading

_lock = threading.Lock()
_loaded = False


def load_all(*, profile=None):
    global _loaded
    with _lock:
        if (profile or os.environ.get('ILSON_PROFILE')) == 'course':
            import approval_dispatch
            approval_dispatch.register()
            return
        if _loaded:
            return
        import approval_dispatch
        approval_dispatch.register()
        # The Q&A feature is optional until integrated; do not mask its import errors.
        if importlib.util.find_spec('replies_dispatch') is not None:
            importlib.import_module('replies_dispatch').register()
        _loaded = True
