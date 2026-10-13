"""Upgrade bounded source RPG calls; never pass arbitrary legacy Lua through."""
import re
from decimal import Decimal

from campaign_quest_bridge import UnsupportedOperation
from campaign_scene import STATS


def upgrade(script):
    # Shipped KCD2 Scripts/CommandExecutor/snapshots.xml calls SetState on
    # player.soul for hunger and exhaust. The native sesivaniTonici fight
    # helper also uses soul:SetState('health', ...). Keep this synchronous
    # at the original ExecuteLua site: it must not escape loading/quest gates.
    setter = r"player\.soul:SetState\(\s*(['\"])(hunger|exhaust|health)\1\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\)"
    states = re.findall(setter, script)
    remainder = re.sub(setter, '', script)
    if states and not remainder.strip(' \t\r\n;'):
        calls = []
        for _, state, raw in states:
            value = Decimal(raw)
            if not 0 <= value <= 100:
                raise UnsupportedOperation('RPG state value outside the validated percentage range')
            calls.append("player.soul:SetState('" + state + "', " + format(value, 'f') + ')')
        return '; '.join(calls)
    # Native AI/quests/zachrana/zachrana.xml uses this same getter/advance
    # protocol. KCD2's RPG stat names replace the source abbreviations.
    increment = re.fullmatch(
        r"\s*local\s+([A-Za-z_]\w*)\s*=\s*player\.soul:GetStatLevel\(\s*(['\"])([a-z]+)\2\s*\)\s*;\s*"
        r"player\.soul:AdvanceToStatLevel\(\s*(['\"])\3\4\s*,\s*\1\s*\+\s*(\d+)\s*\)\s*;?\s*", script)
    if increment:
        old, amount = increment[3], int(increment[5])
        if old not in STATS or amount <= 0:
            raise UnsupportedOperation('Unknown stat or nonpositive stat advancement')
        stat = STATS[old]
        return "local value = player.soul:GetStatLevel('" + stat + "'); player.soul:AdvanceToStatLevel('" + stat + "', value + " + str(amount) + ')'
    calls = re.findall(r"player\.soul:AdvanceToStatLevel\(\s*(['\"])([a-z]+)\1\s*,\s*(\d+)\s*\)", script)
    remainder = re.sub(r"player\.soul:AdvanceToStatLevel\(\s*(['\"])([a-z]+)\1\s*,\s*(\d+)\s*\)", '', script)
    if calls and not remainder.strip(' \t\r\n;'):
        if any(stat not in STATS for _, stat, _ in calls):
            raise UnsupportedOperation('Unknown stat in source advancement')
        return '; '.join("player.soul:AdvanceToStatLevel('" + STATS[stat] + "', " + str(int(value)) + ')'
                         for _, stat, value in calls)
    raise UnsupportedOperation('Source Lua requires a semantic adapter')
