from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from cinematic_media import chunks, demux, movie_override


def packet(tag, payload, channel=0):
    header = bytearray(32)
    header[:4] = tag
    struct.pack_into('>I', header, 4, 24 + len(payload))
    header[9] = 24
    header[12] = channel
    return bytes(header) + payload


class OpeningMediaTests(unittest.TestCase):
    def test_selected_audio_and_subtitle_timing(self):
        cue = struct.pack('<5I', 0, 1000, 1200, 800, 5) + b'@key\0'
        data = (packet(b'@SFV', b'video') + packet(b'@SFA', b'wrong', 0)
                + packet(b'@SFA', b'english', 1) + packet(b'@SBT', cue))
        with tempfile.TemporaryDirectory() as tmp:
            result = demux(data, tmp, 1)
            self.assertEqual(result['video_packets'], 1)
            self.assertEqual(result['subtitle_cues'], 1)
            self.assertEqual((Path(tmp) / 'source.adx').read_bytes(), b'english')

    def test_rejects_truncated_and_overlapping_packets(self):
        data = packet(b'@SFV', b'video')
        with self.assertRaisesRegex(ValueError, 'bounds'):
            list(chunks(data[:-1]))
        bad = bytearray(data)
        bad[9] = 23
        with self.assertRaisesRegex(ValueError, 'bounds'):
            list(chunks(bad))
        with self.assertRaisesRegex(ValueError, 'header'):
            list(chunks(data + b'partial'))

    def test_override_preserves_other_movies_removes_foreign_events(self):
        source = b'<database><Cutscenes><RenderedCutscene Name="intro_new_game" Subtitles="wrong"><Events><Event StartFrame="99999"/></Events></RenderedCutscene><RenderedCutscene Name="other" Root="keep"/></Cutscenes></database>'
        root = ET.fromstring(movie_override(source, 'intro_new_game', 'Videos/test', 'movie'))
        intro = root.find("./Cutscenes/RenderedCutscene[@Name='intro_new_game']")
        self.assertIsNone(intro.find('Events'))
        self.assertEqual(root.find("./Cutscenes/RenderedCutscene[@Name='other']").get('Root'), 'keep')
        with self.assertRaisesRegex(ValueError, 'one native'):
            movie_override(b'<database><Cutscenes/></database>', 'intro_new_game', 'Videos/test', 'movie')


if __name__ == '__main__':
    unittest.main()
