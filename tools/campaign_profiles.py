"""Convert authored profile dependencies and bridge activation into native Skald.

A source profile is registered only after its layers, navigation and legacy
activation policy have been converted. The AI action retains its original
place in the source program; no profile is selected as a substitute opening.
"""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from campaign_dependencies import ImportPlan
from campaign_entity_links import native_guid
from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import constant, definition, edge, identifier, xml
from quest_import import literal


STREAMING_SOURCE = 'Quests/Final/Barbora/utils/streaming/streamprofileshandling.xml'


class WorldLayerAdapter:
    """Collect complete converted members without copying old entity payloads."""
    def __init__(self, documents, namespace, imported_files):
        self.namespace = identifier(namespace).lower()
        self.imported_files = imported_files
        self.documents = {}
        for path, data in documents.items():
            key = path.replace('\\', '/').lower()
            if key.startswith('layers/') and key.endswith('.xml'):
                identity = key[7:-4]
                if identity in self.documents:
                    raise ValueError('Duplicate source layer: ' + path)
                self.documents[identity] = (path, data)

    def plan(self, identity):
        path, data = self.documents[identity]
        root = ET.fromstring(data)
        if root.tag != 'Objects' or root.attrib:
            raise ValueError('Unconverted source world layer root: ' + path)
        members, dependencies = [], []
        for index, node in enumerate(root):
            if node.tag == 'Entity':
                guid = node.get('EntityGuid', '')
                if len(guid) == 16 and int(guid, 16) != 0:
                    member = ('entities', native_guid(int(guid, 16)))
                else:
                    # Prefab/local visual entities also need conversion. Their
                    # source layer/index is an unambiguous dependency key; it
                    # must not be reinterpreted as a persistent actor GUID.
                    member = ('world_layer_entities', identity + '#' + str(index))
            elif node.tag == 'Object':
                # Decals/brushes use a different native compiled object stream;
                # do not pretend an old <Object> is a converted runtime entity.
                member = ('world_layer_objects', identity + '#' + str(index))
            else:
                raise ValueError('Unconverted source world layer member: ' + node.tag)
            dependencies.append(member)
            members.append(dict(group=member[0], identity=member[1], source_index=index))
        return ImportPlan(dependencies, dict(path=path, source_name=identity,
            sha256=hashlib.sha256(data).hexdigest(), members=members))

    def convert(self, identity, plan, registered):
        target = self.namespace + '_layer_' + hashlib.sha256(identity.encode()).hexdigest()[:24]
        root = ET.Element('Objects')
        for member in plan.source['members']:
            group, source = member['group'], member['identity']
            output = registered[group][source.lower()]
            path = ('world/entities/' + output + '.xml') if group == 'entities' else output
            if path not in self.imported_files:
                raise ValueError('Registered layer member has no converted output: ' + source)
            data = self.imported_files[path]
            node = ET.fromstring(data.read_bytes() if isinstance(data, Path) else data)
            if node.tag != 'Entity':
                raise ValueError('Converted layer object stream requires a native merge adapter: ' + source)
            node.set('Layer', target)
            root.append(node)
        return target, {'world/layers/' + target + '.xml': xml(root)}, dict(
            source=plan.source['path'], source_sha256=plan.source['sha256'],
            members=len(root), requires_world_merge=True, runtime_validated=False)


