"""Storm selector algebra with explicit outcome sets.

A selector evaluates to ``V(outs, deps)``. ``outs`` is the set of possible
results ({True}, {False} or both). ``deps`` names why the result is not a
plain data fact:

* ``fork:<id>``        the value varies at runtime (hasRandomValue, game mode).
* ``unsupported:<id>`` the primitive or its input is not modeled.
* ``ambiguous:<id>``   the data itself is ambiguous (duplicate customSelector bodies).
* ``assume:<id>``      the value relies on an inferred semantic and the
                       documented alternative semantic would give a different
                       value for this soul. See ``ASSUMPTIONS``.

``and``/``or`` short-circuit on a definite child, so an unsupported sibling
never hides a definite False (the prototype raised on the first unknown
primitive, which inflated the unsupported count).
"""
import fnmatch
import re

from . import Unsupported

STRUCTURAL = {'selectors', 'and', 'or', 'not'}

# Every inferred semantic, with its evidence. 'evidence' cites native data;
# 'alternative' is what the evaluator also computes to flag dependence.
ASSUMPTIONS = {
    'customSelector-mode': dict(
        rule='customSelector without mode (or mode="and") is AND of its children; mode="or" is OR. '
             '<selectors> is AND.',
        evidence='storm.dtd has no mode semantics; base.xml mixes mode="and", mode="or" and no mode with '
                 'single <or> children (isCinematic), consistent only with AND by default.',
        kind='inferred'),
    'hasName-case': dict(
        rule='hasName matches soul_name with a case-insensitive, anchored glob (* and ?).',
        evidence='602 native hasName values are globs (e.g. kkut_*); 8edd58f trade fix in game is consistent '
                 'with matching soul_name. Case-insensitivity is not evidenced.',
        alternative='case-sensitive match', kind='inferred'),
    'hasVoice-character': dict(
        rule='hasVoice name=X matches voice.xml voice_technical_name, ID/id=N matches voice_id, of the '
             'voice reached by soul.skald_character_name -> skald_character.voice_id.',
        evidence='All 1041 native hasVoice names are voice_technical_name values; 1239/1239 native souls '
                 'with voice_group_name have a skald character whose voice lists that group.',
        kind='evidenced-by-data'),
    'hasVoice-no-character': dict(
        rule='A soul without skald_character_name has no voice: every hasVoice is False.',
        evidence='Native base.xml defines hasMerchantVoiceOrNoCharacter = hasMerchantVoice OR hasNoCharacter; '
                 'the OR is only needed if character-less souls fail hasMerchantVoice. The characters task '
                 '(setGenericCharacterNamePattern, assignVoiceGroup) is commented out in retail storm.xml, '
                 'so no runtime character is assigned by Storm.',
        alternative='the engine draws a voice from the soul voice_group_name (any voice if none)',
        kind='inferred'),
    'hasVoice-no-voice-id': dict(
        rule='A skald character without voice_id has no voice: every hasVoice is False.',
        evidence='14 of 1162 native skald characters have no voice_id.', kind='inferred'),
    'hasFaction-ancestor': dict(
        rule='hasFaction name=F is true when the soul faction is F or a descendant of F in FactionTree.',
        evidence='Native rules name inner nodes (kutnohorsko, trosecko) while souls carry leaf factions.',
        alternative='exact faction name', kind='inferred'),
    'factionLabel-ancestor': dict(
        rule='isPublicEnemy / hasFactionLabel read FactionTree Labels of the soul faction or an ancestor.',
        evidence='Labels="publicEnemy" is set on inner FactionTree nodes; faction_label.xml lists the labels.',
        alternative='labels of the soul faction only', kind='inferred'),
    'hasGender-archetype': dict(
        rule='hasGender name=G compares gender.xml gender_name of soul_archetype.gender_id, case-insensitively.',
        evidence='soul_archetype rows carry gender_id; gender.xml names male/female; rules use Male/Female.',
        kind='inferred'),
    'hasCharacterName-prefix': dict(
        rule='hasCharacterName is a case-insensitive glob over skald_character_name.',
        evidence='The single native use is name="GENERIC_*" while generic characters are named char_GENERIC_*.',
        alternative='the glob is matched after removing the char_ prefix', kind='inferred'),
    'missing-social-class': dict(
        rule='A soul without social_class_id fails every hasSocialClass.',
        evidence='530 native soul rows have no social_class_id.', kind='inferred'),
    'rule-order': dict(
        rule='Operations apply in storm.xml task order, then source order, then rule order; hasRole reads '
             'roles added earlier in this order.',
        evidence='characters.xml comment: "the first rule wins" for setGenericCharacterNamePattern. No evidence '
                 'for roles.', kind='inferred'),
}

