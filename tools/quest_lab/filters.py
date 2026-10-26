"""Native action filters: the retail filter table and the FilterInput contract.

A FilterInput node contributes its Filters to the active set while IsActive is
true; the active set is the union over nodes. Each named filter blocks the input
actions listed for it in the retail ``defaultProfile.xml``. Only input actions are
modeled. Script-initiated paths, the real loading stall and the engine's time
scale are explicit native unknowns, never assumed.
"""
import hashlib
import xml.etree.ElementTree as E

from . import Unsupported

KIND = 'FilterInput'
INPUTS = {'Filters', 'IsActive'}
ENGINE_EVENTS = ('OnWake', 'OnLevelSwitched')
LEAK_BOUND_HOURS = 24

NATIVE_UNKNOWNS = {
    'onwake_on_save_load': 'Whether the engine fires a Level OnWake when a save inside that Level loads. '
        'A scenario or audit can only fire it as an explicit stimulus.',
    'game_time_real_time_scale': 'How many real seconds one GameTime second lasts during the loading stall. '
        'A GameTime window may be much shorter in real time. Needs an explicit scenario time_scale.',
    'ui_input_causes_freeze': 'Whether UI input is the cause of the arrival freeze at all. '
        'A closed gate proves only that the listed actions are filtered.',
    'scripted_paths_bypass_filters': 'Action filters block input actions. Interactions started by script, '
        'dialogue or the interaction_filter table are not modeled.',
    'node_port_names': 'FilterInput.Filters/IsActive and Timer.Running are the names the converter emits. '
        'Their native existence and semantics are not verified offline.',
}


class ActionTable:
    """Filters and known action names read from a retail input profile."""

    def __init__(self, blob):
        root = E.fromstring(blob)
        self.sha256 = hashlib.sha256(blob).hexdigest()
        self.filters = {}
        for item in root.iter('actionfilter'):
            name = item.get('name')
            if not name or name in self.filters: raise ValueError('Missing or duplicate action filter: ' + str(name))
            actions = tuple(a.get('name') for a in item.findall('action'))
            if not actions or any(not a for a in actions):
                raise ValueError('Action filter needs named actions: ' + name)
            self.filters[name] = actions
        mapped = {a.get('name') for m in root.iter('actionmap') for a in m.findall('action') if a.get('name')}
        self.actions = mapped | {a for actions in self.filters.values() for a in actions}
        self.mapped = frozenset(mapped)
        if not self.filters: raise ValueError('Profile defines no action filters')

    def resolve(self, names):
        unknown = [n for n in names if n not in self.filters]
        if unknown: raise Unsupported('Unknown native action filter: ' + ', '.join(sorted(unknown)))
        return {a for n in names for a in self.filters[n]}

    def known(self, action):
        if action not in self.actions: raise ValueError('Unknown input action: ' + str(action))
        return action

    def apse_actions(self):
        return sorted(a for a in self.actions if a.startswith('open_apse_'))


def unknowns(fired, scale):
    """Describe each native unknown relative to what the scenario explicitly supplied."""
    assumed = {'onwake_on_save_load': 'OnWake' in fired, 'game_time_real_time_scale': scale is not None}
    return [dict(id=key, status='ASSUMED_BY_SCENARIO' if assumed.get(key) else 'UNSUPPORTED', detail=text)
            for key, text in NATIVE_UNKNOWNS.items()]
