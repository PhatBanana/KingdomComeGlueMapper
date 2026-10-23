"""Audit source work speech before enabling repeated native monologues.

An imported dialogue is not proof that its source repetition contract survived.
In particular campaign_dialogue currently does not lower sequence timeouts.
Keep unresolved speech separate from an otherwise usable work animation.
"""
import re
import hashlib
import json
import xml.etree.ElementTree as E

from campaign_intro_activity import normalized


def requests(blob, tree_name):
    root = normalized(blob)
    trees = root.findall("BehaviorTree[@name='" + tree_name + "']")
    if len(trees) != 1 or trees[0].find('Root') is None:
        raise ValueError('Missing or ambiguous source work speech tree')
    result = []

    def visit(node, path, ancestors):
        if node.tag in ('SendMessageToNPC', 'InstantSendMessageToNPC') and node.get('type') == 'dialog:monologRequest':
            values = node.get('values', '')
            alias = re.fullmatch(r"alias\((?:'([A-Za-z_]\w*)'|([A-Za-z_]\w*))\)", values)
            blockers = []
            if alias is None:
                blockers.append('dynamic_or_extended_speech_request')
            if node.get('target') not in ('this.id', '$this.id'):
                blockers.append('external_speaker_requires_binding')
            if node.tag == 'SendMessageToNPC' and any(node.get(k) != v for k, v in
                    {'timeoutType': 'OnProcessed', 'timeout': '-1', 'timeType': 'GameTime', 'answer': ''}.items()):
                blockers.append('unsupported_message_completion')
            result.append(dict(alias=(alias[1] or alias[2]) if alias else None,
                source_path=path, source_op=node.tag, source_request=dict(node.attrib),
                repeat=any(a['op'] in ('While', 'Loop', 'LoopWithWaiting') for a in ancestors),
                surrounding_operations=ancestors, blockers=blockers))
        counts = {}
        for child in node:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            visit(child, path + '/' + child.tag + '[' + str(counts[child.tag]) + ']',
                  ancestors + [dict(op=node.tag, attributes=dict(node.attrib))])

    visit(trees[0].find('Root'), tree_name + '/Root', [])
    return result


def assess(request, model):
    """Return precise blockers; never convert unsupported cooldowns to zero."""
    blockers = [dict(reason=x) for x in request['blockers']]
    if request['alias'] != model.get('alias'):
        raise ValueError('Work speech model does not match requested alias')
    for topic in model['topics'].values():
        for sequence in topic['sequences']:
            source = sequence['source']
            identity = source['sequence_id']
            timeout = source.get('timeout', '0')
            if not re.fullmatch(r'\d+', timeout):
                blockers.append(dict(reason='invalid_source_timeout', sequence=identity, value=timeout))
            elif int(timeout):
                blockers.append(dict(reason='source_cooldown_not_lowered', sequence=identity, value=timeout))
            if source.get('flags', '0') != '0':
                blockers.append(dict(reason='source_sequence_flags_not_lowered', sequence=identity,
                                     value=source['flags']))
    # The caller must also lower the surrounding source work/gates and register
    # actors, voices, dialogue effects, and cancellation. This check alone is
    # deliberately not a runnable-job certificate.
    return dict(alias=request['alias'], source_path=request['source_path'],
                repeat=request['repeat'], blockers=blockers,
                speech_contract_supported=not blockers, runtime_verified=False)


def require_supported(request, model):
    report = assess(request, model)
    if report['blockers']:
        reasons = sorted({b['reason'] for b in report['blockers']})
        raise ValueError('Unsupported work speech ' + str(request['alias']) + ': ' + ', '.join(reasons))
    return report


def lower_request(request, model, native_dialog_behavior, registered_dialogue, *, import_validation):
    """Lower one source leaf after its dialogue and native mailbox are present.

    This deliberately does not schedule the leaf. The work converter must retain
    the recorded enclosing gates and cancellation; a free-running replacement
    loop would change the source job. Nonzero legacy timeouts still fail closed.
    """
    from campaign_speech_messages import native_consumer, validate_request
    report = require_supported(request, model)
    # Caller must finish the dialogue importer's condition/effect, participant,
    # recording and activation validation. Bind that result to these inputs so
    # validation for another bark or an earlier native document cannot pass.
    source_digest = hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    native_digest = hashlib.sha256(E.tostring(registered_dialogue)).hexdigest()
    if (import_validation.get('status') != 'validated'
            or import_validation.get('source_sha256') != source_digest
            or import_validation.get('native_sha256') != native_digest
            or import_validation.get('pending') != []
            or import_validation.get('conditions_and_effects_validated') is not True
            or import_validation.get('participants_recordings_activation_validated') is not True):
        raise ValueError('Work speech requires complete matching dialogue import validation')
    if not native_consumer(native_dialog_behavior):
        raise ValueError('Native monologue mailbox consumer is unverified')
    # DoMonologue resolves an alias on a native Dialog, not a player-facing
    # FaderDialog or a topic imported only into the intermediate report.
    hosts = [n for n in registered_dialogue.iter('Dialog')
             if n.find("./Dialogue//Decision[@Alias='" + request['alias'] + "']") is not None]
    if len(hosts) != 1:
        raise ValueError('Work speech needs one registered native Dialog alias')
    decisions = hosts[0].findall("./Dialogue//Decision[@Alias='" + request['alias'] + "']")
    if len(decisions) != 1 or decisions[0].find('Sequences/Sequence') is None:
        raise ValueError('Work speech alias is empty or ambiguous')
    source = request['source_request']
    validate_request(source['values'], {'native_monologue_consumer': True})
    # Preserve OnProcessed/-1/GameTime: immediate success here would let the
    # enclosing source While flood dialogMailbox while speech is still running.
    if request['source_op'] not in ('SendMessageToNPC', 'InstantSendMessageToNPC'):
        raise ValueError('Unsupported source speech operation')
    leaf = E.Element(request['source_op'], dict(source))
    return leaf, dict(report, native_alias_registered=True,
                      native_consumer_verified=True,
                      activation='caller_preserves_source_work_scope')
