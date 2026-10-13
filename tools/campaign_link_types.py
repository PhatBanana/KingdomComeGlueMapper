"""Register source AI link data and translate its expression variable ABI.

KCD1 exposes a tag's data as $Tag (or its explicit variableName); KCD2
exposes $__link_Tag. String literals must remain untouched during translation.
The shared output merges the target definitions rather than replacing them.
"""
import copy
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from campaign_dependencies import ImportPlan
from campaign_quest_graph import identifier, xml
from upgrade_map import read


class LinkTypeAdapter:
    def __init__(self, source_root, target_root, namespace, cache):
        for root in (source_root, target_root):
            if root.tag != 'LinkTagDefinitions' or root.get('version') != '1':
                raise ValueError('Unsupported AI link type schema')
        self.namespace = identifier(namespace).lower()
        self.source = {}
        for node in source_root:
            name = node.get('name')
            if node.tag != 'LinkTag' or not name:
                raise ValueError('Invalid source AI link declaration')
            identity = name.lower()
            if identity in self.source:
                raise ValueError('Ambiguous source AI link type: ' + name)
            self.source[identity] = dict(node.attrib)
        self.root = copy.deepcopy(target_root)
        self.path = Path(cache) / 'LinkTagDefinitions.xml'
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, source, target, reader, namespace, cache):
        blob = reader(source, {'links': ('Scripts.pak', 'Libs/AI/LinkTagDefinitions.xml')})['links']['data']
        with zipfile.ZipFile(Path(target) / 'Data/Scripts.pak') as archive:
            native = read(archive, 'AI/LinkTagDefinitions.xml')
        return cls(ET.fromstring(blob), ET.fromstring(native), namespace, cache)

    def plan(self, identity):
        if identity not in self.source:
            raise ValueError('Source AI link type is not declared: ' + identity)
        row = self.source[identity]
        allowed = {'name', 'type', 'color', 'persistent', 'doNotLoadIfSaved',
                   'autoInverse', 'variableName', 'ownershipIgnore', 'defaultPruning'}
        if set(row) - allowed:
            raise ValueError('Unconverted source AI link metadata')
        # Default graph-search pruning is a source runtime policy. It cannot
        # be replaced with an unrelated native flag or silently discarded.
        if row.get('defaultPruning', '0') != '0':
            raise ValueError('Source default link pruning requires graph-search conversion')
        # KCD2 ownershipInclude is opt-in; its inverse is not sufficient
        # evidence for the source ownership traversal's default behavior.
        if row.get('ownershipIgnore') not in (None, '1'):
            raise ValueError('Source ownership-traversable link requires ownership conversion')
        for field in ('persistent', 'doNotLoadIfSaved'):
            if field in row and row[field] not in ('0', '1'):
                raise ValueError('Invalid source AI link boolean: ' + field)
        identifier(row['name'])
        if row.get('variableName'):
            identifier(row['variableName'])
        deps = [('ai_types', row['type'])] if row.get('type') else []
        if row.get('autoInverse'):
            deps.append(('link_types', row['autoInverse']))
        return ImportPlan(deps, dict(row=row))

    def convert(self, identity, plan, registered):
        row = plan.source['row']
        target = self.namespace + '_' + row['name']
        attrs = {k: v for k, v in row.items() if k in ('color', 'persistent', 'doNotLoadIfSaved')}
        attrs['name'] = target
        if row.get('ownershipIgnore') == '1':
            attrs['ownershipInclude'] = '0'
        if row.get('type'):
            attrs['type'] = registered['ai_types'][row['type'].lower()]
        if row.get('autoInverse'):
            attrs['autoInverse'] = registered['link_types'][row['autoInverse'].lower()]
        if any(n.get('name', '').lower() == target.lower() for n in self.root):
            raise ValueError('Converted AI link type already exists: ' + target)
        ET.SubElement(self.root, 'LinkTag', attrs)
        self.path.write_bytes(xml(self.root))
        return target, {'AI/LinkTagDefinitions.xml': self.path}, dict(
            source_variable=row.get('variableName') or row['name'],
            target_variable='__link_' + target, runtime_validated=False)


