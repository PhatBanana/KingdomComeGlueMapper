# Recipe archive capacity

The clean setup build could create `Data/gluemappertravel.pak` successfully,
then fail while adding Neuhof services. The observed archive was 2,312,130,875
bytes, with 3,962 entries and its central directory at offset 2,311,679,571.
The travel builder permits ZIP64, but `build_horse_trader_test.rewrite`, shared
by subsequent recipe stages, explicitly disabled it. Python's ZIP64 threshold
is approximately 2 GiB. Closing the failed rewrite also raised a central-directory
offset error, masking the initial write error in the setup summary.

The shared writer now permits ZIP64, matching the original builder and package
upgrader. Small archives remain ordinary ZIPs. Actor-material migration also
uses this writer instead of its own ZIP64-disabled travel rewrite. Asset shard
size policies are unchanged.

Regression tests lower Python's limits to exercise large members, central
directory offsets, growing entry counts and actor-material migration. They
check preserved content and CRCs, and confirm ordinary archives remain ordinary.
The actual failing package was used to rerun the Neuhof stage successfully,
staging ten horses into a separate output directory. No game installation was
modified. This validates packaging, not in-game horse behavior or a complete
fresh setup run.
