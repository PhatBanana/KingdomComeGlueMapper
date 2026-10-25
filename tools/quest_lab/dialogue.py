"""Bounded dialogue logic at explicit engine entry/selection/exit boundaries.

No actor interaction, speech playback or scene success is invented. Scenarios
supply those boundaries; this model checks gates, branches and declared effects.
"""
import ast
import copy
import re

from . import Unsupported
from .expressions import boolean, syntax


KINDS = {'ForcedDialog', 'FaderDialog', 'Dialog'}
INPUTS = {'EnqueueDialogue': 'trigger', 'PlayDialogue': 'trigger', 'DialogParams': 'native'}
OUTPUTS = {'BeforePlay', 'AfterPlay'}


def condition(text, ports, sequences):
    # Translate keywords outside strings; no script, lookup or arbitrary call.
    chunks = re.split(r"('(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", text or 'true')
    for i in range(0, len(chunks), 2):
        chunks[i] = re.sub(r'\bAND\b', 'and', re.sub(r'\bOR\b', 'or', chunks[i]))
    tree = syntax(''.join(chunks))

    def check(n):
        if isinstance(n, ast.Constant) and type(n.value) is bool: return
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not): return check(n.operand)
        if isinstance(n, ast.BoolOp) and isinstance(n.op, (ast.And, ast.Or)):
            for value in n.values: check(value)
            return
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords
                and len(n.args) == 1 and isinstance(n.args[0], ast.Constant) and type(n.args[0].value) is str):
            name = n.args[0].value
            if n.func.id == 'Port' and ports.get(name) == ('In', 'bool'): return
            if n.func.id == 'SequenceUsed' and name in sequences: return
        raise Unsupported('Unmodeled dialogue condition: ' + text)
    check(tree)
    return tree


def evaluate(tree, read_port, used):
    if isinstance(tree, ast.Constant): return tree.value
    if isinstance(tree, ast.Call):
        name = tree.args[0].value
        return boolean(read_port(name)) if tree.func.id == 'Port' else name in used
    if isinstance(tree, ast.UnaryOp): return not evaluate(tree.operand, read_port, used)
    values = (evaluate(v, read_port, used) for v in tree.values)
    return all(values) if isinstance(tree.op, ast.And) else any(values)


