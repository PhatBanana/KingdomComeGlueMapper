"""Lower a KCD1 quest controller that is one of a few declared shapes.

This is not a controller converter. Each pattern below is one exact tree shape,
matched on the operations and their arguments and never on a quest's name; any
other operation, branch or argument is refused (`Unmatched`) and the controller
stays reported as not converted. The report names every tree a pattern
consumed, so a general converter can take them over and be compared with what
this module wrote.

Pattern `objective_state_rule`:

    Root
      [OnInit: only branches under `$__version.loaded < $enum:gameVersion.<v>`,
       which migrate an old save and do not run in a new game]
      Behavior > Loop(-1) > ProcessMessage(QuestMailbox, variable V) > Switch
        IfCondition  $V.State == $enum:ObjectiveState.Completed & $V.ObjectiveName == '<objective>'
          QuestCondition IsQuestStarted(<this quest>)
            Then: SetQuest <this quest> CancelQuest
            Else: Success
        ...
        DefaultBranch > Success

"When <objective> completes and the quest is started, cancel the quest." It is
lowered inside the quest definition: an `If` on the objective state's
`OnCompleted`, with the quest's `Active` as its condition, feeds the quest's
cancel (`campaign_dialogue_lifecycle.expose_cancel`). Not runtime-verified.
"""
import re
import xml.etree.ElementTree as ET

from campaign_dialogue_lifecycle import CANCEL, QUEST_INPUTS, expose_cancel, host_of
from campaign_quest_bridge import operation_trees
from campaign_quest_graph import edge, xml
from quest_import import literal

PATTERN = 'objective_state_rule'
PREFIX = 'lowered_controller_'
MIGRATION = re.compile(r"\$__version\.loaded\s*<\s*\$enum:gameVersion\.\w+")
MESSAGE = re.compile(r"\$(\w+)\.State\s*==\s*\$enum:ObjectiveState\.(\w+)\s*&\s*\$\1\.ObjectiveName\s*==\s*'([^'\\]+)'")
STATES = {'Completed': 'OnCompleted'}
ACTIONS = {'CancelQuest'}
MAILBOX = 'QuestMailbox'


class Unmatched(ValueError):
    """The controller is not one of the declared shapes."""


def _attributes(node):
    return {k: literal(v) for k, v in node.get('attributes', {}).items()}


def _only(node, op, where):
    children = node.get('children', [])
    if len(children) != 1 or children[0]['op'] != op:
        raise Unmatched(where + ': expected one ' + op + ', found ' + ', '.join(c['op'] for c in children))
    return children[0]


def _success(node, where):
    children = node.get('children', [])
    if len(children) != 1 or children[0]['op'] != 'Success' or children[0].get('children'):
        raise Unmatched(where + ': expected only Success')


def _rule(node, variable, quest, objectives, where):
    attributes = _attributes(node)
    match = MESSAGE.fullmatch(attributes.get('condition', '').strip())
    if (node['op'] != 'IfCondition' or not match or match.group(1) != variable
            or attributes.get('failOnCondition', 'false') != 'false'):
        raise Unmatched(where + ': not an objective-state message test')
    state, objective = match.group(2), match.group(3)
    if state not in STATES:
        raise Unmatched(where + ': objective state ' + state + ' is not a declared trigger')
    if objective not in objectives:
        raise Unmatched(where + ': unknown objective ' + objective)
    guard = _only(node, 'QuestCondition', where)
    guard_attributes = _attributes(guard)
    if (guard_attributes.get('function') != 'IsQuestStarted' or guard_attributes.get('quest') != quest
            or guard_attributes.get('failSubtMissing', 'false') != 'false'):
        raise Unmatched(where + ': guard is not IsQuestStarted of this quest')
    branches = {c['op']: c for c in guard.get('children', [])}
    if set(branches) != {'Then', 'Else'} or len(guard['children']) != 2:
        raise Unmatched(where + ': guard needs exactly Then and Else')
    _success(branches['Else'], where + ' Else')
    action = _only(branches['Then'], 'SetQuest', where + ' Then')
    action_attributes = _attributes(action)
    if (action.get('children') or action_attributes.get('questName') != quest or action_attributes.get('objectiveName', '')
            or action_attributes.get('paramInt', '0') != '0' or action_attributes.get('function') not in ACTIONS
            or set(action_attributes) - {'questName', 'objectiveName', 'paramInt', 'function'}):
        raise Unmatched(where + ': action is not a plain ' + ' / '.join(sorted(ACTIONS)) + ' of this quest')
    return dict(objective=objective, state=state, guard='IsQuestStarted', function=action_attributes['function'])


