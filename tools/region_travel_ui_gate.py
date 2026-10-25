"""Hold the Apse UI and interaction briefly after entering the converted region.

Opening inventory, map, journal or a shop during the first minutes in
kcd1_travel can livelock the retail renderer (issue #3). The game reports no
"background streaming settled" signal to Skald, and the station profile's
``onloaded`` acknowledgement fires long before the world settles. Use a bounded
native hold instead: the destination Level's own OnWake (save load, repeat
visit) and OnLevelSwitched (coach arrival) start one native Timer, and native
action filters stay active only while that Timer runs.

Everything is retail Skald and retail action filters (Libs/Config/defaultProfile.xml):
- ``no_inventory`` covers every open_apse_* action (inventory, player, journal,
  map, codex) on keyboard and controller.
- ``no_interaction`` covers use/talk, so a shop's OpenShop dialogue and the
  return coach cannot start during the hold. With no coach, map or fast travel,
  the hold cannot outlive the level; death or quitting reloads the world.
The block is silent: the repo has no native player notification helper.
"""
import hashlib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from upgrade_map import read, xml

FILTERS = ('no_inventory', 'no_interaction')
DURATION = '90s'
TIMER = 'arrival_ui_settle'
ARRAY = 'arrival_ui_filters'
GATE = 'arrival_ui_gate'
EVENTS = ('OnWake', 'OnLevelSwitched')
TRAVEL = 'Data/gluemappertravel.pak'


def gate(entry, level):
    """Add the hold to one destination Level graph; unchanged if already present."""
    root = ET.fromstring(entry)
    host = root.find('Skald/Level')
    if host is None or host.get('Name') != level or host.find('Nodes') is None:
        raise ValueError('Expected the destination Level entry graph')
    nodes = host.find('Nodes')
    present = [nodes.find(f"*[@Name='{name}']") for name in (TIMER, ARRAY, GATE)]
    if all(node is not None for node in present):
        return entry
    if any(node is not None for node in present):
        raise ValueError('Partial arrival UI gate; repair explicitly')
    timer = ET.SubElement(nodes, 'Timer', Name=TIMER)
    ET.SubElement(timer, 'Constant', Name='Duration', Value=DURATION)
    ET.SubElement(timer, 'Constant', Name='TimeType', Value='GameTime')
    for event in EVENTS:
        ET.SubElement(timer, 'Edge', From=event, To='SetRunning')
    array = ET.SubElement(nodes, 'MakeArray', Name=ARRAY, TypeT='Strings')
    for key, name in zip('ABCDEFGH', FILTERS):
        ET.SubElement(array, 'Constant', Name=key, Value=name)
    hold = ET.SubElement(nodes, 'FilterInput', Name=GATE)
    ET.SubElement(hold, 'Edge', From=ARRAY + '.Array', To='Filters')
    ET.SubElement(hold, 'Edge', From=TIMER + '.Running', To='IsActive')
    return xml(root)


def report():
    return dict(filters=list(FILTERS), duration=DURATION, time_type='GameTime',
                starts=list(EVENTS), releases='timer', notification=False, runtime_verified=False)


def upgrade(package, entry_path='Quests/GlueTravel/entry/kcd1_travel.xml', level='kcd1_travel'):
    """Add the hold to a saved build's packaged travel graph."""
    from setup_package_upgrade import rewrite
    from setup_campaign import digest
    package = Path(package)
    with zipfile.ZipFile(package/TRAVEL) as z:
        name = next((n for n in z.namelist() if n.lower() == entry_path.lower()), None)
        if name is None:
            raise ValueError('Packaged destination entry graph is missing')
        original = read(z, name)
    gated = gate(original, level)
    if gated == original:
        return {}, dict(report(), changed=False)
    rewrite(package, TRAVEL, {name: gated})
    return {TRAVEL: digest(package/TRAVEL)}, dict(report(), changed=True,
        entry_sha256=hashlib.sha256(gated).hexdigest())
