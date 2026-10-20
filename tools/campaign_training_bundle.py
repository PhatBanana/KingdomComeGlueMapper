"""Assemble a bounded training conversion with the normal dependency importer."""
from pathlib import PurePosixPath

from campaign_training_equipment import lower
from campaign_training_controller import bind, register_events


def assemble_from_source(compiler, model, document, tree, controller_blob,
                         controller_path, events, native_event_sets):
    """Resolve authored registrations before binding a converted controller."""
    from campaign_training_sources import resolve_equipment
    from campaign_behavior import reference
    source = resolve_equipment(model, document, tree)
    if any(source[phase]['document'] != document for phase in ('prepare', 'cleanup')):
        raise ValueError('Cross-document training callbacks require their original compiler document scopes')
    sites = {phase: dict(kind='behavior', target=reference(source[phase]['target']),
                         behavior=source[phase]['name']) for phase in ('prepare', 'cleanup')}
    files, report = assemble(compiler, model['quest'], document,
        source['prepare']['program']['root'], source['cleanup']['program']['root'],
        source['variables'], controller_blob, controller_path, tree, sites, events, native_event_sets)
    report['source_controller'] = source['controller']
    report['source_callbacks'] = {phase: {k: source[phase][k] for k in ('document', 'tree', 'path', 'name')}
                                  for phase in ('prepare', 'cleanup')}
    return files, report


def assemble(compiler, owner, source_document, prepare, cleanup, variables,
             controller_blob, controller_path, controller_tree, call_sites, events, native_event_sets):
    if compiler.importer is None:
        raise ValueError('Training assembly requires the shared dependency importer')
    path = PurePosixPath(controller_path)
    if (not controller_path.startswith('AI/') or '\\' in controller_path or ':' in controller_path
            or '..' in path.parts or path.suffix != '.xml'):
        raise ValueError('Training controller must be an AI package XML path')
    roots, declarations, equipment = lower(compiler, owner, source_document,
                                           prepare, cleanup, variables)
    blob, binding = bind(controller_blob, controller_tree, call_sites, roots, declarations, events)
    event_set = compiler.namespace + '_' + controller_tree + '_training'
    blob, event_table = register_events(blob, controller_tree, event_set,
                                       binding['event_signatures'], native_event_sets)
    files = dict(compiler.importer.files)
    if controller_path in files and files[controller_path] != blob:
        raise ValueError('Training controller conflicts with dependency output: ' + controller_path)
    files[controller_path] = blob
    event_path = 'Libs/Tables/ai/EventSet__' + event_set + '.xml'
    if event_path in files and files[event_path] != event_table:
        raise ValueError('Training event set conflicts with dependency output')
    files[event_path] = event_table
    binding['event_set'] = event_set
    return files, dict(equipment=equipment, controller=binding,
                       dependencies=compiler.importer.report(), publication_ready=False,
                       runtime_validated=False,
                       remaining=['connect lifecycle and source controller scheduling',
                                  'validate in game'])
