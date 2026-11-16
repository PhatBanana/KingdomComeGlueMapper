"""Behaviour nodes whose outcome the engine, a lock table or another NPC decides.

`behavior.Behavior` interprets the control flow of an emitted tree. This module
adds the node types converted KCD1 controllers use on top of it:

    lab gates       GameContextBarrier, IfGate, ExternalLock, Synchronize, Semaphore
    engine gates    DistanceGate, AreaPresenceGate, DialogGate, ActorStateBarrier,
                    DetailBehaviorBarrier, ProfileLoadedGate, FaderBarrier
    engine actions  Move, ExactMove, Turn, CallBehavior, StopMovement, DrawAction,
                    TeleportAction, Look
    queries         GraphSearch with its filters, LuaGate, AreaPresenceListener
    structure       FuseBox, For, LoopUntil, AtomicDecorator, InstantSemaphore
    messages        SendMessageToNPC, InstantMultiSendMessageToNPC
    effects         AddBuff, RemoveBuffs, GameOver, AddLink, RemoveLink, GetTime,
                    GetSpatialInfo, SetSpatialInfo, SetExternalLock, ExecuteLua

Nothing here guesses what the engine does. An engine-dependent outcome is a
*boundary*: the task stops with `task['boundary']` naming the node and the
outcomes it accepts, and the scenario (or the exhaustive walk) supplies one
with `Behavior.resolve`. How a node behaves between boundaries is a named
assumption in `world.ASSUMPTIONS` (`behavior.*`); reaching it without the
scenario declaring that assumption is UNSUPPORTED. Effects are a ledger
(`Behavior.effects`): the lab records that a tree asked for a buff, a link, a
teleport or a Lua script's declared cluster effect; it does not apply them to
a simulated world.

Attribute sets are the ones retail KCD2 trees carry (Scripts.pak `AI/**`); an
attribute outside them is reported instead of ignored.
"""
import copy
import json
import re

from . import Unsupported
from .expressions import assignments, boolean, duration, literal, parts

LAB_GATES = {'GameContextBarrier', 'IfGate', 'ExternalLock', 'Synchronize', 'Semaphore'}
ENGINE_GATES = {'DistanceGate', 'AreaPresenceGate', 'DialogGate', 'ActorStateBarrier', 'DetailBehaviorBarrier',
                'ProfileLoadedGate', 'FaderBarrier'}
GATES = LAB_GATES | ENGINE_GATES
# Rechecked while their child runs: the lab can see the condition change.
HALTABLE = {'GameContextBarrier', 'IfGate', 'ExternalLock'}
ENGINE_ACTIONS = {'Move', 'ExactMove', 'Turn', 'CallBehavior', 'StopMovement', 'DrawAction', 'TeleportAction', 'Look'}
EFFECTS = {'AddBuff', 'RemoveBuffs', 'GameOver', 'AddLink', 'RemoveLink', 'SetSpatialInfo', 'GetSpatialInfo',
           'GetTime', 'SetExternalLock', 'ExecuteLua', 'InstantMultiSendMessageToNPC'}
FILTERS = {'LinkTagFilter', 'LinkDataFilter', 'WUIDFilter', 'EvaLLyzer', 'Nodalyzer'}
STRUCTURE = {'FuseBox', 'For', 'LoopUntil', 'AtomicDecorator', 'InstantSemaphore'}
ENGINE_NODES = GATES | ENGINE_ACTIONS | EFFECTS | FILTERS | STRUCTURE | {
    'SendMessageToNPC', 'AreaPresenceListener', 'GraphSearch', 'LuaGate'}
BRANCHES = {'OnSuccess', 'OnFail'}

EDITOR = {'hasInputBreakpoint', 'comment', 'breakpointFlags', 'editorPosX', 'editorPosY', 'isCollapsed', 'nodeLabel',
          'comment_box', 'comment_box_color'}
LOCK = {'atomic', 'OutsideQueuePosVariable', 'InsidePosVariable', 'TimerType', 'OutsideTimerValue',
        'LockManagerType', 'SemaphoreName', 'RunLogic'}
MOVE = {'destinationSpecification', 'destinationSpecification2', 'destinationSpecification3', 'speed',
        'additionalParams', 'pathFindingParams', 'staminaPolicy', 'pathInfo', 'AnimationToPlay', 'AnimationContext'}
