"""Build an opt-in introduction trace overlay; never install or alter the input.

ExecuteLua and LuaWrapper are native AI nodes. LuaWrapper's single child is
preserved, including its result; exit means exit, not necessarily completion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as E
import zipfile

from campaign_intro_activity import emit

EVENTS = ('initializer_enter', 'first_entry_complete', 'initializer_complete',
          'seat_enter', 'seat_exit', 'worker_success', 'worker_fail',
          'initializer_fast_forward_true', 'initializer_fast_forward_false',
          'seat_fast_forward_true', 'seat_fast_forward_false',
          'body_enter', 'bark_branch_enter', 'bark_branch_success', 'bark_branch_fail',
          'distance_gate_child_enter', 'dialog_gate_child_enter', 'seat_branch_enter')


def lua_log(stem, actor_guid, event, limit, *, wrapper=False):
    """Read-only getters; missing NPC context still produces a bounded event."""
    # Values are validated below; JSON string quoting is Lua-compatible here.
    label = json.dumps(f'[GlueMapper intro trace] {stem} actor={actor_guid} event={event}')
    key = json.dumps(stem + ':' + event)
    # NPC LuaWrapper uses entity too (so_tailor/use and npc switch/root).
    # data.this is established for cart horses, but is not needed here.
    return f'''pcall(function()
  local e = entity
  local errors = {{}}
  local counters
  local ok, err = pcall(function()
    if not e then error("entity context unavailable") end
    e.__gmIntroTraceCounts = e.__gmIntroTraceCounts or {{}}
    counters = e.__gmIntroTraceCounts
  end)
  if not ok then
    errors[#errors+1] = "context:"..tostring(err)
    GlueMapperIntroTraceFallbackCounts = GlueMapperIntroTraceFallbackCounts or {{}}
    counters = GlueMapperIntroTraceFallbackCounts
  end
  local key = {key}
  local count = counters[key] or 0
  if count >= {limit} then return end
  counters[key] = count + 1
  local function sample(name, getter)
    local success, value = pcall(getter)
    if success then return tostring(value) end
    errors[#errors+1] = name..":"..tostring(value)
    return "unavailable"
  end
  local id = sample("entity", function() return e.id end)
  local pos = sample("pos", function()
    local p = {{}}; e:GetWorldPos(p)
    return tostring(p.x)..","..tostring(p.y)..","..tostring(p.z)
  end)
  local faction = sample("faction", function() return AI.GetFactionOf(e.id) end)
  local soul_faction = sample("soul_faction_id", function() return e.soul:GetFactionID() end)
  local world_time = sample("world_time", function() return Calendar.GetWorldTime() end)
  local world_hour = sample("world_hour", function() return Calendar.GetWorldHourOfDay() end)
  local error_text = table.concat(errors,";"):gsub("[\\r\\n]", " "):sub(1,600)
  System.LogAlways({label}.." occurrence="..tostring(count + 1).." entity="..id.." pos="..pos.." faction="..faction.." soul_faction_id="..soul_faction.." world_time="..world_time.." world_hour="..world_hour.." errors="..error_text)
end)'''


def instrument(blob, report, limit=8):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Event limit must be an integer from 1 to 100')
    placement, source = report['placement'], report['source_plan']
    names = (placement['quest'], source['tree'])
    if not all(isinstance(n, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', n) for n in names):
        raise ValueError('Invalid receipt introduction identity')
    actor = placement['actor_guid']
    if not isinstance(actor, str) or not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}', actor):
        raise ValueError('Invalid receipt actor GUID')
    stem = 'gm_intro_' + '_'.join(names)
    path = f'AI/{stem}.xml'
    expected = emit(stem, source)[path]
    if blob != expected:
        raise ValueError('Worker differs from receipt-generated worker; refusing to trace an unknown graph')
    root = E.fromstring(blob)
    init = root.find('BehaviorTree/Root/OnInit/Sequence')
    first = init.find('IfCondition/Sequence') if init is not None else None
    if first is None:
        raise ValueError('Worker has no supported first-entry initializer')

    def log(event, *, wrapper=False):
        return lua_log(stem, actor, event, limit, wrapper=wrapper)

    def mode_sample(location):
        # Native IsFastForwarded Then/Else branching; both diagnostic branches
        # succeed immediately, regardless of lookup/logging failures. No game
        # child, phase, movement, or clock is changed by this observation.
        check = E.Element('IsFastForwarded', failOnCondition='false', saveVersion='2')
        for branch, value in (('Then', 'true'), ('Else', 'false')):
            seq = E.SubElement(E.SubElement(check, branch, canSkip='1'), 'Sequence')
            seq.append(E.Element('ExecuteLua', code=log(location + '_fast_forward_' + value)))
            E.SubElement(seq, 'Success')
        return check

    def prepend_event(parent, child, event):
        index = list(parent).index(child)
        parent.remove(child)
        seq = E.Element('Sequence')
        seq.append(E.Element('ExecuteLua', code=log(event)))
        seq.append(child)
        parent.insert(index, seq)
        return seq

    init.insert(0, E.Element('ExecuteLua', code=log('initializer_enter')))
    init.insert(1, mode_sample('initializer'))
    first.append(E.Element('ExecuteLua', code=log('first_entry_complete')))
    init.append(E.Element('ExecuteLua', code=log('initializer_complete')))
    calls = root.findall('.//CallBehavior')
    if len(calls) != 1 or calls[0].get('Target') != '$workPlace':
        raise ValueError('Expected one source-bound seat behavior')
    call = calls[0]
    parent = next(p for p in root.iter() if call in list(p))
    wrapper = E.Element('LuaWrapper', onEnter=log('seat_enter', wrapper=True), onExit=log('seat_exit', wrapper=True))
    index = list(parent).index(call)
    parent.remove(call)
    seat_sequence = E.SubElement(wrapper, 'Sequence')
    seat_sequence.append(mode_sample('seat'))
    seat_sequence.append(call)
    parent.insert(index, wrapper)
    fuse = root.find('BehaviorTree/Root/Behavior/FuseBox')
    parallel = fuse.find('Child/Parallel')
    gate = parallel.find('DistanceGate')
    context = parallel.find('EntityContextElement')
    dialog = gate.find('DialogGate') if gate is not None else None
    if context is None or dialog is None or dialog.find('Sequence') is None:
        raise ValueError('Unsupported introduction branch layout')
    # Sample entry before the context operation: the nested seat trace alone
    # cannot distinguish an unentered branch from a non-decorator context node.
    prepend_event(parallel, context, 'seat_branch_enter')
    prepend_event(gate, dialog, 'distance_gate_child_enter')
    dialog.find('Sequence').insert(0, E.Element('ExecuteLua', code=log('dialog_gate_child_enter')))
    gate_index = list(parallel).index(gate)
    parallel.remove(gate)
    bark_sequence = E.Element('Sequence')
    bark_sequence.append(E.Element('ExecuteLua', code=log('bark_branch_enter')))
    bark_fuse = E.SubElement(bark_sequence, 'FuseBox', StatusPropagation='Child', OneCleanup='true', saveVersion='2')
    E.SubElement(bark_fuse, 'Child', canSkip='1').append(gate)
    for branch, event, status in (('OnSuccess', 'bark_branch_success', 'Success'),
                                  ('OnFail', 'bark_branch_fail', 'Fail')):
        seq = E.SubElement(E.SubElement(bark_fuse, branch, canSkip='1'), 'Sequence')
        seq.append(E.Element('ExecuteLua', code=log(event)))
        E.SubElement(seq, status)
    parallel.insert(gate_index, bark_sequence)
    prepend_event(root.find('BehaviorTree/Root/Behavior'), fuse, 'body_enter')
    for branch, event in (('OnSuccess', 'worker_success'), ('OnFail', 'worker_fail')):
        node = fuse.find(branch)
        if len(node) != 1 or node[0].tag != 'Callback_empty':
            raise ValueError('Expected original worker result callback')
        callback = node[0]
        node.remove(callback)
        seq = E.SubElement(node, 'Sequence')
        seq.append(E.Element('ExecuteLua', code=log(event)))
        seq.append(callback)
    return path, E.tostring(root, encoding='utf-8', xml_declaration=True)


def build(package, output, target, limit=8):
    package, output = Path(package).resolve(), Path(output).resolve()
    if output == package or package in output.parents or output in package.parents:
        raise ValueError('Diagnostic output must be separate from the input package')
    if output.exists():
        raise ValueError('Diagnostic output already exists; choose a new directory')
    receipt_blob = (package / 'quest-introductions.json').read_bytes()
    receipt = json.loads(receipt_blob)
    stem = 'gm_intro_' + receipt['placement']['quest'] + '_' + receipt['source_plan']['tree']
    path = f'AI/{stem}.xml'
    with zipfile.ZipFile(package / 'Data/gluemappertravel.pak') as archive:
        if archive.namelist().count(path) != 1:
            raise ValueError('Expected exactly one receipt-bound worker archive entry')
        blob = archive.read(path)
    path, traced = instrument(blob, receipt, limit)
    from campaign_combat_work import validate
    validate({path: traced}, Path(target))
    digest = lambda b: hashlib.sha256(b).hexdigest()
    result = dict(version=3, installed=False, input_package=str(package),
                  worker=path, actor_guid=receipt['placement']['actor_guid'],
                  receipt_sha256=digest(receipt_blob), original_worker_sha256=digest(blob),
                  traced_worker_sha256=digest(traced), events=list(EVENTS),
                  per_entity_event_limit=limit,
                  native_evidence=dict(
                      execute_lua='Data/Scripts.pak:AI/animal/basic/switch/animal_horseBrain.xml (entity context)',
                      lua_wrapper='Data/Scripts.pak:AI/profession/tailor/so_tailor.xml (use onEnter/onExit entity context and single child)',
                      position='Data/Scripts.pak:Scripts/Entities/AI/Horse.lua (GetWorldPos output table)',
                      faction='Data/Scripts.pak:Scripts/Entities/Triggers/AreaTrigger.lua (AI.GetFactionOf)',
                      soul_faction_id='Data/Scripts.pak:Scripts/Utils/EntityUtils.lua (entity.soul:GetFactionID; not assumed equivalent to temporary faction)',
                      world_time='Data/Scripts.pak:AI/world/so_door.xml (Calendar.GetWorldTime)',
                      world_hour='Data/Scripts.pak:Scripts/Entities/Lights/Light.lua (Calendar.GetWorldHourOfDay)',
                      fast_forward='Data/Scripts.pak:AI/quests/mucirna_vypaleniSemina/mucirna_vypaleniSemina.xml (IsFastForwarded Then/Else before CowerGround)',
                      retail_logging='runtime/campaign_menu.lua System.LogAlways; emitted messages observed in relocated runtime kcd.log'),
                  limitations=['Opt-in overlay only; not installed or included in setup.',
                               'seat_exit includes interruption; only worker_success/worker_fail identify those outcomes.',
                               'No quest eligibility trace; absence of an initializer event cannot identify why activation failed.',
                               'Counters last for the lifetime of the loaded entity; getters may report unavailable.',
                               'Missing entity context uses bounded session fallback counters; getter errors are recorded. Soul faction ID is distinct from temporary/effective faction.',
                               'Fast-forward mode is sampled at initializer and seat entry only, not continuously; it is not a guessed Lua time-skip flag.',
                               'Native logging primitives are verified, but this overlay has not been tested in retail.'])
    output.mkdir(parents=True)
    pak = output / 'intro-trace.pak'
    with zipfile.ZipFile(pak, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path, traced)
    result['pak_sha256'] = digest(pak.read_bytes())
    (output / 'intro-trace.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True, help='KCD2 root for native AI schema validation')
    parser.add_argument('--max-events', type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(build(args.package, args.output, args.target, args.max_events), indent=2))


if __name__ == '__main__':
    main()
