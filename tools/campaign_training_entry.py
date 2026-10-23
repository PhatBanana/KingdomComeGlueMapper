"""Resolve source duel entry positions and stage the native training teleport scene."""
import copy
import hashlib
import re
import xml.etree.ElementTree as E

from campaign_intro_activity import normalized
from campaign_quest_start_placement import unique, linked, pose
from campaign_bindings import parse_link_labels
from character_person import world_entity
from campaign_entity_links import native_guid
from campaign_quest_graph import edge, constant, any_of


def resolve(behavior, arena_behavior, request, quest, entities, archive):
    """Follow the selected request's area and the arena's ordered position links."""
    root = normalized(behavior)
    tree = unique(root.findall("BehaviorTree[@name='"+request+"']"), 'training request')
    message = unique(tree.findall('.//InstantSendMessageToNPC'), 'arena request message')
    if message.get('type') != 'duel:startDuelWithPlayer':
        raise ValueError('Unsupported training arena request')
    search = unique((s for s in tree.findall('.//GraphSearch')
                     if any(n.get('Child') == message.get('target') for n in s)), 'request area search')
    role = unique(search.findall('LinkDataFilter'), 'area place filter')
    match = re.fullmatch(r"\$QuestPlace == '([\w]+)'", role.get('condition',''))
    if role.get('tag') != 'QuestPlace' or not match:
        raise ValueError('Unresolved training arena role')
    controller = unique((e for e in entities if e.get('Name') == quest), 'source quest')
    area = linked(controller, entities, 'QuestPlace', match[1])
    difficulty=re.search(r'(?:^|,)difficulty\((-?\d+)\)(?:,|$)',message.get('values',''))
    if not difficulty:raise ValueError('Missing source arena difficulty')
    arena=normalized(arena_behavior)
    dispatch=unique((g for g in arena.iter('IfCondition')
        if g.get('condition')=='$startDuelMessage.difficulty == '+difficulty[1]), 'arena request dispatch')
    call=unique(dispatch.findall('InstantSendMessageToNPC'),'arena dispatch message')
    routine=re.fullmatch(r"entity\(\$__player\),behaviorName\('([\w]+)'\),behaviorSource\(\$this.id\)",call.get('values',''))
    if call.get('type')!='combat:stimulus:customBehaviorRequest' or not routine:
        raise ValueError('Unsupported source arena dispatch')
    # Select the actual arena function whose handoff matches the source pair.
    candidates=[]
    for t in arena.findall('BehaviorTree'):
        if t.get('name') != routine[1]: continue
        teleports=t.findall('.//FaderBarrier//Teleport')
        if [(n.get('Position'),n.get('Target')) for n in teleports] != [('positions[0]','__player'),('positions[1]','this.id')]:
            raise ValueError('Unsupported source tutorial entry sequence')
        searches=[s for s in t.findall('.//GraphSearch') if s.find("Nodalyzer[@Child='positions']") is not None]
        s=unique(searches,'arena position search')
        if s.get('Origin') != '__area.id' or s.find("LinkTagFilter[@tag='position']") is None:
            raise ValueError('Unsupported arena position binding')
        candidates.append(t)
    unique(candidates,'source sword tutorial arena')
    targets=[]
    for link in area.findall('EntityLinks/Link'):
        label=link.get('Name','').strip()
        # Untagged editor links do not participate in the source position
        # query; they are valid neighbors of the arena's tagged links.
        if not label:continue
        if dict(tag='position',positional=[],named={}) in parse_link_labels(label):
            target=unique((e for e in entities if e.get('EntityId')==link.get('TargetId')), 'arena entry point')
            if target.get('EntityClass')!='TagPoint':raise ValueError('Arena entry is not a TagPoint')
            targets.append(target)
    if len(targets)!=2:raise ValueError('Training requires exactly two ordered arena positions')
    return dict(area_guid=area.get('EntityGuid'), area_role=match[1],
        positions=[dict(role=role, source_guid=e.get('EntityGuid'), **pose(world_entity(archive,e,entities)))
                   for role,e in zip(('player','tutor'),targets)],
        source_behavior_sha256=hashlib.sha256(behavior).hexdigest(),
        source_arena_sha256=hashlib.sha256(arena_behavior).hexdigest())


