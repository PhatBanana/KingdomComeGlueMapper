"""Lower bounded objective -> cutscene -> schedule -> dialogue requests.

Only complete, statically resolved source chains are accepted. This adapter
does not invent rewards, objective transitions, or conversation identifiers.
"""
import posixpath
import re
import xml.etree.ElementTree as E
from campaign_combat_plan import attrs, callback
from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import edge, xml


def only(node, op):
    children = node['children']
    if len(children) != 1 or children[0]['op'] != op:
        raise UnsupportedOperation('Unconverted dialogue request branch: ' + node['op'])
    return children[0]


def plans(model):
    document = model.get('behavior_documents', {}).get(model.get('behavior_entry'), {})
    root = document.get('trees', {}).get('onUpdate', {}).get('root')
    if root is None: return []
    result = []
    def visit(node, valid=True, variable=None):
        a = attrs(node); op = node['op']
        if op == 'ProcessMessage':
            valid = valid and a['inbox'] == 'QuestMailbox' and not a['condition']
            variable = a['variable']
        elif op == 'ExternalLock':
            valid = valid and a['SemaphoreName'] == 'assetsLoaded'
        elif op == 'IfCondition':
            if not valid or not variable: return
            pattern = r"\(\$"+re.escape(variable)+r"\.ObjectiveName == '([^']+)'\) & \(\$"+re.escape(variable)+r"\.State == \$enum:ObjectiveState.Started\)"
            match = re.fullmatch(pattern, a['condition'])
            if not match: return
            try:
                message = attrs(only(node, 'InstantSendMessageToNPC'))
                alias = re.fullmatch(r"alias\('([^']+)'\), state\(\$enum:cutsceneState.doStart\), dialogFadeIn\(true\)", message['values'])
                if message['type'] != 'cutscene' or message['target'] != 'this.id' or not alias: return
                patch = attrs(only(only(callback(model, '_cutscene_'+alias[1]), 'Behavior'), 'InstantSendMessageToNPC'))
                role = re.fullmatch(r't_actors\[(\w+)\]', patch['target'])
                schedule = re.fullmatch(r"add\(true\),handle\('[^']+'\),name\('([^']+)'\),immediate\(true\),once\(true\),sourceId\(\$this.id\),priority\((\d+)\),criticalPriority\(\$enum:daycyclePatchCriticalPriority.cutscene_dialogFadingIn\)", patch['values'])
                if patch['type'] != 'daycycle:change' or not role or not schedule: return
                guard = only(only(callback(model, schedule[1]), 'Behavior'), 'QuestObjectiveCondition')
                g = attrs(guard)
                if g['quest'] != '$__object.name' or g['objective'] != match[1] or g['function'] != 'IsObjectiveStarted': return
                seq = only(only(guard, 'Then'), 'Sequence')
                if [c['op'] for c in seq['children']] != ['Expression', 'LoopUntil']: return
                expression, loop = seq['children']
                if attrs(loop) != {'until':'Success','attemptCount':'0'}: return
                include = attrs(only(loop, 'IncludeTree'))
                if include['File'].lower() != 'final/dialogutils.xml' or include['Name'] != 'dialogInitiator': return
                text = re.sub(r'\s+', '', attrs(expression)['expressions'])
                target = re.fullmatch(r"\$t_dialogParticipants\[0\]=\$__player,\$t_dialogParameters.alias='([^']+)',\$t_dialogParameters.enableGreeting=false,\$t_dialogParameters.enableEnding=false,\$t_dialogParameters.waitOnReceiverDialogEnd=false,", text)
                if target:
                    result.append(dict(objective=match[1], alias=target[1], role=role[1], schedule_priority=int(schedule[2])))
            except (UnsupportedOperation, KeyError):
                pass
            return
        elif op not in {'Root','Behavior','FuseBox','Child','Parallel','Loop','Switch'}:
            valid = False
        for child in node['children']: visit(child, valid, variable)
    visit(root)
    return result


def lower(files, model, bindings):
    out = dict(files); report = []
    roots = {p:E.fromstring(b) for p,b in files.items() if p.startswith('Quests/') and p.endswith('.xml')}
    quests = [(p,r.find('Skald/Quest')) for p,r in roots.items() if r.find('Skald/Quest') is not None and r.find('Skald/Quest').get('Name') == model['quest']]
    if len(quests) != 1: raise ValueError('Missing source request quest')
    qp, quest = quests[0]
    objectives = {r['objective_name']:r['objective_id'] for r in model['tables']['quest_objective']['rows']}
    records = {r['name']:r for r in bindings['bindings']}
    for plan in plans(model):
        matches = [(p,r) for p,r in roots.items() if r.find('.//Dialogue/Decision[@Alias="'+plan['alias']+'"]') is not None]
        if not matches: continue  # Not in this selected conversation scope.
        if len(matches) != 1: raise ValueError('Ambiguous requested dialogue')
        dp, dr = matches[0]; dialog = dr.find('Skald')[0]; name = dialog.get('Name')
        containers = [(p,r.find('Skald')[0]) for p,r in roots.items() if r.find('Skald') is not None and r.find('Skald')[0].tag in ('Level','Project') and any(posixpath.normpath(posixpath.join(posixpath.dirname(p),d.get('File'))) == dp for d in r.findall('./Skald/*/Definitions/Definition'))]
        if len(containers) != 1: raise ValueError('Missing dialogue request container')
        cp, host = containers[0]; nodes = host.find('Nodes'); stem = name+'_source_request'
        if nodes.find("SceneFinishedWaiter[@Name='"+stem+"']") is not None: continue
        names = bindings['references'].get("t_actors['"+plan['role']+"']", [])
        if len(names) != 1 or records[names[0]]['asset_type'] != 'SoulAsset': raise ValueError('Missing dialogue actor dependency')
        soul = records[names[0]]['attributes']['SharedSoulGuids']
        instances = [n for n in nodes if n.tag == quest.get('Name')]
        if len(instances) != 1: raise ValueError('Missing quest request instance')
        port = 'source_request_'+plan['objective']
        E.SubElement(quest.find('Ports'),'Port',Name=port,Direction='Out',Type='trigger')
        output = E.SubElement(quest.find('Nodes'),'Output',Name=port)
        edge(output,'objective_'+objectives[plan['objective']]+'.OnStarted',port)
        waiter = E.SubElement(nodes,'SceneFinishedWaiter',Name=stem)
        edge(waiter,instances[0].get('Name')+'.'+port,'Enqueue')
        instance = nodes.find("*[@Name='"+name+"']")
        if instance is None: raise ValueError('Missing dialogue instance')
        edge(instance,stem+'.OnFinished','EnqueueDialogue')
        assets = host.find('Assets')
        if assets is None: assets = E.SubElement(host,'Assets')
        E.SubElement(assets,'SoulAsset',Name=stem+'_actor',SharedSoulGuids=soul)
        params = E.SubElement(nodes,'Function',Name=stem+'_params',MethodName='wh::dialogmodule::CreateDialogParams',DeclaringType='wh::dialogmodule')
        E.SubElement(params,'Asset',Name='Participants',Alias=stem+'_actor')
        edge(instance,stem+'_params.DialogParams','DialogParams')
        dialog.tag = 'ForcedDialog'
        body = dialog.find('Dialogue'); body.set('Initiator','NonPlayer'); body.set('AllowGreeting','false'); body.attrib.pop('Priority',None)
        for p in (qp,cp,dp): out[p] = xml(roots[p])
        report.append(dict(**plan, path=dp, runtime_verified=False))
    return {p:b for p,b in out.items() if files[p]!=b},report