class WorldProfileAdapter:
    """Emit native metadata only for a complete converted profile dependency set.

    world_layers registrations identify actual native layer outputs. A profile
    with navigation additionally requires profile_navigation; copying a source
    binary or clearing HasNavigation is not a navigation conversion.
    """
    def __init__(self, document, namespace, provenance):
        self.namespace = identifier(namespace).lower()
        self.provenance = provenance
        self.profiles = {}
        for profile in document.iter('GameProfile'):
            name = profile.findtext('Name')
            identity = identifier(name).lower()
            if identity in self.profiles:
                raise ValueError('Duplicate source world profile: ' + name)
            self.profiles[identity] = profile

    def plan(self, identity):
        profile = self.profiles[identity]
        allowed = {'Name', 'Id', 'HasNavigation', 'NeedsSVORebuild', 'GameLayers',
                   'AutoActForOlderVersion'}
        if profile.attrib or {n.tag for n in profile} - allowed:
            raise ValueError('Unconverted source world profile metadata: ' + identity)
        if len({n.tag for n in profile}) != len(profile):
            raise ValueError('Duplicate world profile fields: ' + identity)
        layers = []
        for layer in profile.findall('./GameLayers/GameLayer'):
            if layer.attrib or len(layer) or not (layer.text or '').strip():
                raise ValueError('Unconverted source profile layer metadata')
            layers.append(layer.text.strip())
        if len({n.lower() for n in layers}) != len(layers):
            raise ValueError('Duplicate source profile layers')
        flags = {name: profile.findtext(name) for name in ('HasNavigation', 'NeedsSVORebuild')}
        if any(value not in ('0', '1') for value in flags.values()):
            raise ValueError('Invalid source profile flags')
        dependencies = [('world_layers', name) for name in layers]
        if flags['HasNavigation'] == '1':
            dependencies.append(('profile_navigation', identity))
        if flags['NeedsSVORebuild'] == '1':
            dependencies.append(('profile_svo', identity))
        legacy = profile.findtext('AutoActForOlderVersion')
        if legacy is not None:
            # KCD2 has no matching field. Its saved-game migration policy must
            # be handled by a lifecycle adapter, not silently discarded here.
            int(legacy)
            dependencies.append(('profile_lifecycle', identity))
        return ImportPlan(dependencies, dict(name=profile.findtext('Name'),
            source_id=profile.findtext('Id'), layers=layers, flags=flags,
            auto_activate_for_older_version=legacy, provenance=self.provenance))

    def convert(self, identity, plan, registered):
        source = plan.source
        target = self.namespace + '_' + source['name']
        root = ET.Element('GameProfile')
        ET.SubElement(root, 'Name').text = target
        # IDs are local to the final world. A fragment carries no guessed Id;
        # the merger allocates it against the destination profile registry.
        for name in ('HasNavigation', 'NeedsSVORebuild'):
            ET.SubElement(root, name).text = source['flags'][name]
        for name in ('DoesPrepareSOAnimData', 'AllowRuntimeAnimValidationFallback'):
            ET.SubElement(root, name).text = '0'
        converted = [registered['world_layers'][name.lower()] for name in source['layers']]
        if len(set(converted)) != len(converted):
            raise ValueError('Distinct source layers collapsed during conversion')
        if converted:
            layers = ET.SubElement(root, 'GameLayers')
            for name in converted:
                ET.SubElement(layers, 'GameLayer').text = name
        path = 'world/profiles/' + target + '.xml'
        return target, {path: xml(root)}, dict(source_name=source['name'],
            source_flags=source['flags'], converted_layers=converted,
            requires_world_merge=True, runtime_validated=False)


class ProfileLifecycleAdapter:
    """Translate the engine's explicit no-migration sentinel, not game versions.

    The supplied metadata must come from the source engine enum serializer.
    Real migration thresholds cannot use KCD2's unrelated $__version domain.
    """
    def __init__(self, profiles, namespace, engine_metadata):
        self.namespace = identifier(namespace).lower()
        self.profiles = {p.findtext('Name').lower(): p for p in profiles.iter('GameProfile')}
        declarations = [d for d in engine_metadata['enum_declarations'] if d['name'] == 'gameVersion']
        if len(declarations) != 1:
            raise ValueError('Source engine gameVersion declaration is required')
        self.declaration = declarations[0]
        invalid = [value['ordinal'] for value in self.declaration['values'] if value['name'] == 'Invalid']
        if len(invalid) != 1:
            raise ValueError('Source engine no-migration sentinel is not declared')
        self.invalid = invalid[0]
        self.binary_sha256 = engine_metadata['sha256']

    def plan(self, identity):
        value = self.profiles[identity].findtext('AutoActForOlderVersion')
        if value is None:
            raise ValueError('Profile has no source automatic activation policy')
        ordinal = int(value)
        if ordinal != self.invalid:
            names = [v['name'] for v in self.declaration['values'] if v['ordinal'] == ordinal]
            raise ValueError('Source campaign save-version migration requires a runtime service: '
                + identity + ' before ' + (names[0] if len(names) == 1 else str(ordinal)))
        return ImportPlan(source=dict(profile=identity, source_value=ordinal,
            source_enum='gameVersion.Invalid', source_binary_sha256=self.binary_sha256,
            enum_function_start_rva=self.declaration['function_start_rva'],
            policy='authored_activation_only'))

    def convert(self, identity, plan, registered):
        return self.namespace + '_profile_policy_' + identity, {}, dict(plan.source,
            target_policy='No automatic profile activation; source EnableProfile controls streaming',
            cross_game_version_comparison=False, runtime_validated=False)


