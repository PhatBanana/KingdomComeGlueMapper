"""Native, controller-owned request lifetimes for converted scheduled work.

The scheduler still chooses and executes the actor's activity. This adapter
changes availability, not NPC update frequency. A native onRelease/count check
acknowledges retirement. Worker results are generation-tagged and are *not*
release acknowledgements. All state belongs to the converted controller brain.
"""
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as E

from campaign_entity_links import guid_value
from campaign_quest_bridge import UnsupportedOperation
from campaign_quest_graph import identifier, xml
from campaign_schedule_requests import request


def route_name(owner, controller, actor, handle, namespace):
    digest = hashlib.sha256(json.dumps([owner, str(guid_value(controller)),
        str(actor), handle]).encode()).hexdigest()[:20]
    return identifier(namespace) + '_lease_' + digest


def node(tag, **attributes):
    return E.Element(tag, {k: str(v) for k, v in attributes.items()})


def sequence(*children):
    result = node('Sequence'); result.extend(children); return result


def condition(value, *children):
    result = node('IfCondition', failOnCondition='false', condition=value)
    result.append(sequence(*children)); return result


def choose(value, yes, no):
    result = node('IfElseCondition', failOnCondition='false', condition=value, saveVersion='2')
    E.SubElement(result, 'Then', canSkip='1').append(yes)
    E.SubElement(result, 'Else', canSkip='1').append(no)
    return result


def assign(value):
    return node('Expression', expressions=value)


def state(name, value):
    return node('SmartObjSetBehaviorState', behaviors=repr(name), state=value)


def tree(name, body, variables=()):
    result = node('BehaviorTree', name=name, is_function='0')
    declarations = E.SubElement(result, 'Variables')
    for n, typ in variables:
        E.SubElement(declarations, 'Variable', name=n, type=typ, values='', isPersistent='0', form='single')
    root = E.SubElement(result, 'Root', OneTimeOnly='false', FailState='Recoverable', saveVersion='2')
    E.SubElement(root, 'Behavior', canSkip='1').append(body)
    return result


def validate_generated(adapter, files, catalog):
    """Check generated node/attribute ABI against this installed target build.

    The catalog is executable native XML evidence. Passing this check does not
    establish scheduler timing or the meaning of a native state enumeration.
    """
    root = E.fromstring(files['AI/' + adapter.file])
    for element in root.iter():
        if element.tag in ('BehaviorTrees', 'BehaviorTree', 'Variables', 'Variable'):
            continue
        native = catalog['nodes'].get(element.tag)
        if native is None or set(element.attrib) - set(native['attributes']):
            raise ValueError('Schedule operation does not match native ABI: ' + element.tag)


