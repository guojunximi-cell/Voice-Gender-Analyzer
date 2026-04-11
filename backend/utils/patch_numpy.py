import numpy as np


def patch_numpy():
    # numpy 2.x made np.stack/vstack/hstack reject generators; patch them early
    # so librosa/pyannote/inaSpeechSegmenter code that passes generator
    # expressions still works.  Root cause: pyannote viterbi.py calls
    # np.vstack(generator_expr) at lines 86 and 95.
    _orig_np_stack = np.stack
    _orig_np_vstack = np.vstack
    _orig_np_hstack = np.hstack

    def _np_stack_compat(arrays, *args, **kwargs):
        if not isinstance(arrays, (list, tuple)):
            arrays = list(arrays)
        return _orig_np_stack(arrays, *args, **kwargs)

    def _np_vstack_compat(tup, *args, **kwargs):
        if not isinstance(tup, (list, tuple)):
            tup = list(tup)
        return _orig_np_vstack(tup, *args, **kwargs)

    def _np_hstack_compat(tup, *args, **kwargs):
        if not isinstance(tup, (list, tuple)):
            tup = list(tup)
        return _orig_np_hstack(tup, *args, **kwargs)

    np.stack = _np_stack_compat
    np.vstack = _np_vstack_compat
    np.hstack = _np_hstack_compat
