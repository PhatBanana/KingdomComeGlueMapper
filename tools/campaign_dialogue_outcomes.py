"""Lower compound source skill-result predicates to native outcome branches."""
import copy
import re

from campaign_dialogue_conditions import expand_functions


TOKENS = re.compile(r"'(?:[^'\\]|\\.)*'|\b(?:skillCheckSuccess|skillCheckFail)\b")


def outcomes(expression, functions):
    if expression.strip() in ('skillCheckSuccess', 'skillCheckFail'):
        return None  # Already handled directly by SelectionCompiler.
    # Expand helper predicates but retain the two engine-owned result symbols.
    expression = expand_functions(expression, {k: v for k, v in functions.items()
        if k not in ('skillCheckSuccess', 'skillCheckFail')})
    if not any(m.group() in ('skillCheckSuccess', 'skillCheckFail')
               for m in TOKENS.finditer(expression)):
        return None
    return {result: TOKENS.sub(lambda m: (
        str(int((m.group() == 'skillCheckSuccess') == success))
        if m.group() in ('skillCheckSuccess', 'skillCheckFail') else m.group()), expression)
        for result, success in (('Success', True), ('Fail', False))}


def lower(dialogue, specifications):
    """Split automatic responses; preserve effects, continuation and history.

    A OR success cannot become A AND SkillcheckCondition=Success. Evaluate
    the source expression separately for each native result instead. Both
    alternatives remain part of the same decision and execute one payload.
    """
    aliases = {}
    for sequences in list(dialogue.iter('Sequences')):
        for sequence in list(sequences):
            name = sequence.get('Name')
            if name not in specifications:
                continue
            if sequence.find('UiPrompt') is not None:
                raise ValueError('Compound skill outcome requires an automatic response: ' + name)
            variant = copy.deepcopy(sequence)
            alternate = name + '_skill_fail'
            if any(n.get('Name') == alternate for n in dialogue.iter('Sequence')):
                raise ValueError('Skill outcome identity collision: ' + alternate)
            variant.set('Name', alternate)
            continuation = variant.find('Decision')
            if continuation is not None:
                # Keep one copy of the continuation's identities and state.
                # The original branch owns it; the other result jumps to it.
                if not continuation.get('Name'):
                    raise ValueError('Unnamed skill outcome continuation: ' + name)
                variant.remove(continuation)
                variant.set('EndType', 'GoTo')
                variant.set('GoToDecision', continuation.get('Name'))
            for node, result in ((sequence, 'Success'), (variant, 'Fail')):
                node.set('SkillcheckCondition', result)
                condition = specifications[name][result]
                if condition:
                    node.set('EntryCondition', condition)
                else:
                    node.attrib.pop('EntryCondition', None)
            sequences.insert(list(sequences).index(sequence) + 1, variant)
            aliases[name] = alternate
    # A source once-only/history query refers to either outcome of that same
    # response. Do not make it replayable just because its native ID split.
    pattern = re.compile(r"SequenceUsed\('([^']+)'\)")
    for node in dialogue.iter():
        for key in ('EntryCondition', 'Condition'):
            if key in node.attrib:
                node.set(key, pattern.sub(lambda m:
                    "(" + m.group() + " OR SequenceUsed('" + aliases[m[1]] + "'))"
                    if m[1] in aliases else m.group(), node.get(key)))
    return aliases


def refresh(blob, model, quest_models):
    """Upgrade an existing imported dialogue only when source predicates match.

    Recompile conditions from source while retaining installed voice/facial
    and presentation payloads. Never infer skill results from translated text.
    """
    import xml.etree.ElementTree as ET
    from campaign_dialogue_conditions import QuestConditions
    from campaign_dialogue import expose_sequence_history
    from campaign_quest_graph import xml

    root = ET.fromstring(blob)
    dialogue = root.find('.//Dialogue')
    if dialogue is None:
        raise ValueError('Expected imported dialogue')
    records = {r['source']['sequence_id']: r
               for topic in model['topics'].values() for r in topic['sequences']}
    compiler = QuestConditions(quest_models, model.get('functions', {}), sequences=records)
    declared = {p.get('Name') for p in root.findall('.//Ports/Port')}
    specs = {}
    for sid, record in records.items():
        variants = outcomes(record['entry']['entry_condition'], model.get('functions', {}))
        if variants is None:
            continue
        name = 'seq_' + sid
        matches = [s for s in dialogue.iter('Sequence') if s.get('Name') == name]
        if len(matches) != 1:
            raise ValueError('Missing/ambiguous skill response: ' + name)
        seq = matches[0]
        if seq.get('SkillcheckCondition'):
            raise ValueError('Skill response already lowered: ' + name)
        expected = compiler.sequence_condition(sid)
        installed = seq.get('EntryCondition', '')
        wrapper = None
        if installed != expected:
            match = re.fullmatch(r"Port\('([^']+)'\) AND \((.*)\)", installed, re.S)
            if match and match[1] in declared and match[2] == expected:
                wrapper = match[1]
        if installed != expected and wrapper is None:
            raise ValueError('Installed predicate differs from source compilation: ' + name)
        specs[name] = {result: compiler.sequence_condition(sid, expression)
                       for result, expression in variants.items()}
        if wrapper is not None:
            specs[name] = {result: "Port('" + wrapper + "')" +
                (' AND (' + value + ')' if value else '') for result, value in specs[name].items()}
    if set(compiler.bindings) - declared:
        raise ValueError('Outcome refresh requires new condition bindings')
    aliases = lower(dialogue, specs)
    expose_sequence_history(dialogue)
    return (xml(root) if aliases else blob), aliases
