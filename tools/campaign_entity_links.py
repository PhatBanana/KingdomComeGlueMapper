"""KCD2 persistent entity identifiers and exported AI link-network records.

Entity GUID text is low32-mid16-high16, whereas KCD1's text is a hexadecimal
uint64. These representations must not be confused when binding binary areas.
The native AI link network loads waitinglinks.xml, independently of CryEngine's
EntityLinks records in objects_mission0.xml.
"""
from functools import lru_cache
import re
import xml.etree.ElementTree as ET

from upgrade_map import xml


def native_guid(value):
    if not isinstance(value, int) or not 0 < value <= 0xffffffffffffffff:
        raise ValueError('Expected a nonzero uint64 entity GUID')
    return f'{value & 0xffffffff:08x}-{(value >> 32) & 0xffff:04x}-{value >> 48:04x}'


@lru_cache(maxsize=1 << 18)  # a build asks for the same few hundred thousand GUIDs millions of times
def guid_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}', value):
        raise ValueError('Expected a native 8-4-4 entity GUID')
    a, b, c = (int(v, 16) for v in value.split('-'))
    result = a | b << 32 | c << 48
    if not result: raise ValueError('Zero entity GUID')
    return result


def entity_link(a, b, label, waiting):
    """Append an EntityLinks/Link from a to b and record it for the link network.

    Creates the EntityLinks container on the source entity when absent, writes a
    single Link with the target's EntityId and EntityGuid, and appends the
    (source guid, target guid, label) record so the caller can export it to the
    native AI link network afterwards.
    """
    links = a.find('EntityLinks')
    if links is None: links = ET.SubElement(a, 'EntityLinks')
    ET.SubElement(links, 'Link', Name=label, TargetId=b.get('EntityId'), TargetGuid=b.get('EntityGuid'))
    waiting.append((a.get('EntityGuid'), b.get('EntityGuid'), label))


def append_links(data, links, *, allow_untagged=False):
    """Merge explicit (source GUID, target GUID, definition) links, deduplicated.

    Existing level links are retained verbatim. Only the supplied records are
    converted; callers must resolve source IDs and profile/layer dependencies.
    allow_untagged permits the native reservation-point -> ItemSlot edge, whose
    empty LinkDefinition is meaningful. Other callers reject empty definitions.
    """
    global _LAST
    # Finalize's steps each hand the network back as the previous step wrote it,
    # over a hundred times a build. The tree and index behind the bytes this
    # process wrote last are extended in place instead of parsed and re-indented.
    # The entry is dropped first: those bytes no longer describe the tree.
    cached = _LAST is not None and data == _LAST[0]
    if cached:
        _, root, waiting, index = _LAST; _LAST = None
    else:
        root = ET.fromstring(data) if data else ET.Element('StaticLinksInfo', version='1')
        if root.tag != 'StaticLinksInfo' or root.get('version') != '1':
            raise ValueError('Unsupported native link-network format')
        waiting = root.find('WaitingLinks')
        if waiting is None: waiting = ET.SubElement(root, 'WaitingLinks')
        index = {(guid_value(n.get('SourceId')), guid_value(n.get('TargetId'))): n
                 for n in waiting.findall('WaitingLink')}
    last = waiting[-1] if cached and len(waiting) else None
    added, touched = [], []
    for source, target, definition in links:
        key = (guid_value(source), guid_value(target))
        if not isinstance(definition, str) or (not definition.strip() and not (allow_untagged and definition == '')):
            raise ValueError('An explicit AI link definition is required')
        if key not in index:
            index[key] = ET.SubElement(waiting, 'WaitingLink', SourceId=native_guid(key[0]),
                                      TargetId=native_guid(key[1]))
            added.append(index[key])
        node = index[key]
        if definition not in [n.text or '' for n in node.findall('LinkDefinition')]:
            ET.SubElement(node, 'LinkDefinition').text = definition
            if node not in touched: touched.append(node)
    if last is not None:
        # The whitespace ET.indent(root) would give: nodes whose children changed are
        # indented at their depth, new links and the former last one get a sibling's
        # tail, the last link the closing one; every other node keeps its indentation.
        for node in touched: ET.indent(node, level=2)
        for node in added: node.tail = '\n    '
        last.tail = '\n    '
        waiting[-1].tail = '\n  '
    else:
        ET.indent(root)
    result = xml(root)
    _LAST = (result, root, waiting, index)
    return result


_LAST = None  # (bytes, root, WaitingLinks, index) of the network append_links wrote last