FORK_PRIMITIVES = {'hasRandomValue': 'random', 'isGameMode': 'game-mode', 'isContentFilterActive': 'content-filter'}


class V:
    __slots__ = ('outs', 'deps')

    def __init__(self, outs, deps=frozenset()):
        self.outs = frozenset(outs); self.deps = frozenset(deps)

    @property
    def definite(self):
        return len(self.outs) == 1

    @property
    def value(self):
        return next(iter(self.outs)) if self.definite else None

    def status(self):
        if self.outs == {True}: return 'APPLIES'
        if self.outs == {False}: return 'NO'
        if any(d.startswith(('unsupported:', 'ambiguous:')) for d in self.deps): return 'UNSUPPORTED'
        return 'FORK'

    def __repr__(self):
        return 'V(%s,%s)' % (sorted(self.outs), sorted(self.deps))


TRUE, FALSE, BOTH = frozenset({True}), frozenset({False}), frozenset({True, False})


def fact(value, deps=()):
    return V(TRUE if value else FALSE, deps)


def sensitive(primary, alternative_outs, assumption):
    """Primary value, tagged with the assumption when the alternative semantic could differ."""
    deps = ('assume:' + assumption,) if set(alternative_outs) - {primary} else ()
    return fact(primary, deps)


_GLOBS = {}


def glob(pattern, value, case_sensitive=False):
    key = (pattern, case_sensitive)
    rx = _GLOBS.get(key)
    if rx is None:
        rx = _GLOBS[key] = re.compile(fnmatch.translate(pattern), 0 if case_sensitive else re.IGNORECASE)
    return rx.match(value) is not None


class Context:
    """Per-run state: tables, custom selectors, caches and observation hooks."""

    def __init__(self, tables, custom_selectors):
        self.tables = tables
        self.custom = custom_selectors
        self.dynamic = self._dynamic_customs()
        self.cache = {}
        self.roles = None            # current soul's role state (set by the engine)
        self.source = None           # current Source being evaluated
        self.name_hits = None        # set of (source path, pattern) when hasName is True

    def _dynamic_customs(self):
        """Custom selectors that (transitively) read hasRole cannot be cached per soul."""
        uses = {}
        for name, bodies in self.custom.items():
            tags = set()
            for _, element in bodies:
                tags |= {e.tag for e in element.iter()}
            uses[name] = tags
        dynamic, changed = {n for n, t in uses.items() if 'hasRole' in t}, True
        while changed:
            changed = False
            for n, t in uses.items():
                if n not in dynamic and t & dynamic:
                    dynamic.add(n); changed = True
        return dynamic

    def begin_soul(self, soul, roles):
        self.cache = {}
        self.roles = roles
        self.soul = soul


def evaluate(element, soul, ctx, combine='and'):
    """Evaluate the children of ``element`` combined with AND (default) or OR."""
    return _combine([c for c in element if isinstance(c.tag, str)], soul, ctx, combine)


