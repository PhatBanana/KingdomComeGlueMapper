import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from campaign_native_contracts import supplement


class NativeContractTests(unittest.TestCase):
    def test_unknown_or_missing_engine_does_not_gain_unverified_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            nodes = {}
            supplement(directory, nodes)
            self.assertEqual(nodes, {})
            path = Path(directory) / 'Bin/Win64ReleaseSteamLTO_DLL/XGenAIModule.dll'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'untested')
            supplement(directory, nodes)
            self.assertEqual(nodes, {})

    def test_matching_engine_supplements_without_overwriting_native_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Bin/Win64ReleaseSteamLTO_DLL/XGenAIModule.dll'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'tested')
            digest = hashlib.sha256(b'tested').hexdigest()
            with patch('campaign_native_contracts.VALIDATED_MODULES', {digest}):
                nodes = {}
                supplement(directory, nodes)
                self.assertEqual(nodes['NotNearPlayer']['sha256'], digest)
                original = dict(attributes={'additionalNativeField'}, children=set())
                nodes['NotNearPlayer'] = original
                supplement(directory, nodes)
                self.assertIs(nodes['NotNearPlayer'], original)