class ProfileBridge:
    """Keep source activation events and native loaded acknowledgements distinct."""
    def __init__(self, namespace, importer):
        self.namespace = identifier(namespace)
        self.importer = importer
        self.actions, self.profiles = {}, {}

    def lower(self, source, site):
        if source['op'] != 'EnableProfile':
            raise UnsupportedOperation('Not a profile activation operation')
        attrs = source['attributes']
        if set(attrs) - {'profileEnable', 'profileDisable'} or source['children']:
            raise UnsupportedOperation('Unconverted profile activation metadata')
        targets = {}
        for field in ('profileEnable', 'profileDisable'):
            name = literal(attrs.get(field, ''))
            if not name:
                continue
            try:
                identifier(name)
            except ValueError as error:
                raise UnsupportedOperation('Dynamic profile identity requires runtime mapping: ' + name) from error
            target = self.importer.ensure('world_profiles', name, site) if self.importer else None
            if target is None:
                raise UnsupportedOperation('Referenced world profile conversion did not complete: ' + name)
            targets[field] = target
        if not targets:
            raise UnsupportedOperation('Empty profile operation has no verified native semantics')
        if targets.get('profileEnable') == targets.get('profileDisable'):
            raise UnsupportedOperation('Same profile enabled and disabled in one source operation')
        digest = hashlib.sha256(repr(sorted(targets.items())).encode()).hexdigest()[:20]
        action = self.namespace + '_profile_' + digest
        self.actions[action] = targets
        for target in targets.values():
            self.profiles[target] = self.namespace + '_profile_' + hashlib.sha256(target.encode()).hexdigest()[:20]
        return ET.Element('SendAIConceptSignal_' + action)

    def emit(self, streaming):
        """Use the installed helper's Layer/ProfileStateTrigger state machine."""
        helper = ET.fromstring(streaming).find('./Skald/Module')
        if (helper is None or helper.get('Name') != 'streamprofileshandling'
                or helper.find('.//Layer') is None or helper.find('.//ProfileStateTrigger') is None):
            raise ValueError('Native profile streaming helper contract changed')
        root, module = definition('Module', self.namespace + '_profile_bridge')
        declarations = ET.SubElement(module, 'Definitions')
        helper_path = self.namespace + '_profile_streaming.xml'
        ET.SubElement(declarations, 'Definition', File=helper_path)
        assets, nodes = ET.SubElement(module, 'Assets'), ET.SubElement(module, 'Nodes')
        signal_root = ET.Element('database')
        signals = ET.SubElement(signal_root, 'AIConceptSignalDatabase', version='1')
        for target, instance in sorted(self.profiles.items()):
            alias = instance + '_asset'
            ET.SubElement(assets, 'ProfileAsset', Name=alias, AssetProfiles=target)
            stream = ET.SubElement(nodes, 'streamprofileshandling', Name=instance)
            ET.SubElement(stream, 'Asset', Name='profiles', Alias=alias)
            for action, values in sorted(self.actions.items()):
                if values.get('profileEnable') == target:
                    edge(stream, action + '.OnNotification', 'streamprofiles')
                if values.get('profileDisable') == target:
                    edge(stream, action + '.OnNotification', 'unstreamprofiles')
            # This is evidence of completion, not a replacement for source
            # ProfileCanBeLoaded (which also has group/policy semantics).
            state = ET.SubElement(nodes, 'State', Name=instance + '_loaded', TypeT='bool')
            constant(state, 'DefaultValue', 'false')
            edge(state, instance + '.onloaded', 'SetTrue')
            edge(state, instance + '.onunloaded', 'SetFalse')
        for action in sorted(self.actions):
            ET.SubElement(signals, 'AIConceptSignal', Name=action)
            trigger = ET.SubElement(nodes, 'AIConceptSignalTrigger', Name=action, NotificationName=action)
            constant(trigger, 'IsActive', 'true')
        return {'Quests/' + self.namespace + '_profile_bridge.xml': xml(root),
            'Quests/' + helper_path: streaming,
            'Libs/Tables/ai/AIConceptSignalDatabase__' + self.namespace.lower() + '_profiles.xml': xml(signal_root)}
