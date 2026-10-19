# Merchant stock dependency conversion

Setup 0.3.8 could stop at **Build coach travel, arrivals and Rattay services**
with `Stock items need native item conversion`. The Rattay upper-gate
innkeeper's source inventory contains 30 item types. Four have no matching
native KCD2 item: lentil soup, horseradish, mash and porridge.

The failure was an ordering/dependency defect. `region_travel.build` called
`shop_resources` before the world pickup and container importers ran, without
first converting the shop's own item dependencies. The stock resolver correctly
rejected the missing definitions. Restoring source stock rows whose `default_on`
flag is false exposed this assumption; that flag is not an instruction to omit
those items from the source inventory.

Setup 0.3.9 routes source shop construction through
`region_travel_services.import_shop_resources`. It requests every stock item
from the shared `container_items`/`WorldItemAdapter` importer, then builds the
native shop preset against the completed registry. No item IDs, quantities,
replacement foods or quest-specific grants are added to the conversion code.

- Native KCD2 definitions and existing converted definitions are reused.
- Missing items bring their converted definitions, models, materials/textures
  and localization into the package. Source stock quantities are retained.
- New definitions are available to later world pickup conversion, preventing
  another definition of the same item.
- Retired native placeholders still resolve through the existing replacement
  identity mapping.
- Source merchant and tavern upgrade builders use the same dependency step;
  staged item extensions can be supplied before their archives are finalized.
- Unresolved dependencies still fail the stage. Items are never dropped to
  allow the build to continue.

The fix changes an early construction stage, not the completed-package recipe
schema. Recipe 33 remains current. An incomplete 0.3.8 world conversion can be
restarted with 0.3.9; a fresh build is also supported. This does not retrofit new
stock into an already completed merchant service or change a saved inventory.

Regression coverage in `tests/test_merchant_stock_dependencies.py` checks clean
stock construction, emitted assets and localization, existing/staged definition
reuse, placeholder identity replacement and failures for incomplete output.
Build/package validation is distinct from an in-game merchant purchase test.
