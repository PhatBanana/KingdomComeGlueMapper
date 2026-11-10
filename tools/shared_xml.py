"""One parsed tree per identical read-only XML document within a build process.

Combine's importers each scan the same ~1,830 KCD1 layer files and the 50 MB
source mission: about thirty full passes of 2-3 s each. A caller that only
reads the elements asks for the shared tree instead of parsing again. The key
is the document's bytes (length and BLAKE2 digest), so a changed document is a
different entry and no file identity is trusted.

Shared trees are read-only. Deep-copy an element before editing it or adding
it to another tree: ElementTree keeps an appended element in its old parent
too, so an edit made through either tree shows in both.
Callers that edit what they parse keep using ElementTree.fromstring.

The memo is filled until its budget is spent and then stops admitting new
documents; nothing is evicted. Layer scans visit the same files in the same
order every pass, and a least-recently-used memo smaller than one pass would
never hit. The budget comes from free memory at first use (a parsed tree is
about five to six times its XML): 1/16 of it, between 256 MiB and 1.5 GiB.

GLUEMAPPER_SHARED_XML=0 parses every call. GLUEMAPPER_SHARED_XML_CHECK=1 keeps
a fingerprint of each tree and raises when a hit, or verify(), finds one edited.
"""
import copy
import hashlib
import os
import threading
import xml.etree.ElementTree as ET

TREE_FACTOR = 6  # measured 5.3x for KCD1 layers and mission (tracemalloc)
MIN_BUDGET = 256 * 1024**2
MAX_BUDGET = 1536 * 1024**2

_TREES = {}
_LOCK = threading.Lock()
_STATE = {'budget': None, 'used': 0, 'hits': 0, 'misses': 0, 'skipped': 0}


def _budget():
    if _STATE['budget'] is None:
        try:
            from bounded_pool import available_memory
            free = available_memory()
        except Exception:
            free = None
        _STATE['budget'] = MIN_BUDGET if free is None else max(MIN_BUDGET, min(MAX_BUDGET, free // 16))
    return _STATE['budget']


def _fingerprint(root):
    return hashlib.blake2b(ET.tostring(root), digest_size=16).digest()


def _checking():
    return os.environ.get('GLUEMAPPER_SHARED_XML_CHECK') == '1'


def parse(data):
    """The root element of `data` (bytes or str), shared with every other reader of the same document."""
    if os.environ.get('GLUEMAPPER_SHARED_XML') == '0':
        return ET.fromstring(data)
    # Text and bytes parse differently (an encoding declaration applies to bytes only), so they never share.
    raw = data.encode('utf-8', 'surrogatepass') if isinstance(data, str) else data
    key = (isinstance(data, str), len(raw), hashlib.blake2b(raw, digest_size=16).digest())
    with _LOCK:
        hit = _TREES.get(key)
        if hit is not None:
            _STATE['hits'] += 1
    if hit is not None:
        root, fingerprint = hit
        if fingerprint is not None and _fingerprint(root) != fingerprint:
            raise RuntimeError('A shared XML tree was edited by one of its readers')
        return root
    root = ET.fromstring(data)
    cost = TREE_FACTOR * len(raw)
    fingerprint = _fingerprint(root) if _checking() else None
    with _LOCK:
        _STATE['misses'] += 1
        if key in _TREES:
            return _TREES[key][0]
        if _STATE['used'] + cost <= _budget():
            _TREES[key] = (root, fingerprint)
            _STATE['used'] += cost
        else:
            _STATE['skipped'] += 1
    return root


def without_tail(element):
    """ElementTree.tostring of an element without its tail, leaving the element as it is."""
    clone = copy.copy(element)
    clone.tail = None
    return ET.tostring(clone)


def verify():
    """Raise if any checked tree no longer matches its fingerprint; return how many were checked."""
    with _LOCK:
        entries = list(_TREES.values())
    checked = 0
    for root, fingerprint in entries:
        if fingerprint is None:
            continue
        if _fingerprint(root) != fingerprint:
            raise RuntimeError('A shared XML tree was edited by one of its readers')
        checked += 1
    return checked


def stats():
    with _LOCK:
        return dict(_STATE, documents=len(_TREES))


def clear():
    with _LOCK:
        _TREES.clear()
        _STATE.update(budget=None, used=0, hits=0, misses=0, skipped=0)
