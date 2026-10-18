# Native world speech audio relocation

Recipe 21 repairs native nearby speech after its gameplay graph is instantiated
below the imported Level. The level contributes a voice namespace by default:
`dialog/open_world/...` becomes `dialog/kcd1_travel/open_world/...`. Text IDs still
resolve without the recordings, producing subtitles and missing-wave log errors.

`world_speech_audio.upgrade` follows the packaged dependency closure, collects
response IDs, derives the wrapper scope through the instantiated graph, and
copies matching recordings from the selected game's English banks. Internal
native graph scopes remain unchanged. All available voices are retained, not
just the NPCs used in one quest. Native filenames, payload bytes, and the existing
dubbing index are preserved. Missing index entries and conflicting source banks
fail the upgrade. Archive replacement is atomic and an unchanged repeat does not
rewrite it.

The shared package finalizer runs this for both clean setup and saved-build
upgrades. Retail and Mod Tools each use their own installed recording banks.
The original game archives and unrelated imported dialogue are untouched.

## Reference audit

The installed Mod Tools package was checked on 18 October 2026:

- Both `open_world` Definition paths resolve to packaged graphs.
- 423 native dependency graphs pass lexical scope validation.
- The `kcd1_travel` module link, land punishment service link and `openworld`
  asset link point to the same local SmartObjectHolder.
- The project-level smithing/prayer wrapper intentionally retains
  `dialog/open_world/minihry` and `dialog/open_world/perky`.
- The Level-owned general gameplay wrapper uses
  `dialog/kcd1_travel/open_world` and requires the audio relocation.

`open_world` is a module/entity identity, not an obsolete level name. Replacing
that identifier with `kcd1_travel` would break the native links. The importer
changes the inherited audio location rather than renaming those identities.

Package verification establishes recording availability and byte identity.
Audible playback still requires an in-game proximity-speech test.