def _combine(children, soul, ctx, mode):
    decisive = False if mode == 'and' else True
    deps, uncertain, settled = set(), False, None
    for child in children:
        v = node(child, soul, ctx)
        if v.outs == {decisive}:
            # Stop at a decisive child that rests on no assumption. A decisive
            # child that does rest on one is kept while later children are
            # checked, so the result only names an assumption when flipping it
            # could actually change the outcome.
            if not v.deps: return v
            if settled is None or len(v.deps) < len(settled.deps): settled = v
            continue
        if settled is not None: continue
        if not v.definite: uncertain = True
        deps |= v.deps
    if settled is not None: return settled
    if uncertain: return V(BOTH, deps)
    return V({not decisive}, deps)


def node(e, soul, ctx):
    tag = e.tag
    if tag in ('selectors', 'and'): return _combine(list(e), soul, ctx, 'and')
    if tag == 'or': return _combine(list(e), soul, ctx, 'or')
    if tag == 'not':
        v = _combine(list(e), soul, ctx, 'and')
        return V({not o for o in v.outs}, v.deps)
    primitive = PRIMITIVES.get(tag)
    if primitive is not None:
        try:
            return primitive(e, soul, ctx)
        except Unsupported as exc:
            return V(BOTH, {'unsupported:' + str(exc)})
    if tag in FORK_PRIMITIVES:
        return V(BOTH, {'fork:' + FORK_PRIMITIVES[tag]})
    if tag in ctx.custom:
        return custom(tag, soul, ctx)
    return V(BOTH, {'unsupported:' + tag})


def custom(name, soul, ctx):
    cacheable = name not in ctx.dynamic
    if cacheable and name in ctx.cache: return ctx.cache[name]
    ctx.cache[name] = V(BOTH, {'unsupported:recursive customSelector ' + name})  # cycle guard
    results = []
    previous = ctx.source
    for defined_in, body in ctx.custom[name]:
        ctx.source = defined_in   # hasName hits are attributed to the defining file
        results.append(_combine(list(body), soul, ctx, 'or' if (body.get('mode') or '').lower() == 'or' else 'and'))
    ctx.source = previous
    if len({r.outs for r in results}) == 1:
        v = V(results[0].outs, set().union(*(r.deps for r in results)))
    else:
        # Duplicate definitions disagree for this soul; which one the engine
        # keeps is not known.
        v = V(BOTH, set().union(*(r.deps for r in results)) | {'ambiguous:duplicate customSelector ' + name})
    if cacheable: ctx.cache[name] = v
    else: ctx.cache.pop(name, None)
    return v


# ---------------------------------------------------------------- primitives

def _attr(e, *names):
    for n in names:
        if e.get(n) is not None: return e.get(n)
    return None


def has_name(e, soul, ctx):
    pattern = _attr(e, 'name', 'Name')
    if pattern is None: raise Unsupported('hasName without name')
    primary = glob(pattern, soul.name)
    alternative = glob(pattern, soul.name, case_sensitive=True)
    if primary and ctx.name_hits is not None and ctx.source is not None:
        ctx.name_hits.add((ctx.source.path, ctx.source.layer, pattern))
    return sensitive(primary, {alternative}, 'hasName-case')


def has_voice(e, soul, ctx):
    name, voice_id = e.get('name'), _attr(e, 'ID', 'id')
    if name is None and voice_id is None: raise Unsupported('hasVoice without name or ID')

    def match(v):
        return (name is not None and v.get('voice_technical_name') == name) or \
               (voice_id is not None and v.get('voice_id') == voice_id)
    status, voice = ctx.tables.voice_of(soul)
    if status == 'ok': return fact(match(voice))
    if status == 'no-character':
        candidates = ctx.tables.group_voices(soul.get('voice_group_name'))
        return sensitive(False, {match(v) for v in candidates} or {False}, 'hasVoice-no-character')
    if status == 'no-voice': return fact(False, ('assume:hasVoice-no-voice-id',))
    raise Unsupported('hasVoice: ' + status + ' ' + str(soul.get('skald_character_name')))


