"""Export the converted KCD1 scene without its single-player controllers.

This uses the static-probe layout documented by GlueMapper's upgrade_map.py,
the native SpawnPoint properties in campaign_package.py, and its 8-4-4 GUID
and v3 trigger-area layouts. It never patches native code. Rendering archives
and their payloads are left to the caller; this module handles level metadata.

The export is an experimental scene conversion, not an in-game compatibility
claim. Read ``SceneContext.report`` for exclusions and runtime limitations.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import copy
import math
import re
import struct
from typing import Any
import xml.etree.ElementTree as ET
import zipfile


LEVEL_NAME = "kcd1_travel"
LEVEL_ID = 1001
SPAWN_NAME = "gluemapper_kcdmp_spawn"
# Native entity GUID text is low32-mid16-high16, not a UUID.
SPAWN_GUID = "fdba1011-a133-65ae"

VISUAL_CLASSES = frozenset({
    "GeomEntity", "AnimChar", "Light", "EnvironmentLight", "ReflexLight",
    "ClipVolume", "FogVolume", "ParticleEffect", "AreaBox", "AreaShape",
    "AudioAreaAmbience", "AudioAreaRandom", "AudioAreaEntity",
    "AudioTriggerSpot", "WaterVolume", "WindArea", "Cloud", "CloudBlocker",
    "GeomCache", "TagPoint",
})
MODEL_BACKED_FURNISHINGS = frozenset({
    "Bed", "Chair", "Stash", "AnimObject", "AnimDoor", "RigidBodyEx",
    "Ladder", "Grindstone", "AlchemyItem", "ShootingTarget", "LedgerBook",
    "Bench", "CookingPlace", "WashingPlace",
})
_SCRIPT_NODES = frozenset({"FlowGraph", "FlowGraphs", "EventTargets", "Events",
                           "Script", "Scripts"})
_SCRIPT_ATTRIBUTES = frozenset({"Script", "ScriptFile", "ScriptName"})
_NATIVE_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}$")


@dataclass
class SceneContext:
    spawn_xyz: tuple[float, float, float]
    heading: float  # Degrees: 0 faces +Y; 90 faces -X, as KCDMP's SDK specifies.
    report: dict[str, Any]
    replacements: dict[str, bytes | None]


def _xml(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse(data: bytes, path: str, expected: str | None = None) -> ET.Element:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid scene XML {path}: {exc}") from exc
    if expected is not None and root.tag != expected:
        raise ValueError(f"Unsupported {path} root {root.tag!r}; expected {expected!r}")
    return root


def _key(path: str) -> str:
    return path.replace("\\", "/").lower()


def _initial_layer(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].removesuffix(".xml").split("{", 1)[0]
    return name.lower().endswith(("_state0", "_state0_prefabs"))


def _values(text: str, count: int, label: str) -> tuple[float, ...]:
    try:
        result = tuple(float(x) for x in text.split(","))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {label}: {text!r}") from exc
    if len(result) != count or not all(math.isfinite(x) for x in result):
        raise ValueError(f"Invalid {label}: {text!r}")
    return result


def _format(values: tuple[float, ...]) -> str:
    return ",".join(format(x, ".12g") for x in values)


def _qmul(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    w, x, y, z = a
    v, i, j, k = b
    return (w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j,
            w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v)


def _guid_key(value: str | None) -> str | None:
    if not value:
        return None
    if _NATIVE_GUID.fullmatch(value):
        low, middle, high = (int(x, 16) for x in value.split("-"))
        return str(low | middle << 32 | high << 48)
    if value.isdecimal():
        return str(int(value))
    return value.lower()


def _id_key(value: str | None) -> str | None:
    return str(int(value)) if value and value.isdecimal() else value


def _source_signature(entity: ET.Element) -> bytes:
    item = copy.deepcopy(entity)
    for key in ("Layer", "EditorLayer"):
        item.attrib.pop(key, None)
    def signature(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
                tuple(signature(child) for child in node))
    return repr(signature(item)).encode("utf-8")


def _world_transform(entity: ET.Element, ids: dict[str, ET.Element],
                     guids: dict[str, ET.Element], visiting: tuple[int, ...] = ()):
    identity = id(entity)
    if identity in visiting:
        raise ValueError("Parent cycle in scene entity transforms")
    position = _values(entity.get("Pos", "0,0,0"), 3, "entity position")
    rotation = _values(entity.get("Rotate", "1,0,0,0"), 4, "entity quaternion")
    scale = _values(entity.get("Scale", "1,1,1"), 3, "entity scale")
    length = math.sqrt(sum(x*x for x in rotation))
    if length < 1e-8:
        raise ValueError("Zero scene quaternion")
    rotation = tuple(x / length for x in rotation)
    parent_id = _id_key(entity.get("ParentId") or entity.get("Parent"))
    parent_guid = _guid_key(entity.get("ParentGuid"))
    parent = ids.get(parent_id) if parent_id not in (None, "", "0") else None
    if parent is None and parent_guid not in (None, "", "0"):
        parent = guids.get(parent_guid)
    if parent is None and (parent_id not in (None, "", "0") or parent_guid not in (None, "", "0")):
        raise ValueError(f"Unresolved visual parent for {entity.get('Name', '<unnamed>')}")
    if parent is not None:
        pp, pq, ps = _world_transform(parent, ids, guids, (*visiting, identity))
        if max(ps)-min(ps) > 1e-4 and max(abs(x) for x in rotation[1:]) > 1e-5:
            raise ValueError("Rotated child under nonuniform parent requires baked affine geometry")
        offset = _qmul(_qmul(pq, (0., *(position[i]*ps[i] for i in range(3)))),
                       (pq[0], -pq[1], -pq[2], -pq[3]))[1:]
        position = tuple(pp[i]+offset[i] for i in range(3))
        rotation = _qmul(pq, rotation)
        scale = tuple(ps[i]*scale[i] for i in range(3))
    if not all(math.isfinite(x) for x in position+rotation+scale):
        raise ValueError("Parent composition produced a nonfinite visual transform")
    return position, rotation, scale


def _remove_scripts(root: ET.Element) -> None:
    for parent in list(root.iter()):
        for key in _SCRIPT_ATTRIBUTES:
            parent.attrib.pop(key, None)
        for child in list(parent):
            if child.tag in _SCRIPT_NODES:
                parent.remove(child)


def _visual(entity: ET.Element) -> tuple[ET.Element | None, str]:
    cls = entity.get("EntityClass", "")
    if cls in VISUAL_CLASSES:
        item = copy.deepcopy(entity)
        _remove_scripts(item)
        properties = item.find("Properties")
        if properties is not None:
            properties.set("bSaved_by_game", "0")
        return item, "preserved_visual"
    if cls not in MODEL_BACKED_FURNISHINGS:
        return None, "excluded_nonvisual_class"
    properties = entity.find("Properties")
    model = entity.get("Geometry", "")
    if properties is not None:
        model = model or properties.get("object_Model", "") or properties.get("fileModel", "")
    model = model.replace("\\", "/")
    character = model.lower().endswith((".cdf", ".chr"))
    if not character and not model.lower().endswith((".cgf", ".cga")):
        return None, "excluded_furnishing_without_direct_model"
    # New minimal native visual properties cannot carry the original object's
    # quests, inventories, use actions or scheduling links into multiplayer.
    item = ET.Element("Entity", entity.attrib)
    for key in _SCRIPT_ATTRIBUTES:
        item.attrib.pop(key, None)
    item.set("EntityClass", "AnimChar" if character else "GeomEntity")
    props = ET.SubElement(item, "Properties", bSaved_by_game="0",
                          bInteractiveCollisionClass="0")
    if character:
        item.attrib.pop("Geometry", None)
        props.set("object_Model", model)
        physics = properties.find("Physics") if properties is not None else None
        if physics is not None:
            physics = copy.deepcopy(physics)
            props.append(physics)
        else:
            physics = ET.SubElement(props, "Physics")
        physics.set("bPhysicalize", "1")
        physics.set("bRigidBody", "0")
        physics.set("bPushableByPlayers", "0")
    else:
        item.set("Geometry", model)
    return item, "converted_to_inert_visual"


def _empty_table(data: bytes, path: str) -> bytes:
    original = _parse(data, path, "database")
    output = ET.Element(original.tag, original.attrib)
    for table in original:
        ET.SubElement(output, table.tag, table.attrib)
    return _xml(output)


def _clean_whdata0(data: bytes, report: dict[str, Any]) -> bytes:
    original = _parse(data, "whdata_0", "Root")
    result = ET.Element(original.tag, original.attrib)
    concepts = ET.SubElement(result, "ConceptManager")
    ET.SubElement(concepts, "ConceptPaths")
    ET.SubElement(concepts, "ConceptModules")
    ET.SubElement(concepts, "IncludeModGraphs").text = "0"
    ai = ET.SubElement(result, "AI")
    ET.SubElement(ai, "LevelPath").text = "data/levels/" + LEVEL_NAME
    previous_areas = original.find("AI/SmartAreaManager")
    if previous_areas is not None:
        manager = ET.SubElement(ai, "SmartAreaManager", previous_areas.attrib)
        ET.SubElement(manager, "SmartAreas")
    old_souls = original.find("SoulList/Souls")
    players = [] if old_souls is None else [x for x in old_souls if x.findtext("Player") == "1"]
    if len(players) > 1:
        raise ValueError("Ambiguous native player registration in converted scene")
    soul_list = original.find("SoulList")
    souls = ET.SubElement(ET.SubElement(result, "SoulList", {} if soul_list is None else soul_list.attrib),
                          "Souls", {} if old_souls is None else old_souls.attrib)
    for player in players:
        souls.append(copy.deepcopy(player))
    report["native_player_souls_retained"] = len(players)
    report["other_souls_removed"] = 0 if old_souls is None else len(old_souls)-len(players)
    report["whdata0_managers_removed"] = [c.tag for c in original
                                           if c.tag not in {"ConceptManager", "AI", "SoulList"}]
    return _xml(result)


def _empty_profiles(data: bytes, report: dict[str, Any]) -> bytes:
    original = _parse(data, "whdata_1", "Root")
    result = ET.Element(original.tag, original.attrib)
    manager = ET.SubElement(result, "GameProfileManager")
    ET.SubElement(manager, "GameProfiles")
    ET.SubElement(ET.SubElement(manager, "GameProfileGroups"), "Groups")
    report["runtime_profiles_removed"] = len(original.findall(".//GameProfile"))
    report["whdata1_managers_removed"] = [c.tag for c in original if c.tag != "GameProfileManager"]
    return _xml(result)


def _empty_trigger_areas(data: bytes) -> tuple[bytes, int]:
    # This is a verified file-format transform, not a guessed byte patch.
    if len(data) < 12:
        raise ValueError("Truncated triggerareas.fubar header")
    version, export, count = struct.unpack_from("<III", data)
    if version != 3 or not export:
        raise ValueError("Expected converted KCD2 trigger-area version 3 and nonzero export version")
    offset = 12
    seen = set()
    for _ in range(count):
        if offset + 16 > len(data):
            raise ValueError("Truncated trigger-area record")
        guid, height, points = struct.unpack_from("<QfI", data, offset)
        offset += 16
        if not guid or guid in seen or not math.isfinite(height) or height < 0 or points < 2:
            raise ValueError("Invalid trigger-area record")
        if offset+12*points > len(data):
            raise ValueError("Truncated trigger-area points")
        for index in range(points):
            if not all(math.isfinite(x) for x in struct.unpack_from("<fff", data, offset+12*index)):
                raise ValueError("Nonfinite trigger-area points")
        seen.add(guid)
        offset += 12*points
    if offset != len(data):
        raise ValueError("Unknown trailing trigger-area data")
    # AreaShape/AreaBox retain inline geometry; only gameplay TriggerArea
    # entities own these compiled records. They are excluded by this exporter.
    return struct.pack("<III", version, export, 0), count


def prepare_scene(archive: zipfile.ZipFile, *,
                  spawn: tuple[float, float, float] | None = None,
                  heading: float | None = None) -> SceneContext:
    """Read a converted level and prepare a deterministic scenery-only export.

    An explicit spawn is world XYZ. Otherwise the authored and terrain-grounded
    ``gmtravel_arrival_kcd1`` marker is required. No guessed coordinate fallback
    is used. Heading is degrees, not radians.

    Visual objects in the main mission are the input's compiled scene baseline.
    Additional *_state0 / *_state0_prefabs layers are flattened into it; other
    entity layers are emptied and audited. Existing compiled render-layer
    definitions stay intact so terrain/HLOD numeric layer references survive.
    """
    index: dict[str, str] = {}
    for entry in archive.infolist():
        if entry.is_dir():
            continue
        key = _key(entry.filename)
        if key in index:
            raise ValueError(f"Duplicate case-insensitive level entry: {key}")
        index[key] = entry.filename
    if "objects_mission0.xml" not in index:
        raise ValueError("Converted level has no objects_mission0.xml")
    main = _parse(archive.read(index["objects_mission0.xml"]), "objects_mission0.xml", "Objects")
    docs = {"objects_mission0.xml": main}
    for key in sorted(index):
        if key.startswith("layers/") and key.endswith(".xml"):
            docs[key] = _parse(archive.read(index[key]), key, "Objects")
    originals: list[tuple[str, ET.Element]] = []
    for path, doc in docs.items():
        for child in doc:
            if child.tag != "Entity":
                raise ValueError(f"Unsupported scene object element {child.tag!r} in {path}; export needs an explicit adapter")
            originals.append((path, child))
    ids: dict[str, ET.Element] = {}
    guids: dict[str, ET.Element] = {}
    # Root mission precedence matches GlueMapper's source inventory. Ignore
    # alternate-state duplicates when their layers are explicitly excluded.
    ordered = sorted(originals, key=lambda p: p[0] != "objects_mission0.xml" and not _initial_layer(p[0]))
    for path, entity in ordered:
        for mapping, identity in ((ids, _id_key(entity.get("EntityId"))), (guids, _guid_key(entity.get("EntityGuid")))):
            if not identity:
                continue
            if (identity in mapping and (path == "objects_mission0.xml" or _initial_layer(path))
                    and _source_signature(mapping[identity]) != _source_signature(entity)):
                raise ValueError(f"Conflicting scene entity identity {identity}")
            mapping.setdefault(identity, entity)
    marker = [entity for path, entity in originals if entity.get("Name") == "gmtravel_arrival_kcd1"
              and (path == "objects_mission0.xml" or _initial_layer(path))]
    unique_markers = {_source_signature(x): x for x in marker}
    marker = list(unique_markers.values())
    if spawn is None:
        if len(marker) != 1:
            raise ValueError("Expected one gmtravel_arrival_kcd1 marker; supply explicit --spawn X Y Z")
        spawn_xyz, marker_rotation, _ = _world_transform(marker[0], ids, guids)
        marker_path = next(path for path, entity in originals if _source_signature(entity) == _source_signature(marker[0]))
        spawn_source = marker_path + " / gmtravel_arrival_kcd1 (authored, terrain-grounded marker)"
    else:
        if len(spawn) != 3 or not all(math.isfinite(float(x)) for x in spawn):
            raise ValueError("Spawn must contain three finite world coordinates")
        spawn_xyz = tuple(float(x) for x in spawn)
        marker_rotation = (_world_transform(marker[0], ids, guids)[1]
                           if heading is None and len(marker) == 1 else (1., 0., 0., 0.))
        spawn_source = "explicit world coordinates"
    if heading is None:
        w, x, y, z = marker_rotation
        heading = math.degrees(math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))) % 360
    elif not math.isfinite(float(heading)):
        raise ValueError("Heading must be finite degrees")
    heading = float(heading) % 360
    reports = []
    counts: Counter = Counter()
    original_counts: Counter = Counter()
    excluded_layers = []
    output = ET.Element(main.tag, main.attrib)
    selected: list[ET.Element] = []
    seen_entities = set()
    for path, entity in originals:
        cls = entity.get("EntityClass", "")
        original_counts[cls or "<missing>"] += 1
        if path != "objects_mission0.xml" and not _initial_layer(path):
            counts["excluded_noninitial_layer"] += 1
            continue
        key = (("id", _id_key(entity.get("EntityId"))) if entity.get("EntityId")
               else ("guid", _guid_key(entity.get("EntityGuid"))) if entity.get("EntityGuid") else None)
        if key and key in seen_entities:
            counts["duplicate_layer_copy_omitted"] += 1
            continue
        if key:
            seen_entities.add(key)
        visual, action = _visual(entity)
        counts[action] += 1
        record = {"name": entity.get("Name", ""), "class": cls,
                  "entity_id": entity.get("EntityId"), "source": path, "action": action}
        if action != "preserved_visual":
            reports.append(record)
        if visual is None:
            continue
        static_id = _id_key(entity.get("EntityId"))
        if static_id and (not static_id.isdecimal() or not 0 < int(static_id) < 65534):
            raise ValueError(f"Unsupported static visual entity ID: {entity.get('EntityId')}")
        if static_id == str(0x7777) or _guid_key(entity.get("EntityGuid")) == str(0x7777):
            raise ValueError("A visual entity uses CryEngine's reserved local-player ID/GUID 0x7777")
        if static_id:
            visual.set("EntityId", static_id)
        # World-space flattening also handles a visual child of a controller
        # that is being removed. Never simply drop its parent transform.
        position, rotation, scale = _world_transform(entity, ids, guids)
        visual.set("Pos", _format(position))
        visual.set("Rotate", _format(rotation))
        visual.set("Scale", _format(scale))
        for attr in ("Parent", "ParentId", "ParentGuid", "Layer", "EditorLayer"):
            visual.attrib.pop(attr, None)
        selected.append(visual)
    for path, doc in docs.items():
        if path != "objects_mission0.xml" and not _initial_layer(path):
            excluded_layers.append({"path": path, "entities": len(doc),
                                    "reason": "not an explicit state0 visual layer"})
    kept_by_id = {x.get("EntityId"): x for x in selected if x.get("EntityId")}
    kept_by_guid = {_guid_key(x.get("EntityGuid")): x for x in selected if x.get("EntityGuid")}
    kept_ids, kept_guids = set(kept_by_id), set(kept_by_guid)
    removed_links = 0
    for visual in selected:
        links = visual.find("EntityLinks")
        if links is not None:
            for link in list(links):
                target_id, target_guid = _id_key(link.get("TargetId")), _guid_key(link.get("TargetGuid"))
                id_target, guid_target = kept_by_id.get(target_id), kept_by_guid.get(target_guid)
                # Both fields are meaningful in native links. Keeping a link
                # merely because one endpoint resolves can leave a stale GUID
                # targeting a removed quest even when its numeric ID survives.
                unresolved = ((target_id not in (None, "", "0") and id_target is None)
                              or (target_guid not in (None, "", "0") and guid_target is None))
                if unresolved or (id_target is None and guid_target is None):
                    links.remove(link)
                    removed_links += 1
                    continue
                if id_target is not None and guid_target is not None and id_target is not guid_target:
                    raise ValueError(f"Visual link has inconsistent ID/GUID targets: {link.attrib}")
                if id_target is not None:
                    link.set("TargetId", target_id)
        output.append(visual)
    used = {int(x) for x in kept_ids if x.isdecimal()}
    number = max(used, default=0)+1
    if number == 0x7777:
        number += 1
    if number >= 65534:
        raise ValueError("No available static entity ID for multiplayer SpawnPoint")
    if _guid_key(SPAWN_GUID) in kept_guids:
        raise ValueError("The dedicated multiplayer spawn GUID conflicts with source geometry")
    yaw = math.radians(heading)
    start = ET.SubElement(output, "Entity", Name=SPAWN_NAME, EntityClass="SpawnPoint",
                          EntityId=str(number), EntityGuid=SPAWN_GUID,
                          Pos=_format(spawn_xyz), Rotate=_format((math.cos(yaw/2), 0., 0., math.sin(yaw/2))),
                          PerInstanceStreamable="0")
    ET.SubElement(start, "Properties", bEnabled="1", bInitialSpawn="0", bDoVisTest="1",
                  bSaved_by_game="0", groupName="", teamName="")
    report: dict[str, Any] = {
        "schema": 1, "mode": "experimental_scenery_only", "level": LEVEL_NAME,
        "level_id": LEVEL_ID, "runtime_verified": False,
        "spawn": {"xyz": list(spawn_xyz), "heading_degrees": heading, "source": spawn_source},
        "source_entity_classes": dict(sorted(original_counts.items())),
        "actions": dict(sorted(counts.items())), "retained_visual_entities": len(selected),
        "entity_audit": reports, "excluded_entity_layers": excluded_layers,
        "pruned_entity_links": removed_links, "emptied_level_tables": [],
        "native_player_souls_retained": 0, "other_souls_removed": 0,
        "limitations": [
            "No game process was run by the exporter; custom-level local actor creation needs runtime acceptance.",
            "The source main mission is treated as its compiled visual baseline; other entity layers are initial-state only.",
            "Model-backed furnishings are inert visuals; doors, ladders, containers and other interactions are not synchronized.",
            "Nonvisual entities, campaign/profile managers, AI and level-table records are removed; native table schemas remain.",
            "Compiled terrain, HLOD, SVO, navigation and visual resources retain the input build's format and quality.",
        ],
    }
    replacements: dict[str, bytes | None] = {"objects_mission0.xml": _xml(output)}
    for path, doc in docs.items():
        if path != "objects_mission0.xml":
            # Keep names present for leveldata.xml's layer-definition contract.
            replacements[path] = _xml(ET.Element(doc.tag, doc.attrib))
    for key, name in index.items():
        if key in replacements:
            continue
        if key.startswith("tables/") and key.endswith(".xml"):
            replacements[key] = _empty_table(archive.read(name), key)
            report["emptied_level_tables"].append(key)
        elif key == "whdata_0":
            replacements[key] = _clean_whdata0(archive.read(name), report)
        elif key == "whdata_1":
            replacements[key] = _empty_profiles(archive.read(name), report)
        elif key == "triggerareas.fubar":
            replacements[key], report["compiled_gameplay_trigger_areas_removed"] = _empty_trigger_areas(archive.read(name))
        elif key == "waitinglinks.xml":
            old = _parse(archive.read(name), key, "StaticLinksInfo")
            clean = ET.Element(old.tag, old.attrib)
            ET.SubElement(clean, "WaitingLinks")
            ET.SubElement(clean, "StreamableTargets")
            replacements[key] = _xml(clean)
        elif key in {"extractedlayerentityids.xml", "smartobjecthelpersetanimations.xml"}:
            old = _parse(archive.read(name), key)
            replacements[key] = _xml(ET.Element(old.tag, old.attrib))
        elif key.startswith("mission_") and key.endswith(".xml"):
            settings = _parse(archive.read(name), key)
            _remove_scripts(settings)
            environment = settings.find("Environment/EnvState")
            if environment is None:
                raise ValueError(f"Missing native Environment/EnvState in {key}")
            environment.set("UseLayersActivation", "0")
            replacements[key] = _xml(settings)
        elif key in {"leveldata.xml", "leveldataaction.xml"}:
            metadata = _parse(archive.read(name), key)
            _remove_scripts(metadata)
            tokens = metadata.find("GameTokensLibraryReferences")
            if tokens is not None:
                for child in list(tokens):
                    tokens.remove(child)
            replacements[key] = _xml(metadata)
        elif (key.endswith((".lua", ".luac")) or key.startswith(("scripts/", "quests/"))
              or re.fullmatch(r"whdata_\d+", key)
              or re.fullmatch(r"objects_mission[1-9]\d*\.xml", key)):
            replacements[key] = None
    report["emptied_level_tables"].sort()
    report["omitted_level_entries"] = sorted(k for k, v in replacements.items() if v is None)
    if not report["native_player_souls_retained"]:
        report["limitations"].append("The source has no native player SoulList record; this exporter does not invent one.")
    return SceneContext(tuple(spawn_xyz), heading, report, replacements)


def transform_level_entry(name: str, data: bytes, context: SceneContext) -> bytes | None:
    """Return the prepared replacement, None for an omitted entry, or original bytes."""
    return context.replacements.get(_key(name), data)
