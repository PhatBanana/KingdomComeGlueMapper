"""Build an opt-in NPC initialization trace; never included by setup.

The complete target-game scripts are retained. Wrappers call the native
functions directly (no protected call around gameplay), preserving errors,
yields, arguments and all return values. Only logging is protected.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from upgrade_map import read


MARKER = b"-- GlueMapperNpcInitTrace diagnostic v1"
SCRIPTS = {
    "Scripts/Entities/actor/BasicActor.lua": (
        "BasicActor",
        ("OnSpawn", "InitialSetup", "Reset", "SetActorModel", "ReviveInEditor"),
        (),
        b"BasicActor = ActorAndParams",
    ),
    "Scripts/Entities/AI/Shared/BasicAI.lua": (
        "BasicAI",
        ("OnSpawn", "RegisterAI", "OnReset", "ResetAIParameters", "OnLoadAI"),
        ("OnInit",),
        b"function BasicAI:RegisterAI",
    ),
}

RUNTIME = r'''
-- GlueMapperNpcInitTrace diagnostic v1
if not GlueMapperNpcInitTrace then
    GlueMapperNpcInitTrace = {}
    local trace = GlueMapperNpcInitTrace
    local selected = __SELECTED__
    local wrapped = setmetatable({}, {__mode="k"})
    local counts = setmetatable({}, {__mode="k"})
    local serial = 0
    local unpackValues = unpack or table.unpack
    local function pack(...) return {n=select("#", ...), ...} end
    local function emit(phase, label, self, token)
        -- Logging cannot prevent native initialization, even before name/AI
        -- registration is available. No gameplay operation is protected here.
        pcall(function()
            local name = self.GetName and self:GetName() or self.name or "?"
            local hasAI = "unavailable"
            if CryAction and CryAction.HasAI then
                hasAI = tostring(CryAction.HasAI(self.id))
            end
            System.LogAlways("[GM_NPC_INIT] " .. phase .. " " .. label ..
                " call=" .. tostring(token) .. " name=" .. tostring(name) ..
                " id=" .. tostring(self.id) .. " hasAI=" .. hasAI)
        end)
    end
    local function begin(label, self)
        local ok, token = pcall(function()
            local name = self.GetName and self:GetName() or self.name
            if not selected[name] then return nil end
            local actorCounts = counts[self]
            if not actorCounts then actorCounts = {}; counts[self] = actorCounts end
            local count = actorCounts[label] or 0
            -- Bound repeated resets; never log updates or poll every frame.
            if count >= 4 then return nil end
            actorCounts[label] = count + 1
            serial = serial + 1
            return serial
        end)
        if ok and token then emit("enter", label, self, token); return token end
    end
    function trace.wrap(owner, name, label)
        if not owner or type(owner[name]) ~= "function" then return end
        local seen = wrapped[owner]
        if not seen then seen = {}; wrapped[owner] = seen end
        if seen[name] then return end
        local original = owner[name]
        seen[name] = true
        owner[name] = function(self, ...)
            local token = begin(label, self)
            -- Do not pcall original: preserve native failures and yield semantics.
            local result = pack(original(self, ...))
            if token then emit("exit", label, self, token) end
            return unpackValues(result, 1, result.n)
        end
    end
    pcall(function() System.LogAlways("[GM_NPC_INIT] trace loaded") end)
end
'''


def patch(blob, virtual, names):
    """Append trace after native class construction, before NPC table.Merge."""
    if MARKER in blob:
        raise ValueError("Initialization trace already present: " + virtual)
    owner, methods, server, required = SCRIPTS[virtual]
    # Whitespace varies between native script distributions.
    if re.sub(rb"\s+", b"", required) not in re.sub(rb"\s+", b"", blob):
        raise ValueError("Expected complete native lifecycle script: " + virtual)
    names = sorted(set(names))
    if not names or any(not re.fullmatch(r"[A-Za-z0-9_]+", n) for n in names):
        raise ValueError("Choose explicit NPC names using letters, digits and underscores")
    selection = "{" + ",".join('["' + n + '"]=true' for n in names) + "}"
    hook = RUNTIME.replace("__SELECTED__", selection)
    for method in methods:
        hook += f'\nGlueMapperNpcInitTrace.wrap({owner}, "{method}", "{owner}.{method}")'
    for method in server:
        hook += f'\nGlueMapperNpcInitTrace.wrap({owner}.Server, "{method}", "{owner}.Server.{method}")'
    hook += f'\npcall(function() System.LogAlways("[GM_NPC_INIT] wrapped {owner}") end)\n'
    return blob + hook.encode("utf-8")


def build(game, output, names):
    """Stage two script overrides and an exact-source manifest for a bounded test."""
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a fresh trace output directory")
    files, sources = {}, {}
    with zipfile.ZipFile(Path(game) / "Data/Scripts.pak") as archive:
        index = {n.lower(): n for n in archive.namelist()}
        for virtual in SCRIPTS:
            blob = read(archive, index[virtual.lower()])
            sources[virtual] = hashlib.sha256(blob).hexdigest()
            files[virtual] = patch(blob, virtual, names)
    output.mkdir(parents=True)
    pak = output / "gluemapper_npc_init_trace.pak"
    with zipfile.ZipFile(pak, "w", compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False) as archive:
        for name, blob in sorted(files.items()):
            archive.writestr(name, blob)
    report = dict(diagnostic_only=True, names=sorted(set(names)),
                  sources=sources, archive_sha256=hashlib.sha256(pak.read_bytes()).hexdigest(),
                  policy="Log native lifecycle entry/exit; no AI, LOD or scheduling changes")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--names", nargs="+", required=True)
    print(json.dumps(build(**vars(parser.parse_args())), indent=2))