SCHEMA = {
    'GameContextBarrier': {'context', 'Negation', 'RunLogic'},
    'IfGate': {'atomic', 'condition', 'RunLogic'},
    'ExternalLock': LOCK,
    'Synchronize': LOCK | {'SemaphoreCount', 'InsideTimerValue', 'InvalidateOnExpire'},
    'Semaphore': LOCK | {'SemaphoreCount'},
    'InstantSemaphore': {'SemaphoreCount', 'LockManagerType', 'SemaphoreName'},
    'SetExternalLock': {'LockManagerType', 'Locked', 'LockName'},
    'DistanceGate': {'Origin', 'ReferencePt', 'Low', 'High', 'Negation', 'OpenInMiddle', 'RunLogic'},
    'AreaPresenceGate': {'aiObjects', 'area', 'amount', 'presence', 'RunLogic'},
    'AreaPresenceListener': {'aiObjects', 'area', 'trackIn', 'trackOut', 'reportInitialState'},
    'DialogGate': {'Who', 'Negation', 'EndDialogInRoot', 'Condition', 'RunLogic', 'WaitForTwins'},
    'ActorStateBarrier': {'Who', 'ToState', 'NegateTo', 'RunLogic'},
    'DetailBehaviorBarrier': {'RunLogic'},
    'ProfileLoadedGate': {'LayerName', 'NegateTo', 'RunLogic'},
    'FaderBarrier': {'Fader', 'MuteSounds'},
    'FuseBox': {'StatusPropagation', 'OneCleanup', 'saveVersion'},
    'For': {'startIndex', 'endIndex', 'step', 'array', 'iterator', 'value', 'break'},
    'LoopUntil': {'until', 'attemptCount'},
    'AtomicDecorator': set(),
    'SendMessageToNPC': {'target', 'type', 'values', 'variable', 'timeType', 'timeoutType', 'timeout', 'answer'},
    'InstantMultiSendMessageToNPC': {'targets', 'successMode', 'failureMode', 'type', 'values', 'variable'},
    'AddBuff': {'SoulWUID', 'BuffGUID'},
    'RemoveBuffs': {'SoulWUID', 'BuffGUID', 'BuffTagId'},
    'GameOver': {'Reason'},
    'AddLink': {'From', 'To', 'Tag', 'Data', 'LinkOpHandleMode'},
    'RemoveLink': {'From', 'To', 'Tag', 'LinkOpHandleMode'},
    'GetSpatialInfo': {'In', 'Out', 'What'},
    'SetSpatialInfo': {'In', 'Val', 'What'},
    'GetTime': {'TimeType', 'OutVar', 'Delta'},
    'ExecuteLua': {'code'},
    'LuaGate': {'code', 'saveVersion'},
    'Move': MOVE | {'stopWithinDistance', 'stopDistanceVariation', 'rayCasteFlee', 'successDistance'},
    'ExactMove': MOVE | {'directionType', 'directionSpecification', 'animationTriggerDist', 'precise'},
    'Turn': {'target', 'destinationType', 'align', 'stopWithinAngle', 'randomMinAngle', 'randomMaxAngle',
             'randomTurnRightChance', 'stopRunninganimation'},
    'CallBehavior': {'Target', 'BehaviorName', 'stopAfterFirstFound', 'ignoreDropUnloading'},
    'StopMovement': {'waitUntilStopped'},
    'DrawAction': {'WeaponSet', 'fullBody', 'tags', 'useSelectedWeaponSet'},
    'TeleportAction': {'Position', 'EndInterruptOnActionStart'},
    'Look': None,
    'GraphSearch': {'Origin', 'Borders', 'depth', 'selection', 'SearchPattern', 'EdgePruning', 'AllowedEdges', 'SubGraph',
                    'AllowSubtraph', 'includeOrigin', 'excludeOrigin', 'failOnEmpty', 'SetOperationChoice',
                    'errorOnEmpty', 'shortCircuit', 'skipTraversed'},
    'LinkTagFilter': {'tag', 'prune', 'negprune', 'Parent', 'Child', 'Data'},
    'LinkDataFilter': {'tag', 'condition', 'prune', 'negprune', 'Parent', 'Child', 'Data'},
    'WUIDFilter': {'WUID', 'Source', 'prune', 'negprune', 'Parent', 'Child'},
    'EvaLLyzer': {'Expresion', 'Quantifiers', 'saveVersion'},
    'Nodalyzer': {'Quantifiers', 'Parent', 'Child', 'saveVersion'},
}
CHILDREN = dict({tag: 1 for tag in GATES | {'For', 'LoopUntil', 'AtomicDecorator', 'InstantSemaphore', 'AreaPresenceListener'}},
                **{tag: 0 for tag in ENGINE_ACTIONS | EFFECTS | FILTERS | {'SendMessageToNPC'}})
OUTCOMES = {'action': ('success', 'fail'), 'gate': ('open',), 'query': ('match', 'empty'),
            'lua': ('true', 'false'), 'message': ('processed', 'failed'), 'listener': ('in', 'out')}
RUN_LOGIC = ('KeepRunning', 'Halt')
IDENTIFIER = re.compile(r'[A-Za-z_]\w*')


