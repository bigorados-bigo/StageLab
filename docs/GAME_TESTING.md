# In-game testing

Export does not install a mod or modify packed archives. Keep backups and test
offline. Close the game before replacing any live asset.

For the tested UNI2 build, the loose path for BG001 was:

```text
<game folder>/bg/bg001/bg.fbx.bin
```

**Copying there alone was not sufficient.** Packed references took precedence.
The accepted local test narrowly dereferenced only that asset's filename in its
archive index, leaving all other references intact. An older pattern-based
runtime bypass broke character selection on the tested executable and was not
used. Do not blindly restore old loaders or dummy entire archives.

This release deliberately does not automate archive changes. Determine the
loading procedure for your exact game build, back up the original index/loose
file and verify the target before modifying it. Useful background:
[UNI2 modding guide](https://github.com/Fatih120/undernightinbirth#dereferencing-for-edits).

Check the edited object, native looping, leaving/re-entering the stage and a
fresh game launch. Geometry changes do not move the characters' gameplay ground
line. Replacing the loose binary is separate from preserving your `.blend`.
