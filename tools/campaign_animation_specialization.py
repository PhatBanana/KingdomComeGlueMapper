"""Specialize fixed helper includes reached under proven actor-gender branches."""
import copy

from campaign_sources import key
from campaign_work_animations import child_controllers
from quest_import import behavior_path, literal


def specialize(models):
    result = copy.deepcopy(models)
    report = []
    for model in result:
        documents = model['behavior_documents']
        originals = dict(documents)
        queue = [(path, name, tree, None) for path, document in originals.items()
                 for name, tree in document['trees'].items()]
        created = {}

        def clone(document, name, controllers):
            identity = (document, name, tuple(controllers))
            if identity in created:
                return created[identity]
            if document not in originals or name not in originals[document]['trees']:
                return None  # Ordinary unresolved include reporting handles it.
            if document.startswith('libs/ai/quests/'):
                return None  # Named quest state/callback ownership stays intact.
            variant = 'libs/ai/__controller_variants/' + '_'.join(controllers) + '/' + document.removeprefix('libs/ai/')
            if variant in originals:
                raise ValueError('Controller specialization collides with source behavior document')
            target = documents.setdefault(variant, dict(trees={}, provenance=copy.deepcopy(originals[document].get('provenance', []))))
            tree = copy.deepcopy(originals[document]['trees'][name])
            tree['animation_controllers'] = list(controllers)
            tree['source_document'] = document
            target['trees'][name] = tree
            created[identity] = variant
            queue.append((variant, name, tree, tuple(controllers)))
            report.append(dict(owner=model['quest'], source_document=document, tree=name,
                               document=variant, controllers=list(controllers)))
            return variant

        def visit(node, controllers):
            if node['op'] == 'IncludeTree' and controllers:
                attrs = node['attributes']
                file, name = literal(attrs.get('File', '')), literal(attrs.get('Name', ''))
                if file and name and not file.startswith('$') and not name.startswith('$'):
                    path = key(behavior_path(file))
                    # A cloned helper still refers to source files; clones are
                    # created once before traversal, so recursive calls close.
                    target = clone(path, name, controllers)
                    if target:
                        attrs['File'] = '"' + target.removeprefix('libs/ai/') + '"'
            for child in node['children']:
                visit(child, child_controllers(node, child, controllers))

        index = 0
        while index < len(queue):
            _, _, tree, controllers = queue[index]
            index += 1
            visit(tree['root'], controllers)
    return result, report