def outputs(node):
    """Variables a GraphSearch writes when it finds something, in document order."""
    found = []
    for child in node:
        names = []
        if child.tag == 'EvaLLyzer':
            for statement in parts(child.get('Expresion', '')):
                target = parts(statement, '=')[0].strip().removeprefix('$')
                if statement and IDENTIFIER.fullmatch(target): names.append(target)
        else:
            names = [child.get(a, '').removeprefix('$') for a in ('Parent', 'Child', 'Data') if child.get(a, '')]
        for name in names:
            if name not in found: found.append(name)
    return found


class EngineNodes:
    """Mixed into Behavior. Uses its tasks, nodes, record() and graph."""

    def _init_engine(self, lua):
        # Lab tables, not engine state: who holds which lock, what the trees asked the engine for.
        self.locks, self.semaphores, self.sync = {}, {}, {}
        self.effects, self.buffs, self.links = [], {}, []
        self.lua = copy.deepcopy(lua or {})
        for code, declared in self.lua.items():
            if not isinstance(declared, dict) or not declared.get('cluster') or set(declared) - {'cluster', 'assign'}:
                raise ValueError('A Lua declaration needs a cluster and at most an assign map: ' + code[:60])

    def assume(self, name):
        return self.graph.world.assume(name)

    # -- loading

    def _schema(self, node):
        tag = node.tag
        if tag not in ENGINE_NODES or tag in self.contracts: return []
        found = []
        allowed = SCHEMA.get(tag)
        if allowed is not None:
            extra = sorted(set(node.attrib) - allowed - EDITOR)
            if extra: found.append(tag + ' has attributes the lab does not model: ' + ', '.join(extra))
        count = CHILDREN.get(tag)
        if count is not None and len(node) != count:
            found.append('%s needs exactly %d child node%s' % (tag, count, '' if count == 1 else 's'))
        if tag in GATES and tag != 'FaderBarrier' and node.get('RunLogic') not in RUN_LOGIC:
            found.append(tag + ' needs RunLogic KeepRunning or Halt')
        if node.get('atomic', 'false') != 'false':
            found.append(tag + ' with atomic=true needs native evidence')
        if tag in ('ExternalLock', 'Synchronize', 'Semaphore'):
            if literal(node.get('OutsideTimerValue', '')) not in (-1, '-1') or node.get('TimerType') != 'GameTime':
                found.append(tag + ' with a queue timeout is not modelled')
            if node.get('OutsideQueuePosVariable') or node.get('InsidePosVariable'):
                found.append(tag + ' queue position outputs are not modelled')
        if tag == 'Synchronize' and (literal(node.get('InsideTimerValue', '')) not in (-1, '-1')
                                      or node.get('InvalidateOnExpire') != 'false'):
            found.append('Synchronize with an inside timer is not modelled')
        if tag == 'FuseBox':
            tags = [c.tag for c in node]
            if tags.count('Child') != 1 or set(tags) - {'Child', 'OnSuccess', 'OnFail'} or len(set(tags)) != len(tags):
                found.append('FuseBox needs one Child and at most one OnSuccess and one OnFail')
            if node.get('StatusPropagation') not in ('Child', 'Success', 'CleanUp') or node.get('OneCleanup') not in ('true', 'false'):
                found.append('FuseBox needs StatusPropagation and OneCleanup')
        if tag == 'LoopUntil' and node.get('until') not in ('Success', 'Fail'):
            found.append('LoopUntil needs until Success or Fail')
        if tag == 'SendMessageToNPC' and (literal(node.get('timeout', '')) not in (-1, '-1')
                                           or node.get('timeoutType') != 'OnProcessed' or node.get('timeType') != 'GameTime'):
            found.append('SendMessageToNPC is modelled only with an infinite OnProcessed wait')
        if tag == 'GraphSearch' and any(c.tag not in FILTERS for c in node):
            found.append('GraphSearch has a filter the lab does not model: '
                         + ', '.join(sorted({c.tag for c in node if c.tag not in FILTERS})))
        if tag == 'LuaGate' and (set(c.tag for c in node) - {'Then', 'Else'} or len(node) > 2
                                 or len({c.tag for c in node}) != len(node)):
            found.append('LuaGate needs at most one Then and one Else')
        if tag == 'ExecuteLua' and node.get('code', '') not in self.lua:
            found.append('Lua script has no declared cluster effect')
        if tag == 'GetTime' and node.get('TimeType') != 'GameTime':
            found.append('GetTime is modelled for GameTime only')
        return found

    # -- boundaries

    def _boundary(self, name, task, kind, path, node, **extra):
        task['status'] = 'external'
        task['boundary'] = dict(kind=kind, node=path, operation=node.tag, outcomes=list(OUTCOMES[kind]), **extra)
        self.record('behavior_request', task=name, node=path, operation=node.tag, boundary=kind,
                    attributes={k: v for k, v in node.attrib.items() if k not in EDITOR})

    def boundaries(self):
        """[(task, boundary)] for every task that waits for an engine outcome, in task order."""
        return [(n, copy.deepcopy(t['boundary'])) for n, t in self.tasks.items()
                if t['status'] == 'external' and 'boundary' in t]

    def open_gates(self):
        """[(task, path, operation, RunLogic)] for engine gates whose child is running."""
        return [(n, f['path'], self.nodes[f['path']].tag, self.nodes[f['path']].get('RunLogic', 'KeepRunning'))
                for n, t in self.tasks.items() for f in t['frames']
                if f.get('gate') == 'open' and self.nodes[f['path']].tag in ENGINE_GATES]

    def _resolve_boundary(self, name, task, outcome, values):
        boundary = task['boundary']
        if outcome not in boundary['outcomes']:
            raise ValueError('%s accepts %s, not %s' % (boundary['operation'], '/'.join(boundary['outcomes']), outcome))
        frame = task['frames'][-1]
        node = self.nodes[frame['path']]
        if values and boundary['kind'] not in ('query', 'message'):
            raise ValueError('Only a search result or a message answer carries values')
        # Refuse a malformed outcome before anything changes: the boundary stays open.
        if boundary['kind'] == 'query':
            wanted = outputs(node) if outcome == 'match' else []
            if sorted(values or {}) != sorted(wanted):
                raise ValueError('The search writes %s; the outcome supplies %s' % (wanted, sorted(values or {})))
        if boundary['kind'] == 'message':
            answer = node.get('answer', '').removeprefix('$') if outcome == 'processed' else ''
            if set(values or {}) != ({answer} if answer else set()):
                raise ValueError('The message answer must supply exactly: ' + (answer or 'nothing'))
        self.record('behavior_outcome', task=name, node=frame['path'], outcome=outcome, values=values)
        del task['boundary']
        task['status'] = 'running'
        kind = boundary['kind']
        if kind == 'action': self._finish(name, outcome == 'success')
        elif kind == 'gate': frame['engine_open'] = True
        elif kind == 'lua': frame['lua_result'] = outcome == 'true'
        elif kind == 'listener': frame['event'] = outcome
        elif kind == 'query':
            if outcome == 'empty': self._finish(name, node.get('failOnEmpty') != 'true')
            else:
                variables, _ = self._environment(name, frame)
                for key in outputs(node): variables[key] = copy.deepcopy(values[key])
                self._finish(name, True)
        elif kind == 'message':
            self.graph.messages = [m for m in self.graph.messages if m['id'] != boundary['message']]
            if values:
                variables, _ = self._environment(name, frame)
                for key, value in values.items(): variables[key] = copy.deepcopy(value)
            self._finish(name, outcome == 'processed')

    def close_gate(self, name, path):
        """The engine says an open engine gate's condition stopped holding."""
        task = self.tasks[name]
        index = next((i for i, f in enumerate(task['frames']) if f['path'] == path and f.get('gate') == 'open'), None)
        if index is None or self.nodes[path].tag not in ENGINE_GATES:
            raise ValueError('No open engine gate at ' + path)
        halt = self.nodes[path].get('RunLogic') == 'Halt'
        self.record('behavior_gate', task=name, node=path, operation=self.nodes[path].tag, state='closed', halted=halt)
        if halt:
            self._unwind(name, index + 1)
            frame = task['frames'][index]
            frame.pop('child_result', None)
            frame['engine_open'], frame['gate'] = False, 'closed'
            task['status'] = 'running'
        self.pump()

    # -- unwinding

    def _unwind(self, name, keep):
        """Drop the frames above `keep`, running what an interruption owes: cleanup and releases."""
        task = self.tasks[name]
        while len(task['frames']) > keep:
            frame = task['frames'][-1]
            node = self.nodes[frame['path']]
            for child in frame.get('parallel_children', []): self._cancel(child)
            if node.tag == 'AtomicDecorator':
                raise Unsupported('Interrupting a running atomic section needs native evidence: ' + frame['path'])
            if node.tag == 'FuseBox' and frame.get('phase'):
                self._interrupt_fusebox(name, task, frame, node)
            self._release(name, frame, node)
            if frame.get('call_scope') and frame['path'] in self.declarations:
                self.tasks[task.get('scope', name)].get('call_scopes', {}).pop(frame['call_scope'], None)
            task['frames'].pop()
        task.pop('boundary', None)

    def _interrupt_fusebox(self, name, task, frame, node):
        if frame['phase'] != 'child':
            raise Unsupported('Interrupting a FuseBox cleanup needs native evidence: ' + frame['path'])
        if self.assume('behavior.fusebox.interrupted') != 'on_fail': raise Unsupported('Unknown FuseBox interruption policy')
        index = next((i for i, c in enumerate(node) if c.tag == 'OnFail'), None)
        self.record('behavior_cleanup', task=name, node=frame['path'], branch='OnFail' if index is not None else None)
        if index is None: return
        self.serial += 1
        helper = name + ':cleanup:' + str(self.serial)
        self.tasks[helper] = dict(frames=[dict(path=frame['path'] + '/' + str(index), index=0, call_scope=frame.get('call_scope'))],
                                  status='running', scope=task.get('scope', name))
        try:
            while self.tasks[helper]['status'] == 'running': self._step(helper)
            if self.tasks[helper]['status'] not in ('success', 'fail'):
                raise Unsupported('A FuseBox cleanup that waits cannot run during an interruption: ' + frame['path'])
        finally:
            del self.tasks[helper]

    def _release(self, name, frame, node):
        holder = name + '|' + frame['path']
        if frame.get('holding'):
            held = self.semaphores.get(frame['holding'], [])
            if holder in held: held.remove(holder)
            if not held: self.semaphores.pop(frame['holding'], None)
            frame.pop('holding')
        if node.tag == 'Synchronize':
            for key in [k for k, waiting in self.sync.items() if [name, frame['path']] in waiting]:
                self.sync[key].remove([name, frame['path']])
                if not self.sync[key]: del self.sync[key]

    def _recheck_gates(self):
        """A lab gate with RunLogic Halt stops its child when its condition stops holding."""
        for name, task in list(self.tasks.items()):
            if task['status'] in ('success', 'fail', 'canceled'): continue
            for index, frame in enumerate(task['frames'][:-1]):
                node = self.nodes[frame['path']]
                if frame.get('gate') != 'open' or node.tag not in HALTABLE or node.get('RunLogic') != 'Halt': continue
                variables, expr = self._environment(name, frame)
                if self._lab_gate(name, task, frame, node, variables, expr, recheck=True): continue
                self.record('behavior_gate', task=name, node=frame['path'], operation=node.tag, state='closed', halted=True)
                self._unwind(name, index + 1)
                frame.pop('child_result', None)
                frame['gate'] = 'closed'
                task['status'] = 'running'
                break

    # -- names and tables

    def _text(self, value, variables, what):
        """A quoted name; `$name` inside it is replaced by that string variable."""
        text = literal(value)
        if not isinstance(text, str) or not text or text == value:
            raise Unsupported(what + ' must be a quoted name: ' + str(value))

        def bound(match):
            found = variables.get(match[1])
            if not isinstance(found, str): raise Unsupported(what + ' reads an unbound name: $' + match[1])
            return found
        return re.sub(r'\$([A-Za-z_]\w*)', bound, text)

    def _lock_key(self, name, task, node, attribute, variables):
        scope = node.get('LockManagerType')
        if scope not in ('Local', 'Intellect', 'Global'): raise Unsupported('Unknown lock manager: ' + str(scope))
        if self.assume('behavior.lock.scope') != 'controller_npc_global': raise Unsupported('Unknown lock scope policy')
        text = self._text(node.get(attribute, ''), variables, 'Lock')
        return scope + '|' + (task.get('scope', name) + '|' if scope == 'Intellect' else '') + text

    def _count(self, node, expr):
        count = expr(node.get('SemaphoreCount', ''))
        if type(count) is not int or count < 1: raise Unsupported('Semaphore count must be a positive integer')
        return count

    def _effect(self, name, path, effect, **values):
        entry = dict(effect=effect, tree=self.tasks[self.tasks[name].get('scope', name)].get('tree'), node=path, **values)
        self.effects.append(entry)
        self.record('behavior_effect', task=name, **entry)

    def _message(self, node, path, expr):
        """(type, content) of a message node; a bare word in a field is a string only under its assumption."""
        typ = literal(node.get('type', ''))
        if not isinstance(typ, str) or not re.fullmatch(r'[A-Za-z_]\w*(?::[A-Za-z_]\w*)*', typ):
            raise Unsupported('NPC message needs an explicit type: ' + path)
        variable, values = node.get('variable', ''), node.get('values', '')
        if variable and values: raise Unsupported('Combined message variable and initializer needs an adapter: ' + path)
        content = copy.deepcopy(expr(variable)) if variable else {}
        for field in parts(values) if values else ():
            match = re.fullmatch(r'([A-Za-z_]\w*)\s*\((.*)\)', field, re.S)
            if not match or match[1] in content: raise Unsupported('Malformed or duplicate message field: ' + field)
            text = match[2].strip()
            if IDENTIFIER.fullmatch(text) and text not in ('true', 'false'):
                if self.assume('behavior.message.bare_word') != 'string': raise Unsupported('Unknown bare word policy')
                self.record('behavior_bare_word', node=path, field=match[1], value=text)
                content[match[1]] = text
            else: content[match[1]] = expr(text)
        return typ, content

    # -- execution

    def _lab_gate(self, name, task, frame, node, variables, expr, recheck=False):
        tag = node.tag
        if tag == 'GameContextBarrier':
            negation = literal(node.get('Negation', ''))
            if type(negation) is not bool: raise Unsupported('GameContextBarrier needs a literal Negation')
            value = self.graph.game_context(node.get('context'))
            if not recheck or value == negation:
                self.record('game_context_gate', task=name, node=frame['path'], context=node.get('context'),
                            result=value, negation=negation)
            return value != negation
        if tag == 'IfGate': return boolean(expr(node.get('condition', '')))
        if tag == 'ExternalLock':
            key = self._lock_key(name, task, node, 'SemaphoreName', variables)
            locked = self.locks[key] if key in self.locks else self.assume('behavior.external_lock.unset') == 'locked'
            return locked == (self.assume('behavior.external_lock.open_when') == 'locked')
        if tag == 'Synchronize':
            if frame.get('released'): return True
            if self.assume('behavior.synchronize') != 'opens_at_count': raise Unsupported('Unknown Synchronize policy')
            key = self._lock_key(name, task, node, 'SemaphoreName', variables)
            waiting = self.sync.setdefault(key, [])
            if [name, frame['path']] not in waiting: waiting.append([name, frame['path']])
            if len(waiting) < self._count(node, expr): return False
            for other, path in waiting:
                for f in self.tasks[other]['frames']:
                    if f['path'] == path: f['released'] = True
                if self.tasks[other]['status'] == 'gate': self.tasks[other]['status'] = 'running'
            del self.sync[key]
            self.record('behavior_synchronized', key=key, tasks=[w[0] for w in waiting])
            return True
        if tag == 'Semaphore': return self._acquire(name, task, frame, node, variables, expr)
        raise Unsupported('Unknown lab gate: ' + tag)

    def _acquire(self, name, task, frame, node, variables, expr):
        if frame.get('holding'): return True
        if self.assume('behavior.semaphore') != 'counted_holders': raise Unsupported('Unknown semaphore policy')
        key = self._lock_key(name, task, node, 'SemaphoreName', variables)
        held = self.semaphores.setdefault(key, [])
        if len(held) >= self._count(node, expr):
            if not held: del self.semaphores[key]
            return False
        held.append(name + '|' + frame['path'])
        frame['holding'] = key
        return True

    def _engine_step(self, name, task, frame, node, variables, expr, finish):
        tag, path = node.tag, frame['path']
        problems = self._schema(node)
        if problems: raise Unsupported(problems[0] + ': ' + path)
        if tag in GATES:
            if self.assume('behavior.gate.run_logic') != 'halt_restarts': raise Unsupported('Unknown gate policy')
            if 'child_result' in frame:
                self._release(name, frame, node)
                frame.pop('gate', None)
                finish(frame.pop('child_result')); return
            if tag in ENGINE_GATES:
                if self.assume('behavior.gate.engine_state') != 'scenario': raise Unsupported('Unknown engine gate policy')
                if not frame.get('engine_open'):
                    self._boundary(name, task, 'gate', path, node); return
            elif not self._lab_gate(name, task, frame, node, variables, expr):
                frame['gate'] = 'closed'; task['status'] = 'gate'; return
            frame['gate'] = 'open'
            self.record('behavior_gate', task=name, node=path, operation=tag, state='open')
            self._push(task, frame, 0)
        elif tag in ENGINE_ACTIONS:
            self._boundary(name, task, 'action', path, node)
        elif tag == 'AtomicDecorator':
            if self.assume('behavior.atomic') != 'not_interrupted': raise Unsupported('Unknown atomic policy')
            if 'child_result' in frame: finish(frame.pop('child_result'))
            else: self._push(task, frame, 0)
        elif tag == 'InstantSemaphore':
            if 'child_result' in frame:
                self._release(name, frame, node)
                finish(frame.pop('child_result'))
            elif self._acquire(name, task, frame, node, variables, expr): self._push(task, frame, 0)
            else: finish(False)
        elif tag == 'FuseBox':
            if self.assume('behavior.fusebox') != 'cleanup_by_result': raise Unsupported('Unknown FuseBox policy')
            index = {c.tag: i for i, c in enumerate(node)}
            if 'phase' not in frame:
                frame['phase'] = 'child'
                self._push(task, frame, index['Child']); return
            result = frame.pop('child_result')
            cleanup = None
            if frame['phase'] == 'child':
                frame['result'] = result
                branch = 'OnSuccess' if result else 'OnFail'
                if branch in index:
                    frame['phase'] = 'cleanup'
                    self._push(task, frame, index[branch]); return
            else: cleanup = result
            mode = node.get('StatusPropagation')
            frame.pop('phase')
            finish(frame['result'] if mode == 'Child' or (mode == 'CleanUp' and cleanup is None)
                   else True if mode == 'Success' else cleanup)
        elif tag == 'For': self._for(name, task, frame, node, variables, expr, finish)
        elif tag == 'LoopUntil':
            if self.assume('behavior.loop_until') != 'reached_succeeds_exhausted_fails':
                raise Unsupported('Unknown LoopUntil policy')
            limit = expr(node.get('attemptCount', ''))
            if type(limit) is not int or limit < -1: raise Unsupported('LoopUntil attempt count must be an integer: ' + path)
            if 'child_result' in frame:
                if frame.pop('child_result') == (node.get('until') == 'Success'): finish(True); return
                frame['attempts'] = frame.get('attempts', 0) + 1
                if limit > 0 and frame['attempts'] >= limit: finish(False); return
            self._push(task, frame, 0)
        elif tag == 'SendMessageToNPC':
            typ, content = self._message(node, path, expr)
            self.graph.queue_message(self.name + ':' + path, typ, expr(node.get('target', '')), content)
            self._boundary(name, task, 'message', path, node, message=self.graph.message_serial)
        elif tag == 'AreaPresenceListener':
            if self.assume('behavior.area_listener') != 'keeps_listening': raise Unsupported('Unknown listener policy')
            frame.pop('child_result', None)
            event = frame.pop('event', None)
            if event and node.get('trackIn' if event == 'in' else 'trackOut') == 'true':
                self.record('behavior_presence', task=name, node=path, event=event)
                self._push(task, frame, 0)
            else: self._boundary(name, task, 'listener', path, node)
        elif tag == 'GraphSearch':
            self._boundary(name, task, 'query', path, node, writes=outputs(node))
        elif tag == 'LuaGate':
            if 'child_result' in frame:
                frame.pop('lua_result', None)
                finish(frame.pop('child_result')); return
            if 'lua_result' not in frame:
                self._boundary(name, task, 'lua', path, node); return
            branch = 'Then' if frame['lua_result'] else 'Else'
            index = next((i for i, c in enumerate(node) if c.tag == branch), None)
            self.record('behavior_lua_gate', task=name, node=path, result=frame['lua_result'])
            if index is None:
                frame.pop('lua_result'); finish(True)
            else: self._push(task, frame, index)
        elif tag in FILTERS:
            raise Unsupported('A search filter outside a GraphSearch: ' + path)
        else: self._effect_step(name, task, frame, node, variables, expr, finish)

    def _for(self, name, task, frame, node, variables, expr, finish):
        path = frame['path']
        collection = expr(node.get('array', ''))
        if not isinstance(collection, (list, dict)): raise Unsupported('For needs an array: ' + path)
        if 'keys' not in frame:
            start, end, step = (expr(node.get(a, '')) for a in ('startIndex', 'endIndex', 'step'))
            if any(type(v) is not int for v in (start, end, step)) or step not in (1, -1):
                raise Unsupported('For needs integer bounds and a step of 1 or -1: ' + path)
            if isinstance(collection, dict):
                if (start, end, step) != (0, -1, 1): raise Unsupported('For over a map needs the default bounds: ' + path)
                frame['keys'] = list(collection)
            else:
                size = len(collection)
                if end != -1 and self.assume('behavior.for.end_index') != 'inclusive':
                    raise Unsupported('Unknown For bound policy')
                first = start if start != -1 else size - 1
                last = end if end != -1 else (size - 1 if step == 1 else 0)
                frame['keys'] = [i for i in range(first, last + step, step) if 0 <= i < size]
            frame['at'] = 0
        else:
            if not frame.pop('child_result'):
                if self.assume('behavior.loop.body_failure') != 'fails': raise Unsupported('Unknown loop failure policy')
                finish(False); return
            stop = node.get('break', '')
            if stop and boolean(expr(stop)): finish(True); return
            frame['at'] += 1
        if frame['at'] >= len(frame['keys']): finish(True); return
        key = frame['keys'][frame['at']]
        try: item = collection[key]
        except (KeyError, IndexError): finish(True); return
        for attribute, value in (('iterator', key), ('value', item)):
            target = node.get(attribute, '').removeprefix('$')
            if not target: continue
            if not IDENTIFIER.fullmatch(target): raise Unsupported('For writes a plain variable: ' + path)
            variables[target] = copy.deepcopy(value)
        self._push(task, frame, 0)

    def _effect_step(self, name, task, frame, node, variables, expr, finish):
        tag, path = node.tag, frame['path']

        def soul():
            return expr(node.get('SoulWUID') or '$this.id')

        def write(attribute, value):
            target = node.get(attribute, '').removeprefix('$')
            if not IDENTIFIER.fullmatch(target): raise Unsupported(tag + ' writes a plain variable: ' + path)
            variables[target] = value
        if tag == 'AddBuff':
            who, buff = soul(), self._text(node.get('BuffGUID', ''), variables, 'Buff')
            self.buffs.setdefault(str(who), []).append(buff)
            self._effect(name, path, 'add_buff', soul=who, buff=buff)
        elif tag == 'RemoveBuffs':
            if node.get('BuffTagId', '-1') != '-1': raise Unsupported('RemoveBuffs by tag is not modelled: ' + path)
            who, buff = soul(), self._text(node.get('BuffGUID', ''), variables, 'Buff')
            left = [b for b in self.buffs.get(str(who), []) if b != buff]
            if left: self.buffs[str(who)] = left
            else: self.buffs.pop(str(who), None)
            self._effect(name, path, 'remove_buffs', soul=who, buff=buff)
        elif tag == 'GameOver':
            self._effect(name, path, 'game_over', reason=node.get('Reason'))
        elif tag in ('AddLink', 'RemoveLink'):
            link = [expr(node.get('From', '')), expr(node.get('To', '')), self._text(node.get('Tag', ''), variables, 'Link tag')]
            if tag == 'AddLink':
                data = copy.deepcopy(expr(node.get('Data'))) if node.get('Data') else None
                self.links.append(link + [data])
                self._effect(name, path, 'add_link', link=link, data=data)
            else:
                self.links = [l for l in self.links if l[:3] != link]
                self._effect(name, path, 'remove_link', link=link)
        elif tag == 'GetSpatialInfo':
            write('Out', dict(spatial=node.get('What'), of=expr(node.get('In', ''))))
        elif tag == 'SetSpatialInfo':
            self._effect(name, path, 'set_spatial', entity=expr(node.get('In', '')), what=node.get('What'),
                         value=copy.deepcopy(expr(node.get('Val', ''))))
        elif tag == 'GetTime':
            write('OutVar', self.graph.now + (duration(node.get('Delta')) if node.get('Delta') else 0))
        elif tag == 'SetExternalLock':
            locked = literal(node.get('Locked', ''))
            if type(locked) is not bool: raise Unsupported('SetExternalLock needs a literal Locked: ' + path)
            key = self._lock_key(name, task, node, 'LockName', variables)
            self.locks[key] = locked
            self._effect(name, path, 'set_lock', lock=key, locked=locked)
        elif tag == 'ExecuteLua':
            declared = self.lua[node.get('code', '')]
            changes = {}
            for target, value in declared.get('assign', {}).items():
                changes.update(assignments(target + ' = ' + repr(value), variables, self.graph.source.enum_value))
            self._effect(name, path, 'lua', cluster=declared['cluster'], changes=changes)
        elif tag == 'InstantMultiSendMessageToNPC':
            targets = expr(node.get('targets', ''))
            if not isinstance(targets, list): raise Unsupported('Multi-send needs an array of targets: ' + path)
            typ, content = self._message(node, path, expr)
            for target in targets: self.graph.queue_message(self.name + ':' + path, typ, target, content)
        else: raise Unsupported('Unsupported behavior operation: ' + tag + ' at ' + path)
        finish()

    # -- state

    def _engine_state(self):
        return dict(locks=self.locks, semaphores=self.semaphores, sync=self.sync, effects=self.effects,
                    buffs=self.buffs, links=self.links)

    def state_key(self):
        """The interpreter state without what differs between two paths to it: clock, serials, the effect ledger."""
        now = self.graph.now
        # Branches of a Parallel that is over stay in `tasks` for the report; they are not state.
        live = {child for t in self.tasks.values() for f in t['frames'] for child in f.get('parallel_children', [])}
        tasks = copy.deepcopy({n: t for n, t in self.tasks.items() if 'parallel_parent' not in t or n in live})
        for task in tasks.values():
            for frame in task['frames']:
                if frame.get('deadline') is not None: frame['deadline'] -= now
                if frame.get('loop_count') == -1: frame['iterations'] = 0      # an endless loop does not count
                frame.pop('stamp', None)
            task.pop('blocks', None)
        text = json.dumps([tasks, self.variables, self.availability, self.inboxes, self.locks, self.semaphores,
                           self.sync, self.buffs, self.links], sort_keys=True, default=str)
        for index, name in sorted(enumerate(tasks), key=lambda item: -len(item[1])):
            text = text.replace(json.dumps(name)[1:-1], '#%d' % index)
        return re.sub(r'call:\d+', 'call', text)
