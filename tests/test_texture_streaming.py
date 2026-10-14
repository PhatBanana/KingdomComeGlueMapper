import struct
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from texture_streaming import layout, split_generated, validate_family, repair_family, complete_rgba_mips, checked_entries


def texture(w=256, h=256, fmt=78):
    header = bytearray(148); header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x2100f, h, w, 0, 0, max(w,h).bit_length())
    struct.pack_into('<II4s', header, 76, 32, 4, b'DX10')
    struct.pack_into('<5I', header, 128, fmt, 3, 0, 1, 0)
    return bytes(header)+b''.join(bytes([i])*s for i,s in enumerate(layout(header)['sizes']))


class TextureStreamingTests(unittest.TestCase):
    def test_packager_rejects_incomplete_family_across_entries(self):
        family = split_generated(texture(512,512))
        del family['.1']
        with self.assertRaisesRegex(ValueError, 'Missing texture mip'):
            list(checked_entries(('gluebuild/test.dds'+k,v) for k,v in family.items()))

    def test_alpha_slices_require_their_base(self):
        with self.assertRaisesRegex(ValueError, 'Missing alpha base'):
            validate_family(texture(), {'.1a': b'pixels'})

    def test_float_native_resident_tail(self):
        parts = split_generated(texture(2048, 2048, 10))
        self.assertEqual(len(parts['']), 2836)
        self.assertEqual(validate_family(parts[''], parts)['streamed_mips'], 7)
        self.assertEqual(struct.unpack_from('<I', parts[''], 116)[0], 2)

    def test_missing_mask_mips_preserve_top_and_filter_channels_independently(self):
        import io
        from PIL import Image
        image = Image.new('RGBA', (2, 2))
        image.putdata([(100, 0, 0, 0), (100, 0, 0, 0), (0, 0, 0, 255), (0, 0, 0, 255)])
        stream = io.BytesIO(); image.save(stream, format='DDS')
        original = stream.getvalue(); result = complete_rgba_mips(original)
        self.assertEqual(result[128:len(original)], original[128:])
        self.assertEqual(sorted(result[-4:]), [0, 0, 50, 128])
        self.assertEqual(validate_family(result, {})['resident_mips'], 2)

    def test_native_layout_preserves_retained_mip_bytes(self):
        source=texture(512,256);parts=split_generated(source)
        info=layout(parts['']);split=validate_family(parts[''],parts)['streamed_mips']
        joined=b''.join(parts['.'+str(i)] for i in range(split,0,-1))+parts[''][148:]
        self.assertEqual(joined,source[148:148+sum(info['sizes'])])
        self.assertEqual(validate_family(parts[''],parts)['resident_mips'],4)

    def test_missing_or_wrong_size_mip_is_rejected(self):
        parts=split_generated(texture(512,512));base=parts.pop('')
        parts.pop('.1')
        with self.assertRaisesRegex(ValueError,'Missing texture mip'):validate_family(base,parts)
        parts['.1']=b'bad'
        with self.assertRaisesRegex(ValueError,'Wrong texture mip size'):validate_family(base,parts)

    def test_arrays_and_truncation_rejected(self):
        blob=bytearray(texture());struct.pack_into('<I',blob,140,2)
        with self.assertRaisesRegex(ValueError,'single 2D'):split_generated(blob)
        with self.assertRaisesRegex(ValueError,'complete DDS'):split_generated(texture()[:-1])

    def test_already_split_rejected(self):
        with self.assertRaisesRegex(ValueError,'already streamed'):
            split_generated(split_generated(texture())[''])

    def test_repair_accepts_only_matching_shared_pixel_payloads(self):
        parts=split_generated(texture(512,512));base=parts.pop('')
        incomplete={k:v for k,v in parts.items() if k!='.1'}
        self.assertEqual(repair_family(base,incomplete,[(base,parts)]),{'.1':parts['.1']})
        donor=dict(parts);donor['.2']=bytes(len(donor['.2']))
        with self.assertRaisesRegex(ValueError,'Missing texture mip'):
            repair_family(base,incomplete,[(base,donor)])

if __name__=='__main__':unittest.main()