def data_expression(expression, source_variable, target_tag):
    """Rewrite a resolved link data symbol; never replace text or prefixes."""
    identifier(source_variable)
    identifier(target_tag)
    pieces = re.split(r'''('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")''', expression)
    symbol = re.compile(r'\$' + re.escape(source_variable) + r'(?![A-Za-z_0-9])')
    return ''.join(part if index % 2 else symbol.sub('$__link_' + target_tag, part)
                   for index, part in enumerate(pieces))


def link_list(value, importer, site=None):
    """Convert a literal GraphSearch edge mask using the same link registry.

    Parent/inventory edges are engine-owned and occur in both native search
    ABIs; all script-declared edges require conversion. Dynamic masks need a
    runtime translation and must not accidentally search the native graph.
    """
    if not value:
        return ''
    tags = [tag.strip() for tag in value.split(',')]
    if any(not re.fullmatch(r'[A-Za-z_]\w*', tag) for tag in tags):
        raise ValueError('Dynamic or invalid graph edge mask requires conversion')
    converted = []
    for tag in tags:
        if tag.lower() in ('parent', 'inventory'):
            converted.append(tag.lower())
            continue
        target = importer.ensure('link_types', tag, site)
        if target is None:
            raise ValueError('Graph edge type did not convert: ' + tag)
        converted.append(target)
    return ','.join(converted)


def link_definition(label, importer, site=None):
    """Convert constant source link data using the registered tag's type."""
    from campaign_bindings import parse_link_labels
    definitions = []
    for item in parse_link_labels(label):
        target = importer.ensure('link_types', item['tag'], site)
        if target is None:
            raise ValueError('AI link type did not convert: ' + item['tag'])
        record = importer.jobs.get(('link_types', item['tag'].lower()))
        if not record or record['status'] != 'imported':
            raise ValueError('AI link serialization requires verified source type metadata')
        typ = record['source']['row'].get('type', '')
        if item['named']:
            raise ValueError('Structured AI link data requires field serialization')
        values = item['positional']
        if not typ:
            if values:
                raise ValueError('Data supplied to an untyped source AI link')
            definitions.append(target)
            continue
        if len(values) != 1:
            raise ValueError('A scalar source AI link requires exactly one value')
        value = values[0]
        if typ in ('string', '_string') and isinstance(value, str):
            if any(c in value for c in "'\\\n\r"):
                raise ValueError('Source AI link string escaping requires an adapter')
            text = "'" + value + "'"
        elif typ in ('bool', '_bool') and type(value) is bool:
            text = str(value).lower()
        elif typ in ('int', 'int64') and type(value) is int:
            text = str(value)
        elif typ == 'float' and type(value) in (int, float) and math.isfinite(value):
            text = str(value)
        else:
            raise ValueError('Source AI link data/type mismatch: ' + typ)
        definitions.append(target + '[' + text + ']')
    return ','.join(definitions)


def convert_world_links(world, importer, placed):
    """Restore source AI edges only when both converted placements exist.

    Traversal cycles are normal in a world graph; they are assembled after
    entity conversion rather than incorrectly treated as dependency cycles.
    """
    from campaign_entity_links import native_guid
    links, resolved, pending = [], [], list(world.get('unresolved', []))
    registered = importer.registered.get('entities', {})
    for link in world['links']:
        try:
            endpoints = []
            for field in ('from', 'to'):
                source = world['entities'][link[field]]['attributes']['EntityGuid']
                identity = native_guid(int(source, 16))
                target = registered.get(identity.lower())
                if target is None or target not in placed:
                    raise ValueError('Source AI link endpoint has not been placed: ' + identity)
                endpoints.append(target)
            label = link['source_link']['Name']
            # Untagged edges are significant for graph traversal and tools.
            definition = link_definition(label, importer, dict(kind='source_world_link', link=link)) if label else ''
            links.append((*endpoints, definition))
            resolved.append(dict(link=link, definition=definition, source=endpoints[0], target=endpoints[1]))
        except (ValueError, KeyError) as error:
            pending.append(dict(link=link, reason=str(error)))
    return links, dict(resolved=resolved, pending=pending, runtime_validated=False)