def has_a_character(e, soul, ctx):
    return fact(bool(soul.get('skald_character_name')))


def has_character_name(e, soul, ctx):
    pattern = e.get('name')
    if pattern is None: raise Unsupported('hasCharacterName without name')
    character = soul.get('skald_character_name') or ''
    primary = bool(character) and glob(pattern, character)
    stripped = character[5:] if character.lower().startswith('char_') else character
    alternative = bool(character) and glob(pattern, stripped)
    return sensitive(primary, {alternative}, 'hasCharacterName-prefix')


def has_social_class(e, soul, ctx):
    wanted = e.get('name')
    sid = soul.get('social_class_id')
    if sid is None: return fact(False, ('assume:missing-social-class',))
    name = ctx.tables.social_classes.get(sid)
    if name is None: raise Unsupported('hasSocialClass: unknown social_class_id ' + sid)
    return fact(name == wanted)


def has_soul_archetype(e, soul, ctx):
    row = ctx.tables.archetypes.get(soul.get('soul_archetype_id'))
    if row is None: raise Unsupported('hasSoulArchetype: unknown soul_archetype_id ' + str(soul.get('soul_archetype_id')))
    return fact(row.get('soul_archetype_name') == e.get('name'))


def has_gender(e, soul, ctx):
    row = ctx.tables.archetypes.get(soul.get('soul_archetype_id'))
    gender = ctx.tables.genders.get((row or {}).get('gender_id'))
    if gender is None: raise Unsupported('hasGender: no archetype gender')
    return fact(gender.lower() == (e.get('name') or '').lower(), ('assume:hasGender-archetype',))


def has_faction(e, soul, ctx):
    wanted, own = e.get('name'), soul.get('factionName')
    chain = ctx.tables.faction_chain(own)
    return sensitive(wanted in chain, {wanted == own}, 'hasFaction-ancestor')


def _labels(soul, ctx):
    chain = ctx.tables.faction_chain(soul.get('factionName'))
    every = set().union(*(ctx.tables.factions.get(f, {}).get('labels', set()) for f in chain)) if chain else set()
    own = ctx.tables.factions.get(soul.get('factionName'), {}).get('labels', set())
    return every, own


def has_faction_label(e, soul, ctx):
    every, own = _labels(soul, ctx)
    label = e.get('name')
    return sensitive(label in every, {label in own}, 'factionLabel-ancestor')


def is_public_enemy(e, soul, ctx):
    every, own = _labels(soul, ctx)
    return sensitive('publicEnemy' in every, {'publicEnemy' in own}, 'factionLabel-ancestor')


def has_combat_level(e, soul, ctx):
    level = soul.get('combat_level')
    if level is None: raise Unsupported('hasCombatLevel: soul has no combat_level')
    level = float(level)
    lo, hi = e.get('minValue'), e.get('maxValue')
    return fact((lo is None or level >= float(lo)) and (hi is None or level <= float(hi)))


def has_role(e, soul, ctx):
    if ctx.roles is None: raise Unsupported('hasRole outside the roles task')
    state = ctx.roles.get(e.get('name'))
    if state is None: return fact(False, ('assume:rule-order',))
    if state.definite: return fact(True, ('assume:rule-order',))
    return V(BOTH, set(state.deps) | {'assume:rule-order'})


PRIMITIVES = {
    'hasName': has_name, 'hasVoice': has_voice, 'hasACharacter': has_a_character,
    'hasCharacterName': has_character_name, 'hasSocialClass': has_social_class,
    'hasSoulArchetype': has_soul_archetype, 'hasGender': has_gender, 'hasFaction': has_faction,
    'hasFactionLabel': has_faction_label, 'isPublicEnemy': is_public_enemy,
    'hasCombatLevel': has_combat_level, 'hasRole': has_role,
    # hasAttribute (soul stats/skills) is deliberately absent: UNSUPPORTED.
}
