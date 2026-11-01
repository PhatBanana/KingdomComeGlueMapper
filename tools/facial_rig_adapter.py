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


# Native KCD2 poses with a KCD1 counterpart the forward table does not name.
# (FA_POSE source, KCD1 targets without the _blendWeightVertex suffix, basis).
REVERSE_EXTRA = (
    ('C_eyesDown', ('eye_down',), 'name: S2 heads spell eyeDown as eye_down'),
    ('C_eyesLeft', ('eye_left',), 'name: S2 spelling of eyeLeft'),
    ('C_eyesRight', ('eye_right',), 'name: S2 spelling of eyeRight'),
    ('C_eyesUp', ('eye_up',), 'name: S2 spelling of eyeUp'),
    ('C_sticky_center', ('stickyLips',), 'name: centre lip stickiness'),
    ('C_U', ('leftPucker', 'rightPucker'), 'semantic: the U viseme rounds and protrudes the lips'),
    ('L_upLipRaise', ('leftMouthUp',), 'semantic: left upper lip raiser (S2 heads only)'),
    ('R_upLipRaise', ('rightMouthUp',), 'semantic: right upper lip raiser (S2 heads only)'),
    ('C_lipPart', ('mouthUp', 'mouth_up'), 'semantic, low confidence: upper lip parts from the lower lip'),
    ('L_browsLowerer', ('leftBrowsDownOut',), 'semantic: the native lowerer covers inner and outer brow'),
    ('R_browsLowerer', ('rightBrowsDownOut',), 'semantic: the native lowerer covers inner and outer brow'),
)


def reverse_speech_mapping():
    """FA_POSE pose -> KCD1 blend joints, with one provenance row per pair.

    Inverts speech_mapping. Where the forward table fans one KCD1 control out
    to two native poses (lower lip, squint), the first native pose drives it
    and the second is recorded as unused, since one joint takes one driver.
    """
    mapping, rows, driven = {}, [], set()
    for source, targets in speech_mapping().items():
        for target in targets:
            if source in driven:
                rows.append(dict(fa_pose=target, kcd1=source, basis='forward table', used=False,
                                 note='second native pose of a fanned-out control'))
                continue
            driven.add(source)
            mapping.setdefault(target, []).append(source)
            rows.append(dict(fa_pose=target, kcd1=source, basis='forward table', used=True))
    for pose, targets, basis in REVERSE_EXTRA:
        for target in targets:
            name = target + '_blendWeightVertex'
            if name in driven:
                raise ValueError('Competing reverse facial driver: ' + name)
            driven.add(name)
            mapping.setdefault('FA_POSE_' + pose, []).append(name)
            rows.append(dict(fa_pose='FA_POSE_' + pose, kcd1=name, basis=basis, used=True))
    return mapping, rows


def load_reverse_adapter(target, kcd1_names, native_names=None):
    """Aliases that let a native track drive the KCD1 blend joints a package's faces carry.

    `kcd1_names` are the *_blendWeightVertex joints of the converted faces;
    rows whose KCD1 joint no face has are dropped, so S1-only packages get no
    S2 rows. Curves are not rescaled: both rigs store the weight as the x of a
    float position track (native jaw ranges ~0.37, KCD1 ~0.5).
    """
    if native_names is None:
        with ExitStack() as stack:
            chr_blob, _ = Assets(Path(target), stack).get('objects/characters/humans/male/skeleton/male.chr')
        native_names = {b['name'] for b in bone_table(read_chunks(chr_blob))}
    kcd1_names = set(kcd1_names)
    full, rows = reverse_speech_mapping()
    mapping = {}
    for pose, joints in full.items():
        present = [j for j in joints if j in kcd1_names]
        if present: mapping[pose] = present
    aliases = controller_aliases(set(native_names), kcd1_names, mapping)
    driven = {j for joints in mapping.values() for j in joints}
    report = dict(rows=[dict(r, present=r['kcd1'] in kcd1_names) for r in rows],
                  aliases=sum(len(v) for v in mapping.values()),
                  kcd1_without_driver=sorted(kcd1_names - driven),
                  fa_pose_without_target=sorted(n for n in native_names if n.startswith('FA_POSE_') and n not in mapping),
                  amplitude='copied unchanged; native and KCD1 weights share the x channel of float position tracks',
                  exact_acting_equivalence=False)
    return aliases, report


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