def _tree(root, quest, objectives, where):
    """(rules, skipped) of one tree, or Unmatched."""
    if root['op'] != 'Root':
        raise Unmatched(where + ': expected Root')
    rules, skipped, behaviors = [], [], 0
    for child in root.get('children', []):
        if child['op'] == 'OnInit':
            for branch in child.get('children', []):
                condition = _attributes(branch).get('condition', '').strip()
                if branch['op'] != 'IfCondition' or not MIGRATION.fullmatch(condition):
                    raise Unmatched(where + ': OnInit does more than migrate an old save')
                skipped.append(dict(condition=condition, reason='migrates an old save; does not run in a new game'))
        elif child['op'] == 'Behavior':
            behaviors += 1
            loop = _only(child, 'Loop', where)
            if _attributes(loop).get('count') != '-1':
                raise Unmatched(where + ': loop is not endless')
            message = _only(loop, 'ProcessMessage', where)
            attributes = _attributes(message)
            variable = attributes.get('variable', '')
            if (attributes.get('inbox') != MAILBOX or not variable or attributes.get('condition', '')
                    or attributes.get('senderInfo', '') or attributes.get('answerVar', '')):
                raise Unmatched(where + ': not a plain ' + MAILBOX + ' message loop')
            switch = _only(message, 'Switch', where)
            branches = switch.get('children', [])
            if not branches or branches[-1]['op'] != 'DefaultBranch':
                raise Unmatched(where + ': switch has no default branch')
            _success(branches[-1], where + ' default')
            for index, branch in enumerate(branches[:-1]):
                rules.append(_rule(branch, variable, quest, objectives, where + ' rule ' + str(index)))
        else:
            raise Unmatched(where + ': unexpected ' + child['op'])
    if behaviors != 1 or not rules:
        raise Unmatched(where + ': expected one message loop with at least one rule')
    if len({(r['objective'], r['state']) for r in rules}) != len(rules):
        raise Unmatched(where + ': two rules for one objective state')
    return rules, skipped


def match(model):
    """dict(pattern, consumed=[tree reports], rules): every controller tree of the quest, or Unmatched."""
    if not (model.get('behavior_documents') or {}):
        return dict(pattern=None, consumed=[], rules=[])
    selected, missing = operation_trees(model)
    if missing:
        raise Unmatched('registered controller trees are missing')
    objectives = {r['objective_name'] for r in model['tables']['quest_objective']['rows']}
    consumed, rules = [], []
    for (document, tree), body in sorted(selected.items()):
        found, skipped = _tree(body['root'], model['quest'], objectives, document + ':' + tree)
        consumed.append(dict(document=document, tree=tree, rules=found, skipped=skipped))
        rules.extend(found)
    if len({(r['objective'], r['state']) for r in rules}) != len(rules):
        raise Unmatched('two controller trees rule on one objective state')
    return dict(pattern=PATTERN if consumed else None, consumed=consumed, rules=rules)


def lower(quest_blob, model):
    """(quest blob, report). Raises Unmatched and changes nothing when the controller is another shape."""
    found = match(model)
    report = dict(found, runtime_verified=False)
    if not found['rules']:
        return quest_blob, report
    root, host = host_of(quest_blob)
    if host.get('Name') != model['quest']:
        raise ValueError('Destination quest identity mismatch')
    nodes = host.find('Nodes')
    if any(n.get('Name', '').startswith(PREFIX) for n in nodes):
        raise ValueError('Controller already lowered')
    ids = {r['objective_name']: r['objective_id'] for r in model['tables']['quest_objective']['rows']}
    sources = []
    for rule in found['rules']:
        state = 'objective_' + ids[rule['objective']]
        if nodes.find("State[@Name='" + state + "']") is None or nodes.find("State[@Name='quest_progress']") is None:
            raise ValueError('Missing native objective state ' + ids[rule['objective']])
        if QUEST_INPUTS[rule['function']] != CANCEL:
            raise Unmatched('no lowering for ' + rule['function'])
        # The source guard (IsQuestStarted) is read when the message arrives, as here.
        gate = ET.SubElement(nodes, 'If', Name=PREFIX + ids[rule['objective']] + '_' + rule['state'].lower())
        edge(gate, 'quest_progress.Active', 'Condition')
        edge(gate, state + '.' + STATES[rule['state']], 'Exec')
        rule.update(native=gate.get('Name'), input=CANCEL)
        sources.append(gate.get('Name') + '.True')
    return expose_cancel(xml(root), sources), report
