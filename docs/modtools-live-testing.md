# Public Modding Tools live testing

The public SDK may be older than retail KCD2. Its mod loader checks
`mod.manifest` separately from the save-version check. A save compatibility
override alone does not enable a retail-version mod.

Create an SDK-only view before launching the SDK, using the verified installed
retail mod as the source:

```powershell
.venv/Scripts/python.exe tools/prepare_modtools_mod.py --sdk "D:/SteamLibrary/steamapps/common/KCD2Mod" --source "D:/SteamLibrary/steamapps/common/KingdomComeDeliverance2/Mods/kingdomcomegluemapper"
```

The helper reads the SDK version from its `system.cfg`, writes a private
manifest, and links the mod's Data and Localization directories. It can migrate
a whole-mod junction to this layout without writing through to retail. It
rejects an unrelated SDK mod directory. It does not copy an installation
receipt or claim that the package is compatible with the older engine.

For a fresh opening test, launch in a 1280x720 window and choose New Game:

```powershell
./tools/launch_modtools_save.ps1 -GameRoot "D:/SteamLibrary/steamapps/common/KCD2Mod" -FreezePlayline
```

This does not load an existing save or apply a save-version override. For a
separate saved-game compatibility test:

```powershell
./tools/launch_modtools_save.ps1 -GameRoot "D:/SteamLibrary/steamapps/common/KCD2Mod" -SaveName autosave881.whs -CompatibilityVersion 10505 -FreezePlayline
```

Use the actual save filename and the SDK's version encoded as required by the
native compatibility CVar. The override is explicit and applies only to this
process. `-FreezePlayline` prevents saving during a read-only audit; omit it only
when testing features such as native region travel that require a save. The
launcher keeps playline deletion disabled in either case.

Verify the SDK's `kcd.log` reports the mod enabled and its packages mounted, then
verify the converted level on screen. A running process or a standard SDK menu
does not prove the mod loaded. SDK observations remain separate from retail
runtime validation.
