"""Lower authored job routes to ordered targets for native point movement.

The points describe work locations; KCD2 owns navigation between them. They
are not passed to the engine as a predefined movement track.
"""
import copy
import hashlib
import math
import xml.etree.ElementTree as E

from campaign_entity_links import native_guid

FIRST = 'gm_work_first'
NEXT = 'gm_work_next'


def connect(source, target, label):
    links = source.find('EntityLinks')
    if links is None:
        links = E.SubElement(source, 'EntityLinks')
    matches = links.findall("Link[@Name='" + label + "']")
    attributes = dict(Name=label, TargetId=target.get('EntityId'), TargetGuid=target.get('EntityGuid'))
    if matches and (len(matches) != 1 or matches[0].attrib != attributes):
        raise ValueError('Conflicting native job waypoint link: ' + label)
    if not matches:
        E.SubElement(links, 'Link', attributes)
    return source.get('EntityGuid'), target.get('EntityGuid'), label


def bind_points(mission, route, points):
    """Stable per-route identities preserve every vertex and its ordering."""
    if len(points) < 2:
        raise ValueError('Job route requires at least two points')
    for point in points:
        if len(point) != 3 or not all(math.isfinite(v) for v in point):
            raise ValueError('Invalid native job waypoint')
    entities, edges = [], []
    for index, point in enumerate(points):
        identity = 'job-waypoint/' + route.get('EntityGuid') + '/' + str(index)
        guid = native_guid(int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], 'little'))
        position = ','.join(format(v, '.10g') for v in point)
        matches = [e for e in mission if e.get('EntityGuid') == guid]
        if len(matches) > 1:
            raise ValueError('Duplicate native job waypoint')
        if matches:
            entity = matches[0]
            if entity.get('EntityClass') != 'TagPoint' or entity.get('Pos') != position:
                raise ValueError('Existing native job waypoint differs from source')
        else:
            entity = E.SubElement(mission, 'Entity', Name='gm_work_point_' + guid,
                EntityClass='TagPoint', EntityGuid=guid, Pos=position,
                EntityId=str(max((int(e.get('EntityId', '0')) for e in mission), default=0)+1))
            E.SubElement(entity, 'Properties', bSaved_by_game='0')
        entities.append(entity)
    for source, target, label in [(route, entities[0], FIRST),
            *((a, b, NEXT) for a, b in zip(entities, entities[1:]))]:
        edges.append(connect(source, target, label))
    if entities[-1].find("EntityLinks/Link[@Name='" + NEXT + "']") is not None:
        raise ValueError('Native job route has a stale continuation')
    return edges


def lookup(parent, origin, target, label, required=True):
    if not required:
        # End-of-route is expected. A missing successor must not turn successful
        # travel into failure before the final work phase can execute.
        parent = E.SubElement(parent, 'SuppressFailure')
    search = E.SubElement(parent, 'GraphSearch', Origin=origin, Borders='', depth='1',
        selection='true', SearchPattern='Depth', EdgePruning="'parent,inventory'",
        AllowedEdges='', SubGraph='', AllowSubtraph='false', includeOrigin='false',
        excludeOrigin='false', failOnEmpty=str(required).lower(), SetOperationChoice='Intersection|And',
        errorOnEmpty='false', shortCircuit='true', skipTraversed='true')
    E.SubElement(search, 'LinkTagFilter', tag="'" + label + "'", prune='true',
        negprune='unknown', Parent='', Child='', Data='')
    E.SubElement(search, 'Nodalyzer', Quantifiers='Exists', Parent='', Child=target, saveVersion='2')


def native_approach(sequence, destination):
    """Retain native hand checks and approach guards; only replace the target."""
    children = list(sequence)
    actions = [i for i, node in enumerate(children) if node.tag == 'UnstanceAction']
    if len(actions) != 1 or not actions[0]:
        raise ValueError('Native work approach/action boundary is ambiguous')
    approach = copy.deepcopy(children[:actions[0]])
    moves = [n for child in approach for n in child.iter('Move')]
    if not moves or any(n.get('destinationSpecification') != '$__object.id'
                        or n.get('destinationSpecification2') for n in moves):
        raise ValueError('Unsupported native work movement contract')
    for child in approach:
        for node in child.iter():
            for key, value in list(node.attrib.items()):
                if value == '$__object.id':
                    node.set(key, destination)
    return approach
