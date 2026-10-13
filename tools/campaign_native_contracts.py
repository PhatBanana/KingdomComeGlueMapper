"""Native contracts absent from shipped examples, tied to tested binaries.

See docs/native-work-contract-validation.md for the acceptance boundary.
An unknown engine retains example-derived contracts only.
"""
import hashlib
from pathlib import Path


VALIDATED_MODULES = {
    'e20db768f17284a6eca8d6bb7411e6d2f08876d41eb5279368679d4d3ccd4847',
}


def supplement(game, nodes):
    module = Path(game) / 'Bin/Win64ReleaseSteamLTO_DLL/XGenAIModule.dll'
    if not module.is_file():
        return
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    if digest not in VALIDATED_MODULES:
        return
    nodes.setdefault('NotNearPlayer', dict(attributes={'target', 'result'}, children=set(),
        example='native runtime parser probe (no shipped XML example)', sha256=digest,
        validation='parser acceptance; proximity outcome not asserted'))
