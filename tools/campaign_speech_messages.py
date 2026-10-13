"""Bind supported legacy speech requests to the native speech consumer.

Ordinary imported records remain namespaced. Engine speech messages cannot:
their identity selects the native mailbox handler. This bounded ABI accepts
alias/look-at requests; unsupported legacy fields require their own adapter.
"""
import re
from campaign_quest_bridge import UnsupportedOperation


MESSAGE = 'dialog:monologRequest'


def validate_request(values, catalog):
    if not catalog.get('native_monologue_consumer'):
        raise UnsupportedOperation('Native monologue mailbox consumer is unverified')
    # These are source message initializers, not Lua calls. Preserve values;
    # only accept the fields whose native consumer has been inspected.
    field = re.compile(r"\s*(alias|lookAtId)\(([^()]*)\)\s*(?:,|$)")
    offset, seen = 0, set()
    while offset < len(values):
        match = field.match(values, offset)
        if not match or match[1] in seen:
            raise UnsupportedOperation('Monologue request fields need an ABI adapter')
        value = match[2].strip()
        if match[1] == 'alias':
            if not re.fullmatch(r"(?:[A-Za-z_]\w*|'[A-Za-z_]\w*')", value):
                raise UnsupportedOperation('Dynamic monologue alias requires conversion')
        elif not re.fullmatch(r'\$[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', value):
            raise UnsupportedOperation('Unsupported monologue look-at reference')
        seen.add(match[1]); offset = match.end()
    if 'alias' not in seen:
        raise UnsupportedOperation('Monologue request needs a source alias')
    return MESSAGE


def native_consumer(document):
    """Require runtime read and execution nodes, excluding editor duplicates."""
    read_tree = document.find("BehaviorTree[@name='monologRequestRead']")
    execution = document.find("BehaviorTree[@name='monologRequestExecution']")
    if read_tree is None or execution is None:
        return False
    reads = read_tree.findall('./Root//ProcessMessage')
    calls = execution.findall('./Root//DoMonologue')
    return (any(n.get('variable') == '$t_monolog_request' and n.get('inbox') == "'dialogMailbox'" for n in reads)
            and any(n.get('DecisionAlias') == '$t_monolog_request.alias' for n in calls)
            and any(n.get('LookTarget') == '$t_monolog_request.lookAtId'
                    for n in execution.findall('./Root//ForceLook')))