class Dialogue:
    def __init__(self, graph, name, scope, host):
        self.graph, self.name, self.scope = graph, name, scope
        self.ports = {p.get('Name'): (p.get('Direction'), p.get('Type')) for p in host.findall('Ports/*')}
        self.decisions, self.sequences, self.owners, self.conditions, self.errors = {}, {}, {}, {}, {}
        self.root = None
        self.state = dict(requests=[], active=False, decision=None, used=[], closing=False)
        body = host.find('Dialogue')
        if body is None: raise Unsupported('Missing dialogue body: ' + name)
        self.enabled = body.get('TechnicalStatus', 'Enabled') == 'Enabled'
        roots = body.findall('Decision')
        if len(roots) != 1: raise Unsupported('Dialogue requires one root decision: ' + name)
        self.root = roots[0].get('Name')
        if host.find('Nodes/*') is not None:
            graph.issue(name, 'Dialogue embedded graph is not modeled')
        for decision in body.iter('Decision'):
            identity = decision.get('Name')
            if not identity or identity in self.decisions: raise ValueError('Duplicate/missing dialogue decision')
            self.decisions[identity] = decision
            for seq in decision.findall('Sequences/Sequence'):
                identity = seq.get('Name')
                if not identity or identity in self.sequences: raise ValueError('Duplicate/missing dialogue sequence')
                self.sequences[identity] = seq
                self.owners[identity] = decision.get('Name')
        for identity, seq in self.sequences.items():
            try:
                self.conditions[identity] = condition(seq.get('EntryCondition', ''), self.ports, self.sequences)
                if seq.get('ExitScript', '').strip(): raise Unsupported('Dialogue exit script requires an execution adapter')
                allowed = {'Name', 'EntryCondition', 'EndType', 'GoToDecision', 'Visibility', 'ExitScript'}
                if set(seq.attrib) - allowed:
                    raise Unsupported('Unmodeled dialogue selection attributes: ' + ', '.join(sorted(set(seq.attrib) - allowed)))
                for trigger in seq.findall('Triggers/*'):
                    if trigger.tag != 'Port' or self.ports.get(trigger.get('Name')) != ('Out', 'trigger'):
                        raise Unsupported('Undeclared dialogue effect: ' + str(trigger.attrib))
                if any(c.tag not in {'Elements', 'DesignName', 'UiPrompt', 'Triggers', 'Decision'} for c in seq):
                    raise Unsupported('Unmodeled dialogue sequence children')
                for element in seq.findall('Elements/*'):
                    if element.tag != 'Response' or any(c.tag not in ('Text', 'Commands') for c in element):
                        raise Unsupported('Unmodeled dialogue element: ' + element.tag)
                    if any(c.tag not in ('CameraCommand', 'LookAtCommand') for c in element.findall('Commands/*')):
                        raise Unsupported('Dialogue command needs an engine adapter')
                end = seq.get('EndType', 'EndTopic')
                if end not in ('EndTopic', 'EndDialogue', 'GoTo', 'Decision'):
                    raise Unsupported('Unmodeled dialogue ending: ' + end)
                if end == 'GoTo' and seq.get('GoToDecision') not in self.decisions:
                    raise ValueError('Missing dialogue destination: ' + str(seq.get('GoToDecision')))
                if end == 'Decision' and len(seq.findall('Decision')) != 1:
                    raise ValueError('Missing/ambiguous child dialogue decision')
                # Returning from a nested topic needs the native conversation
                # stack; do not silently pick a parent or the root.
                if end == 'EndTopic' and self.owners[identity] != self.root:
                    raise Unsupported('Nested EndTopic requires conversation-stack support')
            except Unsupported as exc:
                self.errors[identity] = str(exc)
                graph.issue(name + ':' + identity, str(exc))

    def ref(self, port):
        return self.scope + '.' + port if self.scope else port

    def output(self, port):
        return (self.scope or 'output') + '.' + port

    def request(self, port):
        self.state['requests'].append(port)
        self.graph.record('dialogue_requested', dialogue=self.name, port=port)

    def start(self, request=False):
        if not self.enabled: raise Unsupported('Dialogue is not enabled: ' + self.name)
        if type(request) is not bool: raise ValueError('Dialogue request must be a boolean')
        if self.state['active']: raise ValueError('Dialogue is already active: ' + self.name)
        if request:
            if not self.state['requests']: raise ValueError('No pending dialogue request: ' + self.name)
            self.state['requests'].pop(0)
        self.state.update(active=True, decision=self.root, closing=False)
        self.graph.record('dialogue_started', dialogue=self.name, boundary='explicit_engine_outcome', request=request)
        self.graph.emit(self.output('BeforePlay')); self.graph.drain()

    def choices(self):
        if not self.state['active'] or self.state['closing']: return []
        result = []
        for seq in self.decisions[self.state['decision']].findall('Sequences/Sequence'):
            name = seq.get('Name')
            if name not in self.conditions: raise Unsupported(self.errors[name])
            if evaluate(self.conditions[name], lambda p: self.graph.value(self.ref(p)), self.state['used']): result.append(name)
        return result

    def choose(self, sequence):
        if sequence not in self.choices(): raise ValueError('Dialogue sequence is not available: ' + sequence)
        if sequence in self.errors: raise Unsupported(self.errors[sequence])
        seq = self.sequences[sequence]
        if sequence not in self.state['used']: self.state['used'].append(sequence)
        self.graph.record('dialogue_sequence_executed', dialogue=self.name, sequence=sequence,
                          boundary='explicit_engine_outcome', presentation='not simulated')
        for port in reversed(seq.findall('Triggers/Port')): self.graph.emit(self.output(port.get('Name')))
        self.graph.drain()
        end = seq.get('EndType', 'EndTopic')
        if end == 'EndDialogue': self.state['closing'] = True
        elif end == 'GoTo': self.state['decision'] = seq.get('GoToDecision')
        elif end == 'Decision': self.state['decision'] = seq.find('Decision').get('Name')

    def end(self):
        if not self.state['active']: raise ValueError('Dialogue is not active: ' + self.name)
        self.state.update(active=False, decision=None, closing=False)
        self.graph.record('dialogue_ended', dialogue=self.name, boundary='explicit_engine_outcome')
        self.graph.emit(self.output('AfterPlay')); self.graph.drain()

    def snapshot(self):
        return copy.deepcopy(self.state)
