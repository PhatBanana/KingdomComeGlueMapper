"""Explicit request/result boundary for native function calls, without effects.

The XML supplies the function identity and arguments. A scenario must describe
its interface and supply each result; no native engine function is executed.
"""
import copy
import math

from . import Unsupported


def signature(element):
    return dict(kind=element.tag, declaring_type=element.get('DeclaringType'), method=element.get('MethodName'))


def typed(value, typ):
    if typ == 'bool': valid = type(value) is bool
    elif typ == 'int': valid = type(value) is int
    elif typ == 'float': valid = type(value) in (int, float) and math.isfinite(value)
    elif typ == 'string': valid = isinstance(value, str)
    else: raise ValueError('Native result type is not modeled: ' + str(typ))
    if not valid: raise ValueError('Native result does not match type ' + typ)


class NativeCalls:
    def __init__(self, graph):
        self.graph = graph
        self.pending, self.serial = [], 0

    def validate(self, name, contract):
        node = self.graph.nodes[name]
        if any(not isinstance(v, str) or not v for v in signature(node['element']).values()):
            raise ValueError('Native call must have an explicit declaring type and method: ' + name)
        if contract.get('native') != signature(node['element']):
            raise ValueError('Native contract signature mismatch: ' + name)
        if contract.get('values'):
            raise ValueError('Native call results must be supplied after a request: ' + name)
        if contract.get('inputs', {}).get('Exec') != 'trigger' or any(
                typ != 'value' for p, typ in contract['inputs'].items() if p != 'Exec'):
            raise ValueError('Native call requires Exec trigger and value arguments: ' + name)
        if any(t not in ('trigger','bool','int','float','string') for t in contract.get('outputs', {}).values()):
            raise ValueError('Unsupported native contract output type: ' + name)

    def request(self, name):
        g = self.graph
        if name not in g.contracts:
            raise Unsupported('Native function needs an explicit interface contract: ' + name)
        args = g._args(name)
        expected = {p for p, typ in g.contracts[name]['inputs'].items() if typ == 'value'}
        if set(args) != expected:
            raise Unsupported('Native call arguments do not match contract: ' + name)
        self.serial += 1
        call = dict(id=self.serial, node=name, signature=signature(g.nodes[name]['element']), arguments=copy.deepcopy(args))
        self.pending.append(call)
        g.record('native_requested', **copy.deepcopy(call))

    def resolve(self, identity, node, result, values=None, events=None):
        g = self.graph
        if type(identity) is not int: raise ValueError('Native call id must be an integer')
        matches = [c for c in self.pending if c['id'] == identity and c['node'] == node]
        if len(matches) != 1: raise ValueError('Unknown or already resolved native call')
        values = {} if values is None else values
        events = [] if events is None else events
        if not isinstance(values, dict) or not isinstance(events, list) or any(not isinstance(e,str) for e in events):
            raise ValueError('Native results require a values object and event list')
        if len(set(events)) != len(events): raise ValueError('Duplicate native result events')
        if result not in ('returned','aborted'): raise ValueError('Native result must be returned or aborted')
        if result == 'aborted' and (values or events): raise ValueError('Aborted native calls cannot emit success results')
        outputs = g.contracts[node].get('outputs', {})
        if result == 'returned':
            expected = {p for p,t in outputs.items() if t != 'trigger'}
            if set(values) != expected: raise ValueError('Native result must supply every declared value output')
            for p, value in values.items(): typed(value, outputs[p])
            if any(outputs.get(event) != 'trigger' for event in events): raise ValueError('Undeclared native result event')
        # Validate completely before consuming the request or mutating outputs.
        self.pending.remove(matches[0])
        g.record('native_result', id=identity, node=node, result=result, values=copy.deepcopy(values),
                 events=list(events), boundary='explicit_engine_outcome')
        for p, value in values.items(): g.external_values[node + '.' + p] = copy.deepcopy(value)
        for event in reversed(events): g.emit(node + '.' + event)
        g.drain()

    def snapshot(self): return copy.deepcopy(dict(pending=self.pending, serial=self.serial))

    def restore(self, state):
        self.pending, self.serial = copy.deepcopy(state['pending']), state['serial']
