"""Source-driven temporary faction slots, backed by native Skald effects.

One slot belongs to a soul, not to a quest or request handle. Set replaces that
slot; Clear releases it, exposing the soul's current underlying faction. The
source combat-selection guard is deliberately separate from explicit Clear.
No global combat hook, actor brain replacement or polling loop is installed.
"""
import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as E

from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import definition, identifier, xml, constant, edge, any_of
from character_factions import GROUP
from quest_import import literal


OPTION = 'suppressTempSuperfactionClearingInCombatVersusDude'
OPERATIONS = {'SetTemporarySuperfaction', 'ClearTemporarySuperfaction'}
_VAR = r'\$[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*'
_GUARD = re.compile(r'\((' + _VAR + r') == \$__player\) & '
                    r'\((' + _VAR + r') == true\) & !\$b_context\[\'' + OPTION + r'\'\]')


def token(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()[:24]


def native_contract(document):
    """Require the actual production effect contract, outside authoring data."""
    return any(n.find("Constant[@Name='Faction']") is not None
               and n.find("Asset[@Name='Souls']") is not None
               and n.find("Edge[@To='IsActive']") is not None
               for n in document.findall('./Skald/*/Nodes/TemporaryFactionEffect'))


class FactionBridge:
    def __init__(self, namespace, actor_bindings, superfactions, faction_tree, native_effect):
        self.namespace = identifier(namespace)
        self.stem = self.namespace + '_temporary_factions'
        if not native_contract(E.fromstring(native_effect)):
            raise ValueError('Native temporary faction effect contract is unavailable')
        self.bindings = dict(actor_bindings)
        self.groups = {}
        ids = set()
        registered = {n.get('Name') for n in E.fromstring(faction_tree).iter('Faction')}
        for row in superfactions:
            name, identity = row['superfaction_name'], str(row['superfaction_id'])
            if name in self.groups or identity in ids or not identity.isdecimal():
                raise ValueError('Ambiguous source superfaction declaration')
            ids.add(identity)
            target = GROUP + identity
            if target not in registered:
                raise ValueError('Source superfaction is not registered in the converted faction tree: ' + name)
            self.groups[name] = target
        self.actions = {}

    def actor(self, site, expression):
        # Bindings contain converted SharedSoulGuids, not entity WUIDs. Keeping
        # document/tree scope distinguishes worker `this` from controller `this`.
        expression = literal(expression).lstrip('$') or 'this.id'
        key = (site['owner'], site['document'], site['tree'], expression)
        value = self.bindings.get(key)
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as error:
            raise UnsupportedOperation('Temporary faction requires a scoped converted soul binding: ' + repr(key)) from error

    def action(self, actor, kind, value, site):
        name = self.stem + '_' + token(actor, kind, value)
        item = self.actions.setdefault(name, dict(actor=actor, kind=kind, value=value, sites=[]))
        item['sites'].append(site)
        return E.Element('SendAIConceptSignal_' + name)

    def lower(self, source, site):
        op, attrs = source['op'], {k: literal(v) for k, v in source['attributes'].items()}
        required = {'soul', 'superfaction'} if op == 'SetTemporarySuperfaction' else {'soul'}
        if op not in OPERATIONS or set(attrs) != required or source['children']:
            raise UnsupportedOperation('Unsupported temporary faction operation fields')
        actor = self.actor(site, attrs['soul'])
        if op == 'ClearTemporarySuperfaction':
            return self.action(actor, 'clear', '', site)
        target = self.groups.get(attrs['superfaction'])
        if target is None:
            raise UnsupportedOperation('Unknown or dynamic source superfaction: ' + attrs['superfaction'])
        return self.action(actor, 'set', target, site)

    def combat_guard(self, source, site):
        """Recognize the complete source guard; never generalize to any combat.

        The original opponent and clear-policy variables stay in the AI scope.
        Persistent suppression handles are evaluated by the effect owner. This
        is a source-site translation, not a native CombatAction callback hook.
        """
        if source['op'] != 'IfCondition':
            return None
        attrs = {k: literal(v) for k, v in source['attributes'].items()}
        condition = ' '.join(attrs.get('condition', '').split())
        match = _GUARD.fullmatch(condition)
        if not match:
            return None
        if (set(attrs) - {'condition', 'failOnCondition'} or attrs.get('failOnCondition', 'false') != 'false'
                or len(source['children']) != 1):
            raise UnsupportedOperation('Changed source combat-clearing guard needs review')
        clear = source['children'][0]
        fields = {k: literal(v) for k, v in clear['attributes'].items()
                  if not (k == 'id' and re.fullmatch(r'[0-9]+', v))}
        if (clear['op'] != 'ClearTemporarySuperfaction' or clear['children']
                or set(fields) != {'soul'} or fields['soul'] not in ('', 'this.id', '$this.id')):
            raise UnsupportedOperation('Combat-clearing guard must clear its executing soul')
        actor = self.actor(site, 'this.id')
        node = E.Element('IfCondition', failOnCondition='false',
                         condition=f'({match[1]} == $__player) & ({match[2]} == true)')
        node.append(self.action(actor, 'combat_clear', '', site))
        return node

    def lower_context(self, script, site):
        # Whole-program matching avoids converting a prefix and losing a tail.
        # Entity lookups remain compile-time bindings to an imported soul;
        # arbitrary Lua, dynamic handles and nonpersistent options are rejected.
        receiver = r"(?:entity|XGenAIModule\.GetEntityByWUID\(data\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\['[A-Za-z_]\w*'\])*)\))"
        pattern = re.compile(r"\s*Contexts\.(SetPersistentOption|ClearOption)\(\s*" + receiver
            + r"\s*,\s*(['\"])" + OPTION + r"\3\s*,\s*(['\"])([A-Za-z_]\w*)\4\s*\)\s*;?\s*\Z")
        match = pattern.fullmatch(script)
        if not match:
            raise UnsupportedOperation('Temporary faction context requires one constant persistent set/clear call')
        actor = self.actor(site, match[2] or 'this.id')
        return self.action(actor, 'protect' if match[1] == 'SetPersistentOption' else 'unprotect', match[5], site)

    def emit(self):
        root, module = definition('Module', self.stem)
        assets, nodes = E.SubElement(module, 'Assets'), E.SubElement(module, 'Nodes')
        table = E.Element('database')
        signals = E.SubElement(table, 'AIConceptSignalDatabase', version='1')
        actors = sorted({a['actor'] for a in self.actions.values()})
        for actor in actors:
            prefix = 'soul_' + token(actor)
            E.SubElement(assets, 'SoulAsset', Name=prefix, SharedSoulGuids=actor)
            actions = {n: a for n, a in self.actions.items() if a['actor'] == actor}
            factions = sorted({a['value'] for a in actions.values() if a['kind'] == 'set'})
            reasons = sorted({a['value'] for a in actions.values() if a['kind'] in ('protect', 'unprotect')})
            states, protection = {}, {}
            for faction in factions:
                name = prefix + '_slot_' + token(faction)
                states[faction] = E.SubElement(nodes, 'State', Name=name, TypeT='bool')
                constant(states[faction], 'DefaultValue', 'false')
                effect = E.SubElement(nodes, 'TemporaryFactionEffect', Name=name + '_effect')
                E.SubElement(effect, 'Asset', Name='Souls', Alias=prefix)
                constant(effect, 'Faction', faction)
                edge(effect, name + '.State', 'IsActive')
            for reason in reasons:
                name = prefix + '_protect_' + token(reason)
                protection[reason] = E.SubElement(nodes, 'State', Name=name, TypeT='bool')
                constant(protection[reason], 'DefaultValue', 'false')
            for name, action in sorted(actions.items()):
                E.SubElement(signals, 'AIConceptSignal', Name=name)
                trigger = E.SubElement(nodes, 'AIConceptSignalTrigger', Name=name, NotificationName=name)
                constant(trigger, 'IsActive', 'true')
                event = name + '.OnNotification'
                kind = action['kind']
                if kind in ('protect', 'unprotect'):
                    # Handles are independent: clearing one cannot release an
                    # option still owned by another source context handle.
                    edge(protection[action['value']], event, 'SetTrue' if kind == 'protect' else 'SetFalse')
                    continue
                if kind == 'combat_clear' and protection:
                    guard = E.SubElement(nodes, 'If', Name=name + '_protected')
                    edge(guard, event, 'Exec')
                    edge(guard, any_of(nodes, name + '_handles', [s.get('Name') + '.State' for s in protection.values()]), 'Condition')
                    event = name + '_protected.False'
                if kind == 'set':
                    ordered = E.SubElement(nodes, 'TriggerSequence', Name=name + '_replace')
                    edge(ordered, event, 'Exec')
                    event = name + '_replace.A'
                    edge(states[action['value']], name + '_replace.B', 'SetTrue')
                for state in states.values():
                    edge(state, event, 'SetFalse')
        return {'Quests/' + self.stem + '.xml': xml(root),
                'Libs/Tables/ai/AIConceptSignalDatabase__' + self.stem.lower() + '.xml': xml(table)}

    def report(self):
        return dict(actions=self.actions, runtime_validated=False,
            combat_clearing='Only translated source target-selection guards; no native combat hook installed',
            context_error_semantics='Effective handle state is preserved; source duplicate-set and missing-clear Lua assertions are not reproduced',
            requires=['One shared bridge for all writers of each imported soul',
                      'Converted source combat caller or a verified native combat-selection hook',
                      'Runtime effect removal, signal ordering and save/load validation'])
