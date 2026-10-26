"""Apply Storm tasks to souls and record every operation with its provenance.

Order (an inference, see ASSUMPTIONS['rule-order']): storm.xml task order,
source order within a task, rule order within a source. customOperation
macros (common/roles_operations.xml) are expanded in place, recursively.

Roles are tracked per soul as ``RoleState``: definite, or conditional with
the deps (forks, unsupported selectors, assumptions) that made it so.
"""
from collections import Counter

from .selectors import Context, V, evaluate

ROLE_OPS = {'addRole', 'removeRole', 'addMetarole'}


class RoleState:
    __slots__ = ('definite', 'deps', 'sources')

    def __init__(self, definite, deps, sources):
        self.definite, self.deps, self.sources = definite, frozenset(deps), list(sources)

    def as_dict(self):
        return dict(status='DEFINITE' if self.definite else 'CONDITIONAL', deps=sorted(self.deps),
                    sources=self.sources)


class Result:
    def __init__(self, soul):
        self.soul = soul
        self.roles = {}            # role -> RoleState
        self.metaroles = {}
        self.operations = []       # every op of every applying/forking rule
        self.rules = Counter()     # status -> count
        self.unsupported = Counter()
        self.assumptions = Counter()
        self.name_hits = set()
        self.alternatives = []     # rules that are False only because of an assumption

    def as_dict(self):
        s = self.soul
        return dict(soul=s.name, origin=s.origin, file=s.file,
                    attributes={k: s.get(k) for k in ('soul_archetype_id', 'social_class_id', 'factionName',
                                                    'skald_character_name', 'voice_group_name')},
                    roles={r: st.as_dict() for r, st in sorted(self.roles.items())},
                    metaroles={r: st.as_dict() for r, st in sorted(self.metaroles.items())},
                    operations=self.operations, rule_status=dict(self.rules),
                    unsupported=dict(self.unsupported.most_common()), assumptions=dict(self.assumptions.most_common()),
                    alternative_rules=self.alternatives)


class Engine:
    def __init__(self, program, tables, tasks=None):
        self.program, self.tables = program, tables
        self.custom = {n: bodies for n, bodies in program.custom_selectors.items()}
        self.ctx = Context(tables, self.custom)
        self.tasks = [t for t, _ in program.tasks if t != 'common' and (tasks is None or t in tasks)]
        self.unknown_operations = Counter()

    def expand(self, op, depth=0):
        """Yield primitive operations; custom operations expand recursively."""
        bodies = self.program.custom_operations.get(op.tag)
        if not bodies or depth > 16:
            yield op, None
            return
        # Duplicate macro bodies are not merged; the first definition is used
        # and the duplication is reported in inventory.
        for child in bodies[0][1]:
            if isinstance(child.tag, str):
                for sub, _ in self.expand(child, depth + 1):
                    yield sub, op.tag

    def run(self, soul, record_ops=True):
        result = Result(soul)
        ctx = self.ctx
        ctx.begin_soul(soul, result.roles)
        ctx.name_hits = result.name_hits
        order_checks = []
        for task in self.tasks:
            for source in self.program.task(task):
                ctx.source = source
                for rule in source.rules:
                    selectors = rule.find('selectors')
                    v = evaluate(selectors, soul, ctx) if selectors is not None else V({True})
                    status = v.status()
                    result.rules[status] += 1
                    for d in v.deps:
                        kind, _, what = d.partition(':')
                        if kind in ('unsupported', 'ambiguous'): result.unsupported[what] += 1
                        elif kind == 'assume': result.assumptions[what] += 1
                    if status == 'NO':
                        assumed = sorted(d for d in v.deps if d.startswith('assume:'))
                        if assumed:
                            # False only under an inferred semantic: list what the
                            # rule would do under the documented alternative.
                            ops = rule.find('operations')
                            if 'assume:rule-order' in assumed: order_checks.append((len(result.alternatives), selectors))
                            result.alternatives.append(dict(
                                task=task, file=source.path, layer=source.layer, rule=rule.get('name'),
                                deps=assumed, operations=[dict(op=o.tag, **o.attrib) for c in (ops if ops is not None else [])
                                                          if isinstance(c.tag, str) for o, _ in self.expand(c)]))
                        continue
                    operations = rule.find('operations')
                    if operations is None: continue
                    where = dict(task=task, file=source.path, layer=source.layer, rule=rule.get('name'))
                    for op, macro in ((o, m) for child in operations if isinstance(child.tag, str)
                                      for o, m in self.expand(child)):
                        if task == 'roles' and op.tag not in ROLE_OPS:
                            # Neither a role operation nor a defined customOperation:
                            # no modeled effect.
                            self.unknown_operations[op.tag] += 1
                            result.unsupported['operation ' + op.tag] += 1
                        if record_ops:
                            result.operations.append(dict(where, op=op.tag, attrs=dict(op.attrib), macro=macro,
                                                          status=status, deps=sorted(v.deps)))
                        if task == 'roles' and op.tag in ROLE_OPS:
                            self._role_op(result, op, v, where)
        ctx.source = None
        # hasRole readers that ran before a later source added the role: would
        # they apply if hasRole saw the final role set instead?
        ctx.cache = {}
        for index, selectors in order_checks:
            result.alternatives[index]['with_final_roles'] = evaluate(selectors, soul, ctx).status()
        return result

    @staticmethod
    def _role_op(result, op, v, where):
        name = op.get('name')
        if not name: return
        target = result.metaroles if op.tag == 'addMetarole' else result.roles
        definite = v.outs == {True}
        sources = [dict(where, op=op.tag)]
        current = target.get(name)
        if op.tag in ('addRole', 'addMetarole'):
            if definite:
                target[name] = RoleState(True, v.deps, (current.sources if current else []) + sources)
            elif current is None or not current.definite:
                target[name] = RoleState(False, (current.deps if current else frozenset()) | v.deps,
                                         (current.sources if current else []) + sources)
            else:
                current.sources.extend(sources)
        elif op.tag == 'removeRole' and current is not None:
            if definite:
                del target[name]
            else:
                target[name] = RoleState(False, current.deps | v.deps, current.sources + sources)
