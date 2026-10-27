"""Developer-only interaction clearance and boundary walk emulator.

Never imported by consumer Setup. Geometry comes from level data only; every
clearance shape is an explicit, documented approximation of native helpers.
"""


class Unsupported(Exception):
    """Something the lab does not model; it is reported and never passes."""


SCHEMA = 1