class ScheduleAdapter:
    """Lower only bound source sites; the containing source guards stay intact.

    Build this before compiling, then call install() with the *same* plan and
    complete compiled files. Lowered requests cannot be published without the
    consumer/brain registration returned by install().
    """
    def __init__(self, plan, controller_guid, namespace):
        self.plan = copy.deepcopy(plan)
        self.controller = controller_guid
        self.namespace = identifier(namespace)
        self.stem = namespace + '_schedule_' + hashlib.sha256(
            (plan['owner'] + ':' + str(guid_value(controller_guid))).encode()).hexdigest()[:16]
        self.message_type = self.stem.lower() + ':request'
        self.mailbox = self.stem.lower() + '_requests'
        self.file = namespace.lower() + '/schedule/' + self.stem.lower() + '.xml'
        self.sites = {}
        self.routes = []
        for index, lease in enumerate(plan['leases']):
            policy = lease['policy']
            if not policy['immediate']:
                raise ValueError('Deferred source requests need a next-activity boundary adapter')
            if policy['source'].lstrip('$') not in ('this.id', '__object.id'):
                raise ValueError('Schedule source needs a bound controller scope')
            name = route_name(plan['owner'], controller_guid, lease['actor'], lease['handle'], namespace)
            self.routes.append(dict(index=index, name=name, lease=lease))
            for site in lease['sites']:
                if site['operation'] != 'InstantSendMessageToNPC':
                    raise ValueError('Synchronous source schedule responses require their own response adapter')
                identity = (plan['owner'], site['document'], site['tree'], site['path'])
                if identity in self.sites:
                    raise ValueError('Ambiguous schedule request site')
                self.sites[identity] = (index, site)

    def lower(self, source, owner, document, tree_name, path, object_scope=False, actor_expression=None):
        value = request(source)
        if value is None:
            return None
        identity = (owner, document, tree_name, path)
        bound = self.sites.get(identity)
        def attributes(value):
            return {k: v for k, v in value.items() if k != 'id' or not v.isdecimal()}
        if bound is None or attributes(source['attributes']) != attributes(bound[1]['attributes']) or source['children']:
            raise UnsupportedOperation('Schedule request differs from its resolved source site')
        index, site = bound
        # The worker's this.id is the actor. Its __object remains the original
        # controller because aliases are registered on that same host.
        target = '$__object.id' if object_scope else '$this.id'
        expected = self.routes[index]['lease']['policy']['source'].lstrip('$')
        if site['add'] and expected != target.lstrip('$'):
            raise UnsupportedOperation('Schedule request source differs from its controller scope')
        if actor_expression is None:
            raise UnsupportedOperation('Schedule actor expression requires compiler scope resolution')
        return node('InstantSendMessageToNPC', target=target, type=repr(self.message_type),
                    values=f"route({index}),kind({1 if value['add'] else 0}),generation(0),actor({actor_expression})")

    def variables(self, route):
        stem = 'b_' + route['name']
        return {n: stem + '_' + n for n in ('wanted', 'draining', 'generation', 'actor')}

    def reconcile(self, route):
        v = self.variables(route); n = route['name']
        # Last release is the native boundary. No timer, Success event, actor
        # position, or animation state is used to guess that cleanup finished.
        return condition(f"${v['draining']}&($__behaviors['{n}'].count==0)",
            assign(f"${v['draining']}=false"),
            choose('$' + v['wanted'], sequence(
                assign(f"${v['generation']}=${v['generation']}+1"), state(n, 'Enabled')), node('Success')))

    def released(self, route):
        v = self.variables(route); n = route['name']
        # Preemption by an unrelated native job also invalidates queued results.
        # It does not consume a once request or remove its schedule entry.
        return condition(f"$__behaviors['{n}'].count==0",
            assign(f"${v['generation']}=${v['generation']}+1"), self.reconcile(route))

    def consumer(self):
        switch = node('Switch')
        for r in self.routes:
            i, n, lease = r['index'], r['name'], r['lease']; v = self.variables(r)
            actions = node('Switch')
            for kind, wanted in ((1, 'true'), (0, 'false')):
                branch = condition(f'$message.kind=={kind}',
                    assign(f"${v['wanted']}={wanted},${v['draining']}=true"),
                    state(n, 'Disabled'), self.reconcile(r))
                actions.append(branch)
            # A worker obtains its generation from this controller before it
            # enters any source code. A canceled old worker cannot complete a
            # newly enabled request, even if its message was already queued.
            actions.append(condition('$message.kind==2', condition(
                f"${v['wanted']}&!${v['draining']}&($__behaviors['{n}'].count>0)",
                assign(f"$answer=${v['generation']}"))))
            terminal = condition(f"($message.generation==${v['generation']})&!${v['draining']}",
                assign(f"${v['wanted']}=false,${v['draining']}=true"), state(n, 'NoRequests'))
            actions.append(condition('$message.kind==3', terminal if lease['policy']['once'] else node('Success')))
            E.SubElement(actions, 'DefaultBranch').append(node('Success'))
            switch.append(condition(f"($message.route=={i})&($sender.id==${v['actor']})&($message.actor==$sender.id)", actions))
            # Controller-authored add/remove messages have a different sender.
            switch.append(condition(f"($message.route=={i})&($sender.id==$this.id)&($message.kind<2)",
                condition(f"(${v['actor']}==$__null)|(${v['actor']}==$message.actor)",
                    assign(f"${v['actor']}=$message.actor"), copy.deepcopy(actions))))
        E.SubElement(switch, 'DefaultBranch').append(node('Success'))
        process = node('ProcessMessage', Atomic='true', timeout="'-1'", timeType='GameTime',
            variable='$message', senderInfo='$sender', inbox=repr(self.mailbox), condition='', answerVar='$answer')
        process.append(sequence(assign('$answer=0'), switch))
        loop = node('While', doFail='false', propagateChildFail='false', condition='true'); loop.append(process)
        return tree(self.stem + '_consume', loop,
                    [('message', self.message_type), ('sender', 'senderInfo'), ('answer', '_int')])

    def wrapper(self, route, file, original):
        def send(kind):
            return node('SendMessageToNPC', target='$__object.id', type=repr(self.message_type),
                values=f"route({route['index']}),kind({kind}),generation($gm_schedule_generation),actor($this.id)",
                timeType='GameTime', timeoutType='OnProcessed', timeout="'-1'",
                answer='$gm_schedule_generation' if kind == 2 else '$gm_schedule_response')
        outcomes = node('Selector')
        outcomes.append(sequence(node('IncludeTree', File=repr(file), Name=repr(original)), send(3)))
        outcomes.append(sequence(send(3), node('Fail')))
        # IncludeTree runs the complete source Root, including OnInit and exit
        # cleanup. Halt unwinds it; it does not take either terminal sequence.
        body = sequence(send(2), choose('$gm_schedule_generation>0', outcomes, node('Fail')))
        result = tree(route['name'] + '_worker', body,
            [('gm_schedule_generation', '_int'), ('gm_schedule_response', '_int')])
        result.find("Variables/Variable[@name='gm_schedule_generation']").set('isPersistent', '1')
        return result

    def install(self, files, host_template, native):
        """Transactionally bind consumer, release callback, wrappers and tables.

        The assembled template must already contain the native activity aliases.
        Copy the controller brain instead of changing a shared native brain.
        Inputs are untouched on both success and failure.
        """
        files, template = copy.deepcopy(files), copy.deepcopy(host_template)
        def data(value):
            return value.read_bytes() if isinstance(value, Path) else value
        converted_rows = {table: [] for table in native.tables}
        containers = {info['container']: name for name, info in native.tables.items()}
        for path, blob in files.items():
            if not path.lower().startswith('libs/tables/ai/') or not path.lower().endswith('.xml'):
                continue
            root = E.fromstring(data(blob))
            for container in root:
                table_name = containers.get(container.tag)
                if table_name:
                    converted_rows[table_name].extend(dict(r.attrib) for r in container if r.tag == table_name)
        def rows(table):
            result = {}
            for row in native.tables[table]['rows']:
                result.setdefault(tuple(sorted(row.items())), row)
            for row in converted_rows[table]:
                result[tuple(sorted(row.items()))] = row
            return list(result.values())
        def enum(table, label):
            matches = [r[table+'_id'] for r in rows(table) if r[table+'_name'] == label]
            if len(set(matches)) != 1: raise ValueError('Missing native schedule enumeration: ' + label)
            return matches[0]
        old_brain = template.get('BrainId')
        brains = [r for r in rows('brain') if r['brain_id'] == old_brain]
        if len(brains) != 1: raise ValueError('Schedule controller brain is missing or ambiguous')
        brain = native.guid('brain', self.stem)
        links = [r for r in rows('brain2subbrain') if r['brain_id'] == old_brain]
        smart = [r for r in rows('subbrain_smart_object') if r['subbrain_id'] in {l['subbrain_id'] for l in links}]
        if len(smart) != 1: raise ValueError('Schedule needs one native SmartObject release callback')
        smart = dict(smart[0]); original_sub = smart['subbrain_id']
        smart['subbrain_id'] = native.guid('subbrain', self.stem + '/release')
        path = 'AI/' + smart['file_name']
        if path not in files: raise ValueError('Converted controller callback document is missing')
        document = E.fromstring(data(files[path]))
        release_name = self.stem + '_release'
        release_body = sequence(*(condition(f"$__behaviorName=='{r['name']}'", self.released(r)) for r in self.routes))
        original_release = smart.get('on_release_tree')
        if original_release:
            if len([t for t in document.findall('BehaviorTree') if t.get('name') == original_release]) != 1:
                raise ValueError('Original controller release tree is missing or ambiguous')
            # Preserve its status as well as side effects. Run our bookkeeping
            # on both terminal paths, after the original callback finishes.
            selector = node('Selector')
            selector.append(sequence(node('IncludeTree', File=repr(smart['file_name']), Name=repr(original_release)),
                                     copy.deepcopy(release_body)))
            selector.append(sequence(release_body, node('Fail')))
            release_body = selector
        document.append(tree(release_name, release_body))
        smart['on_release_tree'] = release_name
        files[path] = xml(document)
        emitted = node('BehaviorTrees'); emitted.append(self.consumer())
        for r in self.routes:
            aliases = [b for b in template.findall('BehaviorTemplates/SmartBehaviorTemplate') if b.get('Name') == r['name']]
            if len(aliases) != 1: raise ValueError('Missing assembled native activity alias')
            alias = aliases[0]; location = alias.find('TreeLocation')
            if location is None: raise ValueError('Missing assembled callback location')
            emitted.append(self.wrapper(r, location.get('FileName'), location.get('TreeName')))
            location.set('FileName', self.file); location.set('TreeName', r['name'] + '_worker')
            alias.set('MaxInstances', '1')
        files['AI/' + self.file] = xml(emitted)
        types = node('database'); owner = E.SubElement(E.SubElement(types, 'Types', version='1'), 'Type', Name=self.stem.lower())
        typ = E.SubElement(owner, 'Type', Name='request')
        for field in ('route', 'kind', 'generation'): E.SubElement(typ, 'Member', Name=field, Type='int')
        E.SubElement(typ, 'Member', Name='actor', Type='wuid')
        files['Libs/Tables/ai/Types__' + self.stem.lower() + '.xml'] = xml(types)
        mailbox = native.guid('mailbox', self.stem)
        manager = native.guid('subbrain', self.stem + '/consumer')
        variables = [dict(r, brain_id=brain) for r in rows('brain_variable') if r['brain_id'] == old_brain]
        for r in self.routes:
            for field, name in self.variables(r).items():
                if any(v['brain_variable_name'] == name for v in variables):
                    raise ValueError('Schedule already installed; use the pre-assembly candidate')
                variable = dict(brain_id=brain, brain_variable_name=name,
                    ai_variable_form_id=enum('ai_variable_form', 'single'),
                    ai_variable_sync_id=enum('ai_variable_sync', 'no_sync'), is_persistent='true',
                    type={'generation':'int', 'actor':'wuid'}.get(field, 'bool'))
                if field != 'actor': variable['init_value'] = '0' if field == 'generation' else 'false'
                variables.append(variable)
        sub_rows = [dict(r, subbrain_id=smart['subbrain_id']) for r in rows('subbrain') if r['subbrain_id'] == original_sub]
        if len(sub_rows) != 1: raise ValueError('Original SmartObject subbrain is missing or ambiguous')
        sub_rows.append(dict(subbrain_id=manager, subbrain_name=self.stem,
            always_active='true', subbrain_type=enum('subbrain_type', 'BehaviorTree'), timeout='0'))
        tables = {
            'brain': [dict(brain_id=brain, brain_name=self.stem)],
            'brain_variable': variables,
            'subbrain': sub_rows,
            'subbrain_smart_object': [smart],
            'subbrain_behaviour_tree': [dict(subbrain_id=manager, file_name=self.file, tree_name=self.stem+'_consume')],
            'brain2subbrain': [dict(r, brain_id=brain, subbrain_id=smart['subbrain_id'] if r['subbrain_id']==original_sub else r['subbrain_id']) for r in links]
                + [dict(brain_id=brain, subbrain_id=manager, priority='0')],
            'mailbox': [dict(mailbox_id=mailbox, mailbox_name=self.mailbox, message_limit='-1',
                             on_accept=enum('mailbox_action_type', 'consume'))],
            'mailbox_filter': [dict(mailbox_id=mailbox, mailbox_filter_id=native.guid('mailbox_filter',self.stem), type=self.message_type)],
            'brain2mailbox': [dict(r, brain_id=brain) for r in rows('brain2mailbox') if r['brain_id']==old_brain]
                + [dict(brain_id=brain, mailbox_id=mailbox, priority='0')],
        }
        for table_name, records in tables.items(): files.update(native.emit(table_name, self.stem, records))
        template.set('BrainId', brain)
        return files, template, dict(request_consumer_installed=True, release_acknowledgement='native onRelease and count == 0',
            completion='generation-tagged source Root completion; never inferred from release',
            routes=len(self.routes), runtime_validated=False)
