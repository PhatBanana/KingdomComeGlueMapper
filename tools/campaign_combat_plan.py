"""Resolve legacy controller-owned, nonlethal quest fights for native lowering.

Plans retain the source AST as provenance. Static role/tag references resolve
through controller registration; names never select a special quest handler.
"""
import re

from campaign_behavior_requests import resolve, target
from campaign_rpg_script import upgrade
from campaign_quest_bridge import UnsupportedOperation
from quest_import import literal


def walk(node):
    yield node
    for child in node['children']:
        yield from walk(child)


def attrs(node):
    return {k: literal(v) for k, v in node['attributes'].items()}


def one(values, message):
    values = list(values)
    if len(values) != 1:
        raise UnsupportedOperation(message)
    return values[0]


def objective_actions(root):
    """Retain guards on callback objective mutations instead of flattening them."""
    result = []
    def visit(node, guards):
        a = attrs(node)
        if node['op'] == 'SetQuestObjective':
            if a['quest'] not in ('', '$__object.name'):
                raise UnsupportedOperation('Cross-quest fight outcome needs an explicit binding')
            result.append(dict(objective=a['objective'], operation=a['function'], guards=guards))
            return
        if node['op'] == 'QuestObjectiveCondition':
            if a['quest'] not in ('', '$__object.name'):
                raise UnsupportedOperation('Cross-quest fight guard needs an explicit binding')
            for branch in node['children']:
                if branch['op'] not in ('Then', 'Else'):
                    raise UnsupportedOperation('Unknown objective condition branch')
                visit(branch, guards + [dict(objective=a['objective'],
                    function=a['function'], negate=branch['op'] == 'Else')])
            return
        for child in node['children']:
            visit(child, guards)
    visit(root, [])
    return result


def callback(model, tag):
    return resolve(model, dict(source='$this.id', tree=tag))['program']['root']


