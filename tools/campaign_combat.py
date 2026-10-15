"""Discover and assemble source-requested fights during campaign conversion."""
from campaign_behavior_requests import dependencies
from build_campaign_combat import convert, request_site
from campaign_combat_plan import plan


def discover(models):
    candidates, unresolved = [], []
    for model in models:
        tags = set()
        for document in model['behavior_documents'].values():
            for tree in document['trees'].values():
                for request in dependencies(tree['root']):
                    if 'error' in request:
                        unresolved.append(dict(quest=model['quest'], **request))
                    else:
                        tags.add(request['tree'])
        for tag in sorted(tags):
            try:
                node, objective = request_site(model, tag)
                resolved = plan(model, node)
            except (ValueError, KeyError) as error:
                unresolved.append(dict(quest=model['quest'], tag=tag, reason=str(error)))
            else:
                candidates.append(dict(quest=model['quest'], tag=tag,
                                       objective=objective, plan=resolved))
    return dict(candidates=candidates, unresolved=unresolved)


def assemble(models, bindings, files, registration, project, native_game):
    """Apply each conversion transactionally; do not publish half a lifecycle."""
    report = discover(models)
    report.update(converted=[], runtime_verified=False)
    models = {m['quest']: m for m in models}
    files, registration = dict(files), dict(registration)
    project_path = 'Quests/' + project + '.xml'
    prefix = 'world/registration/'
    for candidate in report['candidates']:
        quest, tag = candidate['quest'], candidate['tag']
        try:
            world = {n: registration[prefix + n] for n in ('objects_mission0.xml', 'waitinglinks.xml', 'tables/ai/scheduler.xml')}
            changes, world_changes, source_plan = convert(files, world, bindings[quest],
                models[quest], tag, project_path, project_path, native_game)
        except (ValueError, KeyError) as error:
            report['unresolved'].append(dict(quest=quest, tag=tag, phase='binding', reason=str(error)))
            continue
        files.update(changes)
        registration.update({prefix + n: b for n, b in world_changes.items()})
        report['converted'].append(dict(quest=quest, tag=tag, files=sorted(changes), plan=source_plan))
    return files, registration, report
