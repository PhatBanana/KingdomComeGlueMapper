"""Float macro texture bakes in worker processes shared by one build.

A fixed-outfit conversion bakes about twenty 2048px textures, which took half
of each NPC's import when run one after another on the main thread. The pool
starts on first use and is reused by every later conversion; callers that
finish a batch call release() so its workers do not idle through the rest of
the build (atexit covers the rest).
"""
import atexit
from concurrent.futures import ProcessPoolExecutor, wait as wait_for
import copy

from bounded_pool import worker_count
from character_native_materials import bake_float_dds

_POOL = None


def pool():
    global _POOL
    if _POOL is None:
        # A 2048px bake holds several float32 RGBA copies and its mips.
        _POOL = ProcessPoolExecutor(max_workers=worker_count(16, 768 * 1024**2, 'GLUEMAPPER_BAKE_WORKERS'))
        atexit.register(release)
    return _POOL


def release():
    global _POOL
    if _POOL is not None:
        _POOL.shutdown()
        _POOL = None


class Bakes:
    """One conversion's deferred bakes; wait() must run before its outputs are read.

    Matches the bake(path, image, material, specular=None) callback of
    convert_character_materials. Arguments are copied because they are pickled
    after submit() and the caller may reuse the images. Use it as a context
    manager: leaving the block waits for every bake, and if a bake or the
    conversion fails, queued bakes are cancelled and running ones joined before
    the original error propagates, so nothing writes into the outputs after a
    reported failure.
    """
    def __init__(self):
        self.pending = []

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if kind is None:
            self.wait()
        else:
            self.drain()
        return False

    def __call__(self, path, image, material, specular=None):
        executor = pool()
        # Bound the queued texture copies.
        while len(self.pending) >= 2 * executor._max_workers:
            self._finish_next()
        self.pending.append((path, executor.submit(bake_float_dds, path, image.copy(), copy.deepcopy(material),
                                                   None if specular is None else specular.copy())))

    def _finish_next(self):
        path, future = self.pending.pop(0)
        try:
            future.result()
        except Exception as error:
            self.drain()
            raise RuntimeError('Character texture bake ' + str(path) + ': ' + str(error)) from error

    def drain(self):
        """Cancel queued bakes and wait for running ones; their own errors are dropped."""
        pending, self.pending = self.pending, []
        for _, future in pending:
            future.cancel()
        wait_for([future for _, future in pending])

    def wait(self):
        try:
            while self.pending:
                self._finish_next()
        except BaseException:
            self.drain()
            raise
