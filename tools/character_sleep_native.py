"""Validate the exported native bed resource, scoped sleep contexts and activity."""
import copy
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

from campaign_entity_links import guid_value
from upgrade_map import read

TABLE = 'Libs/Tables/ai/smartEntity/SmartEntity__so_bed.xml'


def contract(target):
    target = Path(target)
    with zipfile.ZipFile(target/'Data/Tables.pak') as z:
        template = E.fromstring(read(z, TABLE)).find('.//SmartEntityTemplate')
    resource = template.find("Resources/Resource[@Name='use']")
    behavior = template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use']")
    if resource is None or resource.get('MaxInstances') != '1' or behavior is None or behavior.get('Resource') != 'use' or behavior.get('InitialState') != 'Enabled':
        raise ValueError('Native sleep reservation changed')
    loc = behavior.find('TreeLocation')
    with zipfile.ZipFile(target/'Data/Scripts.pak') as z:
        root = E.fromstring(read(z, 'AI/'+loc.get('FileName'))).find("BehaviorTree[@name='"+loc.get('TreeName')+"']/Root")
    stance = root.find(".//StanceElement[@smartObject='$__object.id'][@stance='lying']") if root is not None else None
    context = stance.find("AddBuffElement/EntityContextPresetElement[@contextPreset='sleeping']") if stance is not None else None
    if (root is None or root.get('OneTimeOnly') != 'false' or context is None or
            context.find("Sequence/Wait[@duration=\"'15s'\"][@timeType='GameTime']") is None or
            context.find('Sequence/WaitAction') is None):
        raise ValueError('Native sleep stance/context lifetime changed')
    with zipfile.ZipFile(target/'Data/Levels/trosecko/level.pak') as z:
        mission = E.fromstring(read(z, 'objects_mission0.xml'))
        rows = E.fromstring(read(z, 'tables/ai/scheduler.xml')).find('Schedulers')
    beds = {str(guid_value(e.get('EntityGuid'))) for e in mission if e.find('Properties') is not None
            and e.find('Properties').get('guidSmartObjectType') == template.get('DatabaseId')}
    expected = dict(BehaviorName='use', ProvidedRole='sleeper', Priority='0', Privileged='false',
                    AllowedGenders='0', TimeOfDayStart='0', TimeOfDayEnd='1440')
    for link in rows.findall('.//S_ActivityLink'):
        p = link.find('Parameters')
        if (link.get('TargetGuid') in beds and link.get('PositioningDelegate') == '0' and p is not None and
                all(p.get(k) == v for k, v in expected.items()) and
                not any(k in p.attrib for k in ('RequiredRole', 'RequiredContext', 'LinkTag', 'SocialClass', 'BuffTag'))):
            return template.get('DatabaseId'), copy.deepcopy(link)
    raise ValueError('Missing unrestricted native sleeper activity')