def plan(model, request_node):
    request = target(request_node)
    if request is None or request['entity'] != '$__player':
        raise UnsupportedOperation('Only a statically bound player opponent is supported')
    registration = resolve(model, request)
    program = registration['program']
    nodes = list(walk(program['root']))
    variables = {v['name']: v for v in program['variables']}
    actor = re.fullmatch(r"\$?t_actors\[(?:'([\w]+)'|([\w]+))\]", attrs(request_node)['target'])
    if not actor:
        raise UnsupportedOperation('Fight actor must resolve through a source quest role')
    health = one((n for n in nodes if n['op'] == 'ExecuteLua'), 'Ambiguous combat initialization script')
    health_script = upgrade(attrs(health)['code'])
    health_match = re.fullmatch(r"local actor = XGenAIModule.GetEntityByWUID\(data.this.id\); actor.soul:SetState\('health', ([\d.]+)\); data\.(\w+) = player.soul:GetState\('health'\) / ([\d.]+)", health_script)
    if not health_match:
        raise UnsupportedOperation('Combat initialization is not a health snapshot')
    gates = [n for n in nodes if n['op'] == 'NPCStateGate']
    actor_gate = one((n for n in gates if attrs(n)['Target'] == ''), 'Ambiguous actor health gate')
    player_gate = one((n for n in gates if attrs(n)['Target'] == '__player'), 'Ambiguous player health gate')
    for n in gates:
        a = attrs(n)
        if a['State'] != 'Health' or a['Negation'] != 'false' or a['Low'] != a['High']:
            raise UnsupportedOperation('Unsupported combat health gate semantics')
    threshold_var = attrs(actor_gate)['Low'].removeprefix('$')
    if threshold_var not in variables or attrs(player_gate)['Low'] != '$' + health_match[2]:
        raise UnsupportedOperation('Unresolved combat surrender thresholds')
    distance = attrs(one((n for n in nodes if n['op'] == 'DistanceGate'), 'Ambiguous combat distance gate'))
    if distance['Origin'] != '' or distance['Negation'] != 'true' or distance['OpenInMiddle'] != 'false':
        raise UnsupportedOperation('Unsupported combat distance policy')
    homes = [attrs(n) for n in nodes if n['op'] == 'LinkTagFilter' and attrs(n)['tag'] == 'Home']
    if len(homes) != 1 or homes[0]['Child'] != distance['ReferencePt']:
        raise UnsupportedOperation('Fight distance reference is not the source Home link')
    weapons = [attrs(n)['expressions'] for n in nodes if n['op'] == 'Expression'
               and 'preferredWeaponKind' in attrs(n).get('expressions', '')]
    weapon = one(weapons, 'Missing or ambiguous fight weapon policy')
    if not re.search(r'\.preferredWeaponKind\s*=\s*\$enum:weaponChange\.unarmed\b', weapon):
        raise UnsupportedOperation('Unsupported source fight weapon')
    if not re.search(r'\.combatRegimeOverride\s*=\s*\$enum:combatTreeExecutionRegime\.keepRunning\b', weapon):
        raise UnsupportedOperation('Unsupported source fight execution regime')
    additions = [attrs(n)['BuffGUID'] for n in nodes if n['op'] == 'AddBuff' and attrs(n)['SoulWUID'] == 'this.id']
    removals = [attrs(n)['BuffGUID'] for n in nodes if n['op'] == 'RemoveBuffs' and attrs(n)['SoulWUID'] == 'this.id']
    if not additions or sorted(additions) != sorted(removals):
        raise UnsupportedOperation('Combat protection buffs have unbalanced lifetimes')
    partner_filter = one((attrs(n)['condition'] for n in nodes
        if n['op'] == 'LinkDataFilter' and attrs(n)['tag'] == 'QuestActor'), 'Unresolved partner role filter')
    partners = re.findall(r"\$QuestActor == '([\w]+)'", partner_filter)
    if not partners or re.sub(r"\$QuestActor == '[\w]+'", '', partner_filter).strip(' ()|'):
        raise UnsupportedOperation('Dynamic combat partner selection')
    party_tests = [attrs(n) for n in nodes if n['op'] == 'QuestObjectiveCondition'
                   and any(c['op'] == 'Then' and any(x['op'] == 'Wait' and attrs(x)['duration'] == '-1'
                       for x in walk(c)) for c in n['children'])]
    party = {(a['objective'], a['function']) for a in party_tests}
    if len(party) != 1 or next(iter(party))[1] != 'IsObjectiveCompleted':
        raise UnsupportedOperation('Unsupported party combat continuation policy')

    def cutscene(node):
        messages = [attrs(n) for n in walk(node) if n['op'] == 'InstantSendMessageToNPC' and attrs(n).get('type') == 'cutscene']
        aliases = set()
        for a in messages:
            match = re.fullmatch(r"alias\('([\w]+)'\),dialogFadeIn\(true\),state\(\$enum:cutsceneState.doStart\)", a['values'])
            if not match:
                raise UnsupportedOperation('Unsupported post-combat cutscene message')
            aliases.add(match[1])
        return one(aliases, 'Ambiguous post-combat cutscene')
    victory = one((n for n in nodes if n['op'] == 'FuseBox' and
        any(x is actor_gate for c in n['children'] if c['op'] == 'Child' for x in walk(c)) and
        any(c['op'] == 'OnSuccess' and any(x['op'] == 'SetQuestObjective' for x in walk(c)) for c in n['children'])),
        'Missing combat victory cleanup')
    victory_actions = one((c for c in victory['children'] if c['op'] == 'OnSuccess'), 'Missing victory actions')
    win, loss = cutscene(victory_actions), cutscene(player_gate)
    result = dict(schema=1, quest=model['quest'], actor_role=actor[1] or actor[2],
        registration=dict(tag=request['tree'], document=registration['document'], tree=registration['tree']),
        initial_health=float(health_match[1]), player_health_divisor=float(health_match[3]),
        actor_threshold=float(variables[threshold_var]['values']), weapon='unarmed', buffs=additions,
        partners=partners, party_objective=next(iter(party))[0], distance_low=float(distance['Low']),
        distance_high=float(distance['High']), victory_actions=objective_actions(victory_actions),
        outcomes={}, runtime_verified=False)
    result['wake_buff'] = one((attrs(n)['BuffGUID'] for n in nodes
        if n['op'] == 'AddBuff' and attrs(n)['SoulWUID'] == '__player'), 'Unresolved unconsciousness recovery')
    grace = one((attrs(n)['Delta'] for n in nodes if n['op'] == 'GetTime'), 'Unresolved combat reaction grace period')
    if not re.fullmatch(r'\d+(?:\.\d+)?s', grace):
        raise UnsupportedOperation('Unsupported combat reaction grace duration')
    result['reaction_grace'] = grace
    # Preserve the source assault-reaction policy, not just its timer. The
    # native arranged-fight context alone does not suppress crime reactions.
    reaction_links = [attrs(n) for n in nodes if n['op'] == 'AddLink'
                      and attrs(n).get('Tag') == 'suppressAssaultReactions']
    expirations = [attrs(n) for n in nodes if n['op'] == 'LinkDataExpression'
                   and 'suppressAssaultReactions' in attrs(n).get('Expresssion', '')]
    clock = one((attrs(n) for n in nodes if n['op'] == 'GetTime'), 'Missing reaction clock')
    if reaction_links or expirations:
        link = one(reaction_links, 'Ambiguous assault reaction suppression')
        expiry = one(expirations, 'Missing assault reaction expiration')
        if (link['From'] != 'this.id' or link['To'] != '__player'
                or expiry['From'] != 'this.id' or expiry['To'] != '__player'
                or expiry['Expresssion'] != '$suppressAssaultReactions.expiration = $' + clock['OutVar']):
            raise UnsupportedOperation('Unsupported assault reaction suppression binding')
        result['suppress_assault_reactions'] = True
    from campaign_combat_lifecycle import preparation, aftermath
    result['preparation'] = preparation(program['root'])
    for name, alias in [('won', win), ('lost', loss)]:
        tree = callback(model, '_cutscene_' + alias)
        patches = [attrs(n) for n in walk(tree) if n['op'] == 'InstantSendMessageToNPC' and attrs(n).get('type') == 'daycycle:change']
        patch = one(patches, 'Post-fight callback needs one resolved schedule patch')
        behavior = re.search(r"(?:^|,)\s*name\('([\w]+)'\)", patch['values'])
        if not behavior:
            raise UnsupportedOperation('Unresolved post-fight schedule tag')
        followup = callback(model, behavior[1])
        aliases = sorted({a for n in walk(followup) if n['op'] == 'Expression'
            for a in re.findall(r"\.alias\s*=\s*'([^']+)'", attrs(n)['expressions'])})
        result['outcomes'][name] = dict(cutscene=alias, actions=objective_actions(tree),
            schedule_tag=behavior[1], schedule_patch=patch, dialogue_aliases=aliases, schedule_source=followup)
        if any(n['op'] == 'CallBehavior' for n in walk(followup)):
            result['outcomes'][name]['aftermath'] = aftermath(followup)
    return result
