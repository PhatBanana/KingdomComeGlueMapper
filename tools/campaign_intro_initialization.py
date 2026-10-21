"""Preserve a source worker's guarded first-entry placement.

Map spawn placement is not a substitute: the worker can start later, after an
interrupt has moved its actor. Only the recognized persistent source guard is
translated; subsequent starts keep the actor's current position.
"""
import re
import xml.etree.ElementTree as E

from campaign_quest_start_placement import unique, same_pose
from campaign_entity_links import native_guid
from campaign_bindings import ENTITY_ASSETS


def contract(tree):
    moves = tree.findall('Root/OnInit//SetSpatialInfo')
    if not moves:
        return None
    guard = unique(tree.findall('Root/OnInit/Sequence/IfCondition'), 'intro initialization guard')
    match = re.fullmatch(r'\$(\w+) < (\d+)', guard.get('condition', ''))
    if not match or guard.get('failOnCondition') != 'false':
        raise ValueError('Unsupported intro initialization guard')
    phase = unique(tree.findall("Variables/Variable[@name='"+match[1]+"']"), 'intro initialization phase')
    if phase.get('isPersistent') != '1' or phase.get('type') not in ('_int', 'common:int'):
        raise ValueError('Intro initialization requires a persistent integer phase')
    seq = unique(guard.findall('Sequence'), 'intro initialization sequence')
    expected = ['DisablePerception','SetTemporarySuperfaction','GetSpatialInfo','SetSpatialInfo',
                'EnablePerception','Expression','ExecuteLua']
    if [n.tag for n in seq] != expected or len(moves) != 1:
        raise ValueError('Unsupported intro initialization operations')
    disable, faction, get, move, enable, advance, protection = seq
    if (get.get('What') != 'Transform' or move.get('What') != 'Transform'
            or move.get('In') != 'this.id' or move.get('Val') != get.get('Out')
            or advance.get('expressions', '').strip().rstrip(',').strip() != '$'+match[1]+' = '+match[2]
            or any(n.get('Perceptor') != 'true' or n.get('Perceptible') != 'true'
                   or n.get('ToWhom') != '' for n in (disable,enable))):
        raise ValueError('Unsupported intro first-entry placement semantics')
    binding = unique((n for n in tree.findall('Root/OnInit//LinkDataFilter')
                      if n.get('Child') == get.get('In')), 'intro arrival binding')
    role = re.fullmatch(r"\$QuestPlace == '(\w+)'", binding.get('condition',''))
    if binding.get('tag') != 'QuestPlace' or not role:
        raise ValueError('Unresolved intro arrival role')
    # Faction and protection are validated by campaign_intro_factions and owned
    # by its native scoped effect. Never emit the obsolete source faction API.
    return dict(version=1, phase=match[1], threshold=int(match[2]), arrival_role=role[1])


def emit(tree, root, source, stem):
    init = source.get('initialization')
    if not init:
        return
    variables = tree.find('Variables')
    E.SubElement(variables,'Variable',name=init['phase'],type='_int',values='',form='single',isPersistent='1')
    E.SubElement(variables,'Variable',name='arrivalTransform',type='transform',values='',form='single',isPersistent='0')
    seq = E.SubElement(E.SubElement(root,'OnInit',canSkip='1'),'Sequence')
    E.SubElement(seq,'LogToConsole',LogLevel='Info',Message=repr('[GlueMapper intro] '+stem+' enter'))
    first = E.SubElement(E.SubElement(seq,'IfCondition',failOnCondition='false',
                        condition='$'+init['phase']+' < '+str(init['threshold'])),'Sequence')
    # Resolve the destination before disabling perception, so lookup failure
    # cannot leave the actor with perception disabled.
    E.SubElement(first,'GetSpatialInfo',In='$arrivalPlace',Out='$arrivalTransform',What='Transform')
    E.SubElement(first,'DisablePerception',Perceptor='true',Perceptible='true',ToWhom='$this.id')
    E.SubElement(first,'SetSpatialInfo',In='$this.id',Val='$arrivalTransform',What='Transform')
    E.SubElement(first,'EnablePerception',Perceptor='true',Perceptible='true',ToWhom='$this.id')
    E.SubElement(first,'Expression',expressions='$'+init['phase']+' = '+str(init['threshold']))
    E.SubElement(first,'LogToConsole',LogLevel='Info',Message=repr('[GlueMapper intro] '+stem+' first-entry placement complete'))


def bind(objects, project, project_entity, entry, additions, stem, placement, *, validate=False):
    """Bind the source arrival marker independently from the sitting destination."""
    guid = native_guid(int(placement['source_place_guid'],16))
    name = stem+'_arrival'
    found = [e for e in objects if e.get('EntityGuid') == guid]
    changed = False
    if found:
        marker = unique(found, 'intro arrival marker')
        if marker.get('Name') != name or marker.get('EntityClass') != 'TagPoint' or not same_pose(marker,placement['placement']):
            raise ValueError('Intro arrival marker conflicts with source')
    else:
        if validate: raise ValueError('Missing intro arrival marker')
        marker = E.SubElement(objects,'Entity',Name=name,EntityClass='TagPoint',EntityGuid=guid,
            EntityId=str(max(int(e.get('EntityId','0')) for e in objects)+1),**placement['placement'])
        E.SubElement(marker,'Properties',bSaved_by_game='0'); changed=True
    assets = project.find('Assets')
    asset = assets.find("*[@Name='"+name+"']")
    asset_type = ENTITY_ASSETS[marker.get('EntityClass')]
    if asset is None:
        if validate: raise ValueError('Missing intro arrival asset')
        E.SubElement(assets,asset_type,Name=name); changed=True
    elif asset.tag == 'EntityAsset' and not validate:
        # Repair the unreleased initializer's invalid generic asset declaration.
        # The marker identity, class and pose have already been checked above.
        asset.tag = asset_type; changed=True
    elif asset.tag != asset_type: raise ValueError('Intro arrival asset conflicts: expected '+asset_type)
    links = project_entity.find('EntityLinks')
    label = "asset['"+name+"']"
    found = [l for l in links if l.get('Name') == label]
    expected = dict(Name=label,TargetId=marker.get('EntityId'),TargetGuid=guid)
    if found:
        if unique(found,'intro arrival link').attrib != expected: raise ValueError('Intro arrival link conflicts')
    else:
        if validate: raise ValueError('Missing intro arrival link')
        E.SubElement(links,'Link',**expected)
        additions.append((project_entity.get('EntityGuid'),guid,label)); changed=True
    enable = unique(entry.findall("Nodes/EnableBehavior[@Name='"+stem+"_enable']"),'intro activity')
    param = enable.find("Asset[@Name='arrivalPlace']")
    if param is None:
        if validate: raise ValueError('Missing intro arrival parameter')
        E.SubElement(enable,'Asset',Name='arrivalPlace',Alias=name); changed=True
    elif param.get('Alias') != name: raise ValueError('Intro arrival parameter conflicts')
    return changed
