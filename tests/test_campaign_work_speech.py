import sys
from pathlib import Path
import unittest
import hashlib
import json
import xml.etree.ElementTree as E

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_work_speech import requests, assess, require_supported, lower_request


class WorkSpeechTests(unittest.TestCase):
    def source(self, values="alias('renamed_bark')", target='this.id'):
        return ('''<BehaviorTrees><BehaviorTree name="work"><Root><Behavior><LODCheck>
        <Detail><Parallel successMode="Any" failureMode="All"><While condition="$working">
        <SendMessageToNPC target="%s" type="dialog:monologRequest" values="%s"
        timeoutType="OnProcessed" timeout="-1" timeType="GameTime" answer=""/>
        </While></Parallel></Detail></LODCheck></Behavior></Root>
        <EditorData><SendMessageToNPC type="dialog:monologRequest" values="alias('editor')"/></EditorData>
        </BehaviorTree></BehaviorTrees>''' % (target, values)).encode()

    def model(self, timeout='0', flags='0'):
        return dict(alias='renamed_bark', topics={'17': dict(sequences=[dict(source=dict(
            sequence_id='38', timeout=timeout, flags=flags))])})

    def test_executable_only_and_preserves_source_scope(self):
        rows = requests(self.source(), 'work')
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['repeat'])
        self.assertEqual(rows[0]['alias'], 'renamed_bark')
        self.assertIn('LODCheck', [a['op'] for a in rows[0]['surrounding_operations']])

    def test_cooldown_and_flags_block_repetition(self):
        request = requests(self.source(), 'work')[0]
        report = assess(request, self.model('900', '1'))
        self.assertEqual({b['reason'] for b in report['blockers']},
                         {'source_cooldown_not_lowered', 'source_sequence_flags_not_lowered'})
        with self.assertRaisesRegex(ValueError, 'source_cooldown_not_lowered'):
            require_supported(request, self.model('900'))

    def test_dynamic_alias_and_other_actor_not_guessed(self):
        row = requests(self.source('alias($selected)', '__player'), 'work')[0]
        self.assertIsNone(row['alias'])
        self.assertIn('external_speaker_requires_binding', row['blockers'])

    def test_simple_request_is_not_runtime_proof(self):
        row = requests(self.source(), 'work')[0]
        report = require_supported(row, self.model())
        self.assertTrue(report['speech_contract_supported'])
        self.assertFalse(report['runtime_verified'])
        with self.assertRaisesRegex(ValueError, 'does not match'):
            assess(row, dict(self.model(), alias='wrong'))

    def native(self):
        return E.fromstring('''<BehaviorTrees>
        <BehaviorTree name="monologRequestRead"><Root><ProcessMessage
        variable="$t_monolog_request" inbox="'dialogMailbox'"/></Root></BehaviorTree>
        <BehaviorTree name="monologRequestExecution"><Root><Sequence>
        <DoMonologue DecisionAlias="$t_monolog_request.alias"/>
        <ForceLook LookTarget="$t_monolog_request.lookAtId"/>
        </Sequence></Root></BehaviorTree></BehaviorTrees>''')

    def registration(self, host='Dialog'):
        return E.fromstring('<Skald><' + host + '><Dialogue><Decision Alias="renamed_bark">'
            '<Sequences><Sequence Name="seq_38"/></Sequences></Decision></Dialogue></' + host + '></Skald>')

    def validation(self, model=None, document=None):
        model = self.model() if model is None else model
        document = self.registration() if document is None else document
        return dict(status='validated', pending=[], conditions_and_effects_validated=True,
            participants_recordings_activation_validated=True,
            source_sha256=hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            native_sha256=hashlib.sha256(E.tostring(document)).hexdigest())

    def test_lowering_keeps_blocking_completion_and_rejects_player_only_registration(self):
        row = requests(self.source(), 'work')[0]
        leaf, report = lower_request(row, self.model(), self.native(), self.registration(), import_validation=self.validation())
        self.assertEqual(leaf.attrib, row['source_request'])
        self.assertEqual(leaf.tag, 'SendMessageToNPC')
        self.assertEqual(leaf.get('timeoutType'), 'OnProcessed')
        self.assertFalse(report['runtime_verified'])
        with self.assertRaisesRegex(ValueError, 'registered native Dialog'):
            lower_request(row, self.model(), self.native(), self.registration('FaderDialog'), import_validation=self.validation(document=self.registration('FaderDialog')))

    def test_lowering_refuses_unverified_consumer_and_nonzero_timeout(self):
        row = requests(self.source(), 'work')[0]
        with self.assertRaisesRegex(ValueError, 'consumer is unverified'):
            lower_request(row, self.model(), E.Element('BehaviorTrees'), self.registration(), import_validation=self.validation())
        with self.assertRaisesRegex(ValueError, 'source_cooldown_not_lowered'):
            lower_request(row, self.model('120'), self.native(), self.registration(), import_validation=self.validation())

    def test_import_validation_cannot_be_reused_for_changed_document_or_pending_effects(self):
        row = requests(self.source(), 'work')[0]
        document = self.registration()
        document.find('.//Sequence').set('EntryCondition', 'true')
        for validation in (self.validation(), dict(self.validation(document=document), pending=['effect'])):
            with self.assertRaisesRegex(ValueError, 'matching dialogue import validation'):
                lower_request(row, self.model(), self.native(), document, import_validation=validation)

    def test_instant_request_remains_instant_and_does_not_invent_timer(self):
        blob = self.source().replace(b'SendMessageToNPC', b'InstantSendMessageToNPC')
        row = requests(blob, 'work')[0]
        leaf, _ = lower_request(row, self.model(), self.native(), self.registration(),
                                import_validation=self.validation())
        self.assertEqual(leaf.tag, 'InstantSendMessageToNPC')
        self.assertEqual(leaf.attrib, row['source_request'])
        self.assertEqual(len(leaf), 0)


if __name__ == '__main__':
    unittest.main()
