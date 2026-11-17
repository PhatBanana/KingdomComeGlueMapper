"""Resumable interpreter for a bounded subset of emitted XGen behavior XML.

This executes controller logic and availability changes. It does not approximate
KCD2's scheduler arbitration, navmesh, animation or perception. Those boundaries
must be supplied as explicit scenario outcomes.
"""
import copy
import hashlib
import json
import re
import xml.etree.ElementTree as E

from . import Unsupported
from .expressions import assignments, boolean, duration, evaluate, literal, parts
from .variables import initialize
from .patterns import concatenate
from .engine_nodes import BRANCHES, ENGINE_ACTIONS, ENGINE_NODES, EngineNodes


WRAPPERS = {'Sequence', 'Then', 'Else', 'Behavior', 'OnInit', 'Child', 'DefaultBranch'} | BRANCHES
SUPPORTED = WRAPPERS | ENGINE_NODES | {'Root', 'Success', 'Fail', 'Expression', 'IfCondition',
    'IfElseCondition', 'Switch', 'Selector', 'While', 'Wait', 'ProcessMessage',
    'SmartObjSetBehaviorState', 'Callback_empty', 'GameContextCheck', 'IncludeTree', 'Parallel', 'Loop',
    'InstantSendMessageToNPC', 'SuppressFailure', 'Invertor', 'VarOperation', 'Concatenation'}