def stage(mission, project, entry, stem, actor, record, scene, player_asset):
    """Create owned scene anchors; activate equipment only after scene release."""
    aliases=project.find('Skald/Project/Assets')
    project_name=project.find('Skald/Project').get('Name')
    project_host=unique((e for e in mission if e.get('Name')==project_name and e.get('EntityClass')=='SmartObjectHolder'), 'project holder')
    nodes=entry.find('Skald/Level/Nodes')
    prefix=stem+'_entry'
    if any(n.get('Name','').startswith(prefix) for n in nodes):raise ValueError('Entry already installed without receipt')
    next_id=max(int(e.get('EntityId','0')) for e in mission)+1
    links=[];made=[]
    def entity(suffix,kind,transform):
        nonlocal next_id
        name=prefix+'_'+suffix
        guid=native_guid(int.from_bytes(hashlib.sha256(name.encode()).digest()[:8],'little'))
        if any(e.get('Name')==name or e.get('EntityGuid')==guid for e in mission):raise ValueError('Entry entity collision')
        e=E.SubElement(mission,'Entity',Name=name,EntityId=str(next_id),EntityGuid=guid,EntityClass=kind,**transform)
        next_id+=1;E.SubElement(e,'EntityLinks');made.append(e)
        return e
    def link(a,b,label):
        ls=a.find('EntityLinks')
        if ls is None:ls=E.SubElement(a,'EntityLinks')
        E.SubElement(ls,'Link',Name=label,TargetId=b.get('EntityId'),TargetGuid=b.get('EntityGuid'))
        links.append((a.get('EntityGuid'),b.get('EntityGuid'),label))
    holder=entity('scene','CutsceneHolder',{k:record['positions'][0][k] for k in ('Pos','Rotate')})
    E.SubElement(holder,'Properties',esCutsceneName=scene)
    for p in record['positions']:
        point=entity(p['role'],'TagPoint',{k:p[k] for k in ('Pos','Rotate')})
        E.SubElement(point,'Properties',bSaved_by_game='0')
        link(holder,point,'teleport')
        link(point,point,"useAsset['"+player_asset+"']") if p['role']=='player' else link(point,actor,'setting')
    E.SubElement(aliases,'CutsceneHolderAsset',Name=holder.get('Name'))
    link(project_host,holder,"asset['"+holder.get('Name')+"']")
    # Preparation already waits for authorization dialogue release. The scene
    # completion remains guarded so cancellation cannot create new loan items.
    active=unique(nodes.findall("State[@Name='"+stem+"_host_active']"),'worker availability')
    trigger=unique(active.findall("Edge[@To='SetTrue']"),'worker start trigger')
    original=trigger.get('From'); active.remove(trigger)
    pending=E.SubElement(nodes,'State',Name=prefix+'_pending',TypeT='bool');constant(pending,'DefaultValue','false')
    edge(pending,original,'SetTrue')
    handler=E.SubElement(nodes,'CutsceneHandler',Name=prefix+'_play')
    E.SubElement(handler,'Asset',Name='CutsceneHolder',Alias=holder.get('Name'));edge(handler,original,'EnqueueCutscene')
    released=E.SubElement(nodes,'SceneFinishedWaiter',Name=prefix+'_release');edge(released,prefix+'_play.AfterPlay','Enqueue')
    guard=E.SubElement(nodes,'If',Name=prefix+'_ready');edge(guard,prefix+'_release.OnFinished','Exec');edge(guard,prefix+'_pending.State','Condition')
    released_order=E.SubElement(nodes,'TriggerSequence',Name=prefix+'_released_order')
    edge(released_order,prefix+'_ready.True','Exec')
    stopped=E.SubElement(nodes,'If',Name=prefix+'_stopped')
    edge(stopped,prefix+'_released_order.A','Exec');edge(stopped,stem+'_host_stop_requested.State','Condition')
    edge(active,prefix+'_stopped.False','SetTrue');edge(pending,prefix+'_released_order.B','SetFalse')
    lesson=unique((n for n in nodes if n.get('Name')==stem),'lesson instance')
    edge(lesson,prefix+'_stopped.True','workers_stopped')
    stop_gate=unique(nodes.findall("If[@Name='"+stem+"_host_stop_workers']"),'worker stop gate')
    condition=unique(stop_gate.findall("Edge[@To='Condition']"),'stop condition')
    condition.set('From',any_of(nodes,prefix+'_occupied',[active.get('Name')+'.State',pending.get('Name')+'.State']))
    # A canceled queued scene must drain before workers_stopped is acknowledged.
    # Otherwise cleanup would finish while it could still teleport a new session.
    return links, [e.get('EntityGuid') for e in made]
