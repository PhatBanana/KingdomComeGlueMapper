from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import zipfile
import test_campaign_opening_clock as clock_fixture
from setup_opening_clock import upgrade


class SetupClockPaths(unittest.TestCase):
    def test_saved_job_string_paths_upgrade_real_archives_and_repeat_safely(self):
        fixture = clock_fixture.OpeningClockTests()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, package = root/'source', root/'package'
            (source/'Data').mkdir(parents=True)
            (package/'Data').mkdir(parents=True)
            with zipfile.ZipFile(source/'Data/Scripts.pak','w') as z:
                z.writestr('opening.xml',fixture.source())
            with zipfile.ZipFile(package/'Data/gluemappertravel.pak','w') as z:
                z.writestr('project.xml',fixture.graph())
            with patch.multiple('setup_gameplay',PROJECT='project.xml',OPENING='open',
                                OPENING_CLOCK={'controller':'opening.xml','tree':'opening'}):
                files, report = upgrade(str(package),str(source))
                self.assertIn('Data/gluemappertravel.pak',files)
                self.assertEqual(report['hour'],'10')
                with zipfile.ZipFile(package/'Data/gluemappertravel.pak') as z:
                    graph=E.fromstring(z.read('project.xml'))
                self.assertIsNotNone(graph.find(".//Function[@MethodName='wh::rpgmodule::AdvanceWorldTime']"))
                self.assertEqual(upgrade(str(package),str(source))[0],{})
