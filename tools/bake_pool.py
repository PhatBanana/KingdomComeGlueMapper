"""Float macro texture bakes in worker processes shared by one build.

A fixed-outfit conversion bakes about twenty 2048px textures, which took half
of each NPC's import when run one after another on the main thread. The pool
starts on first use and is reused by every later conversion; callers that
finish a batch call release() so its workers do not idle through the rest of
the build (atexit covers the rest).
"""
import atexit
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor, wait as wait_for
import copy

from bounded_pool import worker_count
from character_native_materials import bake_float_dds
from texture_encode import Batches, write_mask_dds

_POOL = None
_SHARED = None   # the deferred_encodes() Batches, while one is active


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



@contextmanager
def deferred_encodes():
    """Let conversions continue while the GPU compresses earlier ones' textures.

    Inside this block every Bakes hands its staged BC7 textures to one shared
    texture_encode.Batches and returns once its bakes are staged, without waiting
    for texconv. A Bakes' ticket() completes when its textures are written; the
    caller must wait on it before reading them (Bakes(encode_now=True) waits
    itself). Leaving the block writes every remaining texture; an error discards
    work that was not started.
    """
    global _SHARED
    if _SHARED is not None:
        yield _SHARED
        return
    batches = _SHARED = Batches()
    try:
        yield batches
        try:
            batches.finish()
        except Exception as error:
            raise RuntimeError('Character texture encode: ' + str(error)) from error
    finally:
        _SHARED = None
        batches.abort()


class Bakes:
    """One conversion's deferred bakes; wait() must run before its outputs are read.

    Matches the bake(path, image, material, specular=None) callback of
    convert_character_materials, plus mask(path, image) for effect masks.
    Arguments are copied because they are pickled after submit() and the caller
    may reuse the images. Use it as a context manager: leaving the block waits
    for every bake, and if a bake or the conversion fails, queued bakes are
    cancelled and running ones joined before the original error propagates, so
    nothing writes into the outputs after a reported failure.

    BC7 textures are staged by the workers and block-compressed by texconv in
    batches on a background thread. Inside deferred_encodes() that encoder is
    shared and wait() leaves the compression running unless encode_now is set;
    ticket() then tells when this conversion's textures are written.
    """
    def __init__(self, encode_now=False):
        self.pending = []
        self.shared = _SHARED is not None
        self.batches = _SHARED if self.shared else Batches()
        self.encode_now = encode_now
        self.done = None

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if kind is None:
            self.wait()
        else:
            self.drain()
        return False

    def __call__(self, path, image, material, specular=None):
        self._submit(path, bake_float_dds, image.copy(), copy.deepcopy(material),
                     None if specular is None else specular.copy())

    def mask(self, path, image):
        """Effect masks are encoded in the workers too, not on the converting thread."""
        self._submit(path, write_mask_dds, image.copy())

    def _submit(self, path, function, *args):
        executor = pool()
        # Bound the queued texture copies.
        while len(self.pending) >= 2 * executor._max_workers:
            self._finish_next()
        staging = self.batches.staging()
        extra = {} if staging is None else {'staging': staging}
        self.pending.append((path, executor.submit(function, path, *args, **extra)))

    def _finish_next(self):
        path, future = self.pending.pop(0)
        try:
            self.batches.add(future.result())
        except Exception as error:
            self.drain()
            raise RuntimeError('Character texture bake ' + str(path) + ': ' + str(error)) from error

    def drain(self):
        """Cancel queued bakes and wait for running ones; their own errors are dropped."""
        pending, self.pending = self.pending, []
        for _, future in pending:
            future.cancel()
        wait_for([future for _, future in pending])
        if self.shared:
            # Textures this conversion already queued may be compressing; let them
            # land now rather than after the failure is reported.
            try: self.batches.ticket().result()
            except Exception: pass
        else:
            self.batches.abort()

    def ticket(self):
        """A future that completes when this conversion's textures are written."""
        return self.done

    def wait(self):
        try:
            while self.pending:
                self._finish_next()
            try:
                if not self.shared:
                    self.batches.finish()
                    self.done = self.batches.ticket()
                else:
                    self.done = self.batches.ticket()
                    if self.encode_now: self.done.result()
            except Exception as error:
                raise RuntimeError('Character texture encode: ' + str(error)) from error
        except BaseException:
            self.drain()
            raise