class Behavior(EngineNodes):
    def __init__(self, name, blob, graph, variables=None, contracts=None, callbacks=None, lua=None):
        self.name, self.graph = name, graph
        self.contracts, self.callbacks = copy.deepcopy(contracts or {}), dict(callbacks or {})
        self.fingerprint = hashlib.sha256(b'concatenation-v1\0' + blob + json.dumps([self.contracts, self.callbacks] + ([lua] if lua else []), sort_keys=True).encode()).hexdigest()
        self.root = E.fromstring(blob)
        self.nodes, self.trees = {}, {}
        self.declarations = {}
        self.variables = copy.deepcopy(variables or {})
        self.availability, self.tasks, self.inboxes = {}, {}, {}
        self._init_engine(lua)
        self.unsupported, self.visited = [], set()
        self.serial = 0
        trees = [self.root] if self.root.tag == 'BehaviorTree' else self.root.findall('BehaviorTree')
        if not trees: raise ValueError('No behavior trees: ' + name)
        for tree in trees:
            key = tree.get('name')
            if not key or key in self.trees: raise ValueError('Duplicate or missing behavior tree name')
            root = tree.find('Root')
            if root is None: raise ValueError('Behavior tree has no Root: ' + key)
            self.trees[key] = key
            if len(tree.findall('Variables')) > 1: raise ValueError('Duplicate variable declarations: '+key)
            self.declarations[key] = list(tree.findall('./Variables/*'))
            self._index(root, key)
        self._resolve_includes()
        enum_files = {p:self.graph.source.hashes[p] for declarations in self.graph.source.enums.values()
                      for p,_,_ in declarations}
        enum_files.update({p:self.graph.source.hashes[p] for declarations in self.graph.source.types.values()
                           for p,_,_ in declarations})
        self.fingerprint = hashlib.sha256((self.fingerprint+json.dumps(enum_files,sort_keys=True)).encode()).hexdigest()
        for tag, contract in self.contracts.items():
            if (tag in SUPPORTED and tag not in ENGINE_ACTIONS) or tag.startswith('SendAIConceptSignal_'):
                raise ValueError('Cannot stub interpreted behavior: ' + tag)
            if not contract.get('reason'): raise ValueError('Behavior contract requires a reason')

    def _resolve_includes(self):
        """Index reachable static helper calls without executing or flattening them."""
        from pathlib import PurePosixPath
        self.includes, self.include_errors = {}, {}
        used, checked = {}, set()
        while True:
            pending = [(p,n) for p,n in self.nodes.items() if n.tag == 'IncludeTree' and p not in checked]
            if not pending: break
            for path, node in pending:
                checked.add(path)
                try:
                    if len(node) or set(node.attrib) - {'File','Name','nodeLabel'}:
                        raise Unsupported('IncludeTree needs a static file/tree and no child overrides')
                    file, name = literal(node.get('File','')), literal(node.get('Name',''))
                    if not all(isinstance(v,str) and v and '$' not in v for v in (file,name)):
                        raise Unsupported('Dynamic behavior include needs runtime dispatch')
                    file = file.replace('\\','/').lower()
                    if PurePosixPath(file).is_absolute() or '..' in file.split('/') or ':' in file:
                        raise Unsupported('Invalid behavior include path')
                    # Production fragments use AI/, installed packages Libs/AI/.
                    relative = file.removeprefix('libs/ai/').removeprefix('ai/')
                    matches = [p for p in (file, 'ai/'+relative, 'libs/ai/'+relative)
                               if p in self.graph.source.files]
                    matches = sorted(set(matches))
                    if len(matches) != 1:
                        raise Unsupported('Missing/ambiguous behavior include: '+file)
                    file = matches[0]
                    document = self.graph.source.files[file]
                    trees = [] if document is None else ([document] if document.tag == 'BehaviorTree'
                                                         else document.findall('BehaviorTree'))
                    trees = [t for t in trees if t.get('name') == name]
                    if len(trees) != 1 or len(trees[0].findall('Root')) != 1:
                        raise Unsupported('Missing/ambiguous included tree: '+file+':'+name)
                    if len(trees[0].findall('Variables')) > 1:
                        raise Unsupported('Duplicate included variable declarations')
                    declarations=list(trees[0].findall('./Variables/*'))
                    initialize(declarations,{},self.graph.source.enum_value,self.graph.source)
                    target = '@include:'+file+':'+name
                    self.declarations[target] = declarations
                    self.includes[path] = target
                    used[file] = self.graph.source.hashes[file]
                    if target not in self.nodes: self._index(trees[0].find('Root'), target)
                except Unsupported as error:
                    self.include_errors[path] = str(error)
                    self.unsupported.append(dict(node=path, reason=str(error)))
        self.fingerprint = hashlib.sha256((self.fingerprint + json.dumps(used, sort_keys=True)).encode()).hexdigest()

    def _index(self, node, path):
        self.nodes[path] = node
        signal = node.tag.startswith('SendAIConceptSignal_') and len(node.tag) > len('SendAIConceptSignal_')
        if signal and (len(node) or node.attrib):
            self.unsupported.append(dict(node=path, reason='AI concept signal must be an argument-free leaf'))
        if node.tag not in SUPPORTED and node.tag not in self.contracts and not signal:
            self.unsupported.append(dict(node=path, reason='Unsupported behavior: ' + node.tag))
        if node.tag in self.contracts and len(node):
            self.unsupported.append(dict(node=path, reason='Engine contract cannot replace a subtree'))
        for reason in self._schema(node): self.unsupported.append(dict(node=path, reason=reason))
        if node.tag == 'Wait' and node.get('skipInLOD', 'false') != 'false':
            self.unsupported.append(dict(node=path, reason='Native LOD-dependent wait skipping is not emulated'))
        if node.tag == 'Concatenation' and (len(node) or set(node.attrib) != {'OutString','Pattern'}):
            self.unsupported.append(dict(node=path, reason='Concatenation requires an output, pattern and no children'))
        if node.tag == 'Parallel' and not self._parallel_schema(node):
            self.unsupported.append(dict(node=path, reason='Parallel requires nonempty branches and explicit All/Any policies'))
        if node.tag == 'Loop' and (set(node.attrib) != {'count'} or len(node) != 1):
            self.unsupported.append(dict(node=path, reason='Loop requires an explicit count and exactly one body'))
        if node.tag in ('SuppressFailure','Invertor') and (node.attrib or len(node) != 1):
            self.unsupported.append(dict(node=path, reason='Result decorator requires exactly one child and no attributes'))
        if node.tag == 'VarOperation' and (len(node) or
                set(node.attrib)-{'varName','targetVarName','operation','argument'} or
                node.get('operation') not in ('Size','PushBack')):
            self.unsupported.append(dict(node=path,reason='Unsupported collection operation: '+node.get('operation','')))
        if node.tag == 'InstantSendMessageToNPC' and (len(node) or set(node.attrib) - {'target','type','variable','values'}):
            self.unsupported.append(dict(node=path, reason='Immediate NPC message requires a leaf and known payload fields'))
        if node.tag == 'GameContextCheck' and not self._context_check_schema(node):
            self.unsupported.append(dict(node=path, reason='GameContextCheck requires explicit Then/Else branches and version 2'))
        for index, child in enumerate(node): self._index(child, path + '/' + str(index))

    def record(self, kind, **values):
        self.graph.record(kind, controller=self.name, **values)

    def _unset_members(self):
        declared = 'behavior.record.unset_member' in self.graph.world.assumptions
        return declared and self.assume('behavior.record.unset_member') == 'assignable'

    def _context_check_schema(self, node):
        """Both branches, or one of them when the scenario declares what a missing branch returns."""
        branches = sorted(c.tag for c in node)
        one = branches in (['Then'], ['Else']) and 'behavior.context_check.missing_branch' in self.graph.world.assumptions
        return (set(node.attrib) == {'context', 'saveVersion'} and node.get('saveVersion') == '2'
                and (branches == ['Else', 'Then'] or one))

    @staticmethod
    def _parallel_schema(node):
        return (len(node) > 0 and set(node.attrib) == {'successMode', 'failureMode'}
                and all(node.get(k) in ('All','Any') for k in ('successMode','failureMode')))

    def start(self, tree, task=None):
        if tree not in self.trees: raise ValueError('Unknown behavior tree: ' + tree)
        self.serial += 1
        task = task or tree + ':' + str(self.serial)
        if task in self.tasks: raise ValueError('Duplicate task: ' + task)
        local = initialize(self.declarations[tree], self.variables, self.graph.source.enum_value, self.graph.source,
                           unset=self._unset_members())
        self.tasks[task] = dict(frames=[dict(path=self.trees[tree], index=0)], status='running',
                               scope=task, locals=local, tree=tree,
                               declared=[n.get('name') for n in self.declarations[tree]])
        self.record('behavior_start', task=task, tree=tree)
        self.pump()
        return task

    def set_variables(self, values):
        self.variables.update(copy.deepcopy(values))
        self.record('behavior_inputs', values=values)

    def message(self, inbox, value, sender):
        self.inboxes.setdefault(inbox, []).append(dict(value=copy.deepcopy(value), sender=copy.deepcopy(sender)))
        self.record('message', inbox=inbox, value=value, sender=sender)
        self.pump()

    def resolve(self, task_name, outcome, values=None):
        task = self.tasks[task_name]
        if task['status'] == 'external' and 'boundary' in task:
            self._resolve_boundary(task_name, task, outcome, values)
            self.pump()
            return
        if task['status'] != 'external' or outcome not in ('success', 'fail') or values:
            raise ValueError('Outcome requires an outstanding external task and success/fail')
        self.record('behavior_outcome', task=task_name, node=task['frames'][-1]['path'], outcome=outcome)
        task['status'] = 'running'
        self._finish(task_name, outcome == 'success')
        self.pump()

    def _finish(self, name, result):
        task = self.tasks[name]
        frame = task['frames'].pop()
        if frame.get('call_scope') and frame['path'] in self.declarations:
            self.tasks[task.get('scope',name)].get('call_scopes',{}).pop(frame['call_scope'],None)
        self.record('behavior_return', task=name, node=frame['path'], result=result)
        if task['frames']: task['frames'][-1]['child_result'] = result
        else:
            task['status'] = 'success' if result else 'fail'
            parent = task.get('parallel_parent')
            if parent is not None and self.tasks[parent]['status'] == 'parallel':
                self.tasks[parent]['status'] = 'running'

    def _cancel(self, name):
        task = self.tasks[name]
        if task['status'] in ('success','fail','canceled'): return
        self._unwind(name, 0)
        self.record('behavior_cancel', task=name, previous_status=task['status'])
        task['frames'] = []
        task['status'] = 'canceled'

    def _push(self, task, frame, index):
        task['frames'].append(dict(path=frame['path'] + '/' + str(index), index=0,
                                   call_scope=frame.get('call_scope')))

    def _environment(self, name, frame):
        """(variables, expr) as the node of `frame` sees them: globals, then the task's and its calls' locals."""
        task = self.tasks[name]
        owner = self.tasks[task.get('scope',name)]
        calls=owner.setdefault('call_scopes',{})
        chain=[]; scope=frame.get('call_scope')
        while scope is not None:
            current=calls[scope];chain.append(current);scope=current['parent']
        bindings=dict(self.variables); destinations={}
        for current in [owner]+list(reversed(chain)):
            for key in current.get('declared',[]):
                bindings.pop(key,None)
                destinations[key]=current['locals']
            bindings.update(current.get('locals',{}))
        class Environment(dict):
            def __setitem__(env, key, value):
                destinations.get(key,self.variables)[key]=value
                super().__setitem__(key,value)
        variables = Environment(bindings)
        def expr(text): return evaluate(text, variables, self.graph.source.enum_value)
        return variables, expr

    def _step(self, name):
        task = self.tasks[name]
        frame = task['frames'][-1]
        path = frame['path']; node = self.nodes[path]; tag = node.tag
        owner = self.tasks[task.get('scope',name)]
        calls=owner.setdefault('call_scopes',{})
        variables, expr = self._environment(name, frame)
        self.visited.add(path)
        self.graph.tick()
        def finish(result=True): self._finish(name, result)
        if tag.startswith('SendAIConceptSignal_'):
            if len(node) or node.attrib:
                raise Unsupported('AI concept signal must be an argument-free leaf: ' + path)
            self.record('behavior_signal', task=name, node=path, notification=tag.removeprefix('SendAIConceptSignal_'))
            self.graph.signal(tag.removeprefix('SendAIConceptSignal_')); finish()
        elif tag == 'IncludeTree':
            if path in self.include_errors: raise Unsupported(self.include_errors[path])
            if 'child_result' in frame: finish(frame.pop('child_result')); return
            target = self.includes[path]
            self.serial += 1
            scope = 'call:'+str(self.serial)
            declarations=self.declarations[target]
            calls[scope]=dict(parent=frame.get('call_scope'),
                declared=[n.get('name') for n in declarations],
                locals=initialize(declarations,{},self.graph.source.enum_value,self.graph.source,
                                  unset=self._unset_members()))
            self.record('behavior_include', task=name, node=path, target=target)
            task['frames'].append(dict(path=target,index=0,call_scope=scope))
        elif tag == 'InstantSendMessageToNPC':
            if len(node) or set(node.attrib) - {'target','type','variable','values'}:
                raise Unsupported('Unsupported immediate NPC message schema: '+path)
            # The type is a quoted name in emitted trees and a bare one in older fixtures.
            typ, content = self._message(node, path, expr)
            self.graph.queue_message(self.name+':'+path, typ, expr(node.get('target','')), content)
            finish()
        elif tag in ENGINE_NODES and tag not in self.contracts:
            self._engine_step(name, task, frame, node, variables, expr, finish)
        elif tag in self.contracts:
            if len(node): raise Unsupported('Engine contract cannot replace a subtree: ' + path)
            task['status'] = 'external'
            self.record('behavior_request', task=name, node=path, operation=tag, attributes=dict(node.attrib))
        elif tag == 'Parallel':
            if not self._parallel_schema(node): raise Unsupported('Unsupported parallel schema: '+path)
            if 'parallel_children' not in frame:
                frame['parallel_children'] = []
                for index in range(len(node)):
                    self.serial += 1
                    child = name + ':parallel:' + str(self.serial)
                    if child in self.tasks: raise ValueError('Duplicate parallel task: '+child)
                    self.tasks[child] = dict(frames=[dict(path=path+'/'+str(index), index=0,call_scope=frame.get('call_scope'))],
                                            status='running', parallel_parent=name, scope=task.get('scope',name))
                    frame['parallel_children'].append(child)
                self.record('behavior_parallel', task=name, node=path, children=frame['parallel_children'][:])
            children = frame['parallel_children']
            statuses = [self.tasks[c]['status'] for c in children]
            for result, attr in (('fail','failureMode'), ('success','successMode')):
                count = statuses.count(result)
                if count and (node.get(attr) == 'Any' or count == len(children)):
                    for child in children: self._cancel(child)
                    finish(result == 'success'); return
            if all(s in ('success','fail') for s in statuses):
                raise Unsupported('Parallel ended with mixed results satisfying neither policy: '+path)
            task['status'] = 'parallel'
        elif tag in WRAPPERS or tag == 'Root':
            if tag == 'Root' and any(c.tag not in ('OnInit', 'Behavior') for c in node):
                raise Unsupported('Root exit handlers need an unwind adapter: ' + path)
            if frame.pop('child_result', True) is False: finish(False); return
            index = frame['index']
            if index == len(node): finish(); return
            frame['index'] += 1
            if tag == 'Root':
                # OnInit is a lifecycle hook, not an XML-order behavior child.
                order = [i for i,c in enumerate(node) if c.tag == 'OnInit']
                order.extend(i for i,c in enumerate(node) if c.tag == 'Behavior')
                index = order[index]
            self._push(task, frame, index)
        elif tag in ('SuppressFailure','Invertor'):
            if node.attrib or len(node) != 1:
                raise Unsupported('Unsupported result decorator schema: '+path)
            if 'child_result' not in frame:
                self._push(task,frame,0); return
            result = frame.pop('child_result')
            finish(True if tag == 'SuppressFailure' else not result)
        elif tag in ('Success', 'Fail'): finish(tag == 'Success')
        elif tag == 'Expression':
            changes = assignments(node.get('expressions', ''), variables, self.graph.source.enum_value)
            self.record('assignment', task=name, node=path, changes=changes); finish()
        elif tag == 'Concatenation':
            if len(node) or set(node.attrib) != {'OutString','Pattern'}:
                raise Unsupported('Unsupported Concatenation schema: '+path)
            value = concatenate(node.get('Pattern'), variables)
            changes = assignments(node.get('OutString')+' = '+repr(value), variables, self.graph.source.enum_value)
            self.record('assignment', task=name, node=path, changes=changes); finish()
        elif tag == 'VarOperation':
            if len(node) or set(node.attrib)-{'varName','targetVarName','operation','argument'}:
                raise Unsupported('Unsupported collection operation schema: '+path)
            operation=node.get('operation','')
            if operation not in ('Size','PushBack'):
                raise Unsupported('Unsupported collection operation: '+operation)
            collection=expr(node.get('varName',''))
            target=node.get('targetVarName','')
            if operation=='Size':
                if not isinstance(collection,(list,dict)) or not target or node.get('argument',''):
                    raise Unsupported('Size requires a collection, output and no argument')
                assignments(target+' = '+str(len(collection)),variables,self.graph.source.enum_value)
            else:
                if not isinstance(collection,list) or target or not node.get('argument',''):
                    raise Unsupported('PushBack requires an array, argument and no output')
                collection.append(copy.deepcopy(expr(node.get('argument'))))
            self.record('behavior_collection',task=name,operation=operation,
                        variable=node.get('varName'),size=len(collection)); finish()
        elif tag == 'SmartObjSetBehaviorState':
            behavior = expr(node.get('behaviors', ''))
            state = node.get('state')
            if not isinstance(behavior, str) or state not in ('Enabled','Disabled','NoRequests'):
                raise Unsupported('Unknown behavior availability: ' + path)
            self.availability[behavior] = state
            self.record('availability', task=name, behavior=behavior, state=state); finish()
        elif tag == 'GameContextCheck':
            if not self._context_check_schema(node):
                raise Unsupported('Unsupported game-context branch schema: ' + path)
            if 'child_result' in frame: finish(frame.pop('child_result')); return
            result = self.graph.game_context(node.get('context'))
            branch = 'Then' if result else 'Else'
            self.record('game_context_check', task=name, node=path, context=node.get('context'), result=result)
            index = next((i for i,c in enumerate(node) if c.tag == branch), None)
            if index is None:
                finish(self.assume('behavior.context_check.missing_branch') == 'succeeds'); return
            self._push(task, frame, index)
        elif tag in ('IfCondition', 'IfElseCondition'):
            if 'child_result' in frame: finish(frame.pop('child_result')); return
            result = boolean(expr(node.get('condition', '')))
            self.record('behavior_condition', task=name, node=path, expression=node.get('condition'), result=result)
            if tag == 'IfCondition' and not result:
                flag = node.get('failOnCondition')
                if flag not in ('true','false'): raise Unsupported('Unknown failOnCondition: ' + path)
                finish(flag != 'true'); return
            index = 0 if result else 1
            if index >= len(node): raise Unsupported('Missing conditional branch: ' + path)
            self._push(task, frame, index)
        elif tag == 'Selector':
            if frame.pop('child_result', False): finish(); return
            index = frame['index']
            if index == len(node): finish(False); return
            frame['index'] += 1; self._push(task, frame, index)
        elif tag == 'Switch':
            if 'child_result' in frame: finish(frame.pop('child_result')); return
            for index, child in enumerate(node):
                if child.tag == 'DefaultBranch' or (child.tag == 'IfCondition' and boolean(expr(child.get('condition','')))):
                    self._push(task, frame, index); return
                if child.tag != 'IfCondition': raise Unsupported('Unsupported Switch branch: ' + child.tag)
            finish()
        elif tag == 'Loop':
            if set(node.attrib) != {'count'} or len(node) != 1:
                raise Unsupported('Loop requires an explicit count and exactly one body: '+path)
            if 'loop_count' not in frame:
                count = expr(node.get('count', ''))
                if type(count) is not int or count == 0 or count < -1:
                    raise Unsupported('Loop count must be a positive integer or -1: '+path)
                frame['loop_count'], frame['iterations'] = count, 0
                frame['stamp'] = task.get('blocks', 0)
            if 'child_result' in frame:
                if not frame.pop('child_result'):
                    if 'behavior.loop.body_failure' not in self.graph.world.assumptions:
                        raise Unsupported('Loop body failure policy needs native verification: '+path)
                    if self.assume('behavior.loop.body_failure') != 'fails': raise Unsupported('Unknown loop failure policy')
                    finish(False); return
                frame['iterations'] += 1
                if (frame['loop_count'] == -1 and frame['stamp'] == task.get('blocks', 0)
                        and 'behavior.loop.instant_body' in self.graph.world.assumptions):
                    # The body of an endless loop came back without waiting for anything. The engine
                    # runs it again on its next update; the lab stops here until the scenario ticks.
                    # Without the declared assumption the loop spins into the operation budget, as before.
                    if self.assume('behavior.loop.instant_body') != 'next_tick': raise Unsupported('Unknown loop policy')
                    frame['stamp'] = task.get('blocks', 0) + 1       # pump counts this stop as a wait
                    self.record('behavior_tick_wait', task=name, node=path)
                    task['status'] = 'tick'; return
                frame['stamp'] = task.get('blocks', 0)
            if frame['iterations'] == frame['loop_count']:
                finish(); return
            self._push(task, frame, 0)
        elif tag == 'While':
            result = frame.pop('child_result', True)
            if not result and node.get('propagateChildFail') != 'false': finish(False); return
            if not boolean(expr(node.get('condition', ''))):
                if node.get('doFail') not in ('true','false'): raise Unsupported('Unknown While doFail')
                finish(node.get('doFail') == 'false'); return
            if len(node) != 1: raise Unsupported('While needs one child')
            self._push(task, frame, 0)
        elif tag == 'Wait':
            if literal(node.get('timeType','')) != 'GameTime' or node.get('variation',''):
                raise Unsupported('Wait requires GameTime and no variation: ' + path)
            if node.get('doFail') not in ('true','false'): raise Unsupported('Wait needs explicit doFail')
            if 'deadline' not in frame:
                text = str(literal(node.get('duration','')))
                frame['deadline'] = None if text == '-1' else self.graph.now + duration(text)
                self.record('behavior_wait', task=name, node=path, deadline_us=frame['deadline'])
            if frame['deadline'] is not None and frame['deadline'] <= self.graph.now:
                finish(node.get('doFail') == 'false')
            else: task['status'] = 'waiting'
        elif tag == 'ProcessMessage':
            if literal(node.get('timeout','')) not in (-1, '-1'):
                raise Unsupported('Only infinite mailbox waits are supported: ' + path)
            if 'message' not in frame:
                bindings = []
                for attr, key in (('variable','value'),('senderInfo','sender')):
                    variable = node.get(attr,'').removeprefix('$')
                    if not variable: continue
                    if not variable.isidentifier(): raise Unsupported('Invalid mailbox variable')
                    bindings.append((variable,key))
                inbox = expr(node.get('inbox',''))
                messages = self.inboxes.get(inbox, [])
                condition = node.get('condition','')
                selected = None
                for index, message in enumerate(messages):
                    # Candidate content is temporary filter context, never a
                    # published output or a mutation of controller variables.
                    context = dict(variables, __content=message['value'])
                    if not condition or boolean(evaluate(condition, context, self.graph.source.enum_value)):
                        selected = index; break
                if selected is None: task['status'] = 'message'; return
                frame['message'] = messages.pop(selected)
                for variable, key in bindings:
                    variables[variable] = frame['message'][key]
            if frame.pop('child_result', True) is False: finish(False); return
            index = frame['index']
            if index == len(node):
                answer = node.get('answerVar','').removeprefix('$')
                self.record('message_processed', task=name, answer=variables.get(answer)); finish(); return
            frame['index'] += 1; self._push(task, frame, index)
        elif tag == 'Callback_empty':
            event = literal(node.get('EventName',''))
            if event not in self.callbacks: raise Unsupported('Unbound behavior callback: ' + str(event))
            self.graph.fire(self.callbacks[event]); finish()
        else: raise Unsupported('Unsupported behavior operation: ' + tag + ' at ' + path)

    def pump(self):
        # Stable task creation order is the emulator policy. Native arbitration
        # and concurrent mailbox locking have not been replicated.
        for task in self.tasks.values():
            if task['status'] in ('waiting', 'message', 'gate'): task['status'] = 'running'
        progressed, woken = False, set()
        while True:
            self._recheck_gates()
            name = next((n for n,t in self.tasks.items() if t['status'] == 'running'), None)
            if name is None:
                # Something ran since the lab gates were last read (a lock was set, a variable
                # written): read them once more, and stop when that changes nothing.
                woken = {n for n,t in self.tasks.items() if t['status'] == 'gate'}
                if not progressed or not woken: break
                for n in woken: self.tasks[n]['status'] = 'running'
                progressed = False
                continue
            # Re-select after each step so a returned branch wakes its parent
            # before another branch can execute effects after cancellation.
            self._step(name)
            task = self.tasks.get(name)
            if task is not None and task['status'] not in ('running', 'success', 'fail', 'canceled'):
                task['blocks'] = task.get('blocks', 0) + 1
            if not (name in woken and task is not None and task['status'] == 'gate'): progressed = True
            woken.discard(name)

    def tick(self):
        """The next engine update: endless loops whose body returned at once run again."""
        waiting = [t for t in self.tasks.values() if t['status'] == 'tick']
        for task in waiting: task['status'] = 'running'
        self.record('behavior_tick', tasks=len(waiting))
        self.pump()

    def next_deadline(self):
        return min((t['frames'][-1]['deadline'] for t in self.tasks.values()
                    if t['status'] == 'waiting' and t['frames'][-1].get('deadline') is not None), default=None)

    def snapshot(self):
        return copy.deepcopy(dict(fingerprint=self.fingerprint, variables=self.variables,
            availability=self.availability, tasks=self.tasks, inboxes=self.inboxes, serial=self.serial,
            **self._engine_state()))

    def restore(self, data):
        if data.get('fingerprint') != self.fingerprint: raise ValueError('Behavior snapshot mismatch')
        for key in ('variables','availability','tasks','inboxes','serial'):
            setattr(self, key, copy.deepcopy(data[key]))
        for key in self._engine_state():
            setattr(self, key, copy.deepcopy(data.get(key, [] if key in ('effects', 'links') else {})))

    def report(self):
        return dict(fingerprint=self.fingerprint, variables=self.variables, availability=self.availability,
            tasks={k: v['status'] for k,v in self.tasks.items()}, visited=sorted(self.visited),
            effects=copy.deepcopy(self.effects), locks=dict(self.locks), buffs=copy.deepcopy(self.buffs),
            pending_boundaries=[dict(task=n, **b) for n, b in self.boundaries()],
            unvisited=sorted(set(self.nodes)-self.visited), unsupported=self.unsupported,
            scheduling_policy='Deterministic creation order with parent outcome propagation; native arbitration unverified',
            external_contracts=self.contracts)
