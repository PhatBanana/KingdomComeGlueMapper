"""Named KCD1 morph-control to KCD2 speech-control compatibility adapter.

This is a semantic rig mapping, not regenerated acting. Both controller sets
remain in each clip so original converted heads keep their original curves.
Unmapped expressive controls are retained, not guessed or silently discarded.
"""
from contextlib import ExitStack
from pathlib import Path
import zlib

from audit_character_bodies import Assets, bone_table
from clothing_regions import read_chunks


def speech_mapping():
    pairs = {
        'eyeDown': ['C_eyesDown'], 'eyeLeft': ['C_eyesLeft'],
        'eyeRight': ['C_eyesRight'], 'eyeUp': ['C_eyesUp'],
        'mouthOpen': ['C_jawDrop'], 'mouthScream': ['C_mouthStretch'],
        'mouthLeft': ['C_mouthLeft'], 'mouthRight': ['C_mouthRight'],
        'mouthFront': ['C_jawThrust'], 'o': ['C_O'],
        'pbm': ['C_press'], 'fv': ['C_bite'], 'shCh': ['C_funnel'],
        'lowLipDown': ['L_lowLipDepressor', 'R_lowLipDepressor'],
    }
    for old, new in (('left', 'L'), ('right', 'R')):
        for name, targets in {
            'Blink': ['eyelidClose'], 'BrowsDownIn': ['browsLowerer'],
            'BrowsUpIn': ['browsUp_in'], 'BrowsUpOut': ['browsUp_out'],
            'Cheek': ['cheekRaiser'], 'DimpleCheeks': ['dimpler'],
            'MouthSad': ['cornerDepressor'], 'MouthSpread': ['lipStretcher'],
            'Neck': ['neck_stretch'], 'Nose': ['noseWrinkler'],
            'Smile': ['cornerPull'], 'SmileOpen': ['smileOpen'],
            'Squint': ['squint_up', 'squint_low'],
        }.items():
            pairs[old + name] = [new + '_' + t for t in targets]
    return {s + '_blendWeightVertex': ['FA_POSE_' + t for t in ts]
            for s, ts in pairs.items()}


def controller_aliases(source_names, target_names, mapping):
    """Validate named contracts and reject competing drivers/CRC collisions."""
    result, targets = {}, set()
    all_names = set(source_names) | set(target_names)
    hashes = {}
    for name in all_names:
        crc = zlib.crc32(name.encode('ascii'))
        if crc in hashes and hashes[crc] != name:
            raise ValueError('Facial controller hash collision')
        hashes[crc] = name
    for source, destinations in mapping.items():
        if source not in source_names or not destinations:
            raise ValueError('Missing source facial control: ' + source)
        for target in destinations:
            if target not in target_names:
                raise ValueError('Missing target facial control: ' + target)
            if target in targets or target in source_names:
                raise ValueError('Competing facial control driver: ' + target)
            targets.add(target)
        result[zlib.crc32(source.encode())] = tuple(zlib.crc32(t.encode()) for t in destinations)
    return result


def load_speech_adapter(source, target):
    # Reference assets establish the two rig vocabularies. No soul, recording,
    # quest or conversation is selected by these asset names.
    source_path = 'objects/characters/humans/head/henry.skin'
    target_path = 'objects/characters/humans/male/skeleton/male.chr'
    with ExitStack() as stack:
        old, source_receipt = Assets(Path(source), stack).get(source_path)
        new, target_receipt = Assets(Path(target), stack).get(target_path)
    source_names = {b['name'] for b in bone_table(read_chunks(old))}
    target_names = {b['name'] for b in bone_table(read_chunks(new))}
    mapping = speech_mapping()
    aliases = controller_aliases(source_names, target_names, mapping)
    return aliases, dict(mapping=mapping, source_rig=source_receipt,
                        target_rig=target_receipt, exact_acting_equivalence=False,
                        retained_unmapped_controls=sorted(n for n in source_names
                            if n.endswith('_blendWeightVertex') and n not in mapping))
