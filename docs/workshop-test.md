# Workshop and church interaction test

Installed build receipt: `outputs/WorkshopPrayer03/report.json`. Previous
packages and the failed smithing session log are retained in that directory.

On 2026-10-16 the user reported "it worked" after testing this installed build
and requested commit/push. This is user acceptance of the latest test build;
the specific successful interaction and diagnostic readings were not supplied.
It does not establish the cause of the earlier smithing failures or verify every
church location. The smithing debug display remains enabled on station use.

The upper Rattay smithy has an unlocked, legal supply chest at
2673.6,660.0,99.6947, on the approach side away from the station's animation
positions. It clones the existing debug chest and reuses its installed assets.
The new preset contains all 36 native smithing recipe documents and ingredients
for ten of each of the 61 native non-autotest recipes: 87 item types, 3106 units.
The 25 recipes without documents still require their native quest/perk unlocks;
this chest does not bypass DLC, skill or quest requirements.

Four prayer pairs now use the previously staged altar positions. All six church
triggers have an empty required-perk field, allowing ordinary church prayer.
The native prayer behavior explicitly supports basicTheology=0 as well as 1;
the player is not granted a perk. Existing kneeling links, scheduler and matching
animation transforms are preserved. Remaining two sites use authored points.

The native Smithery OnUsed script is preserved with a small prefix for this
mod's Rattay stations: enable wh_pl_BlacksmithDebugDraw and log the current
quality-loss, completion-gain, cold threshold, cannot-break and heat-loss CVars.
Only the debug-draw CVar is changed; gameplay values remain untouched. This
exposes native completion, quality, temperature and stroke diagnostics for a
controlled follow-up. Disable manually with wh_pl_BlacksmithDebugDraw 0.

The latest failed attempt no longer logged missing coal or short_sword1
material errors. It still emitted cold, half-finished, ineffective, almost-broken
and broken warnings. The user confirmed reheating works. The damage cause is
not established; this build does not claim to repair that failure. One
ineffective-strike warning was suppressed because a half-finished dialogue was
already playing at the same priority. Missing sound controls remain unresolved.

Structural checks cover exact preset counts, unique IDs/GUIDs, preservation of
all unrelated entities, six ungated prayer triggers and matched animation poses.
The diagnostic build's level package matches the validated pre-diagnostic build
byte for byte, and its only additional entry is the instrumented native script.
In-game chest clearance, Pray prompt and successful crafting remain unverified.
