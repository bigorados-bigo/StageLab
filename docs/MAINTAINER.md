# Maintainer review map

Scope: general stage tooling with a UNI2-specific format/render adapter. No
MBAACC custom gameplay ABI or Gonptechan/CCCaster/ETM changes are bundled.

Start here:

| Area | Source |
| --- | --- |
| Binary model reader/writer | `fpan_binary.py` |
| Import, clock and compiled playback | `core.py`, `animation_clock.py` |
| Full affine preservation in Blender | `affine_transform.py` |
| Standard Blender placement controls | `placement.py`, `placement_session.py` |
| Unified vertex + placement export | `placement_export.py`, `geometry_export.py` |
| Overwrite/backup boundary | `export_output.py` |
| GPU preview and composition | `render_engine.py`, `viewport.py`, `postprocess.py` |
| PAT parsing/animation/packets | `pat_*.py`, `stage_components.py` |

Paths above are inside `fpan_stage_pipeline/`.

## Important contracts

Native tracks contain complete local matrices and own independent cycles. One
sample is still authoritative; it is not an absent track. Do not infer a bind
delta or synchronize every node to the longest track.

Blender Object basis is TRS-only. To retain native shear, playback uses a
frame-owned parent-inverse correction `K = native_local * inverse(TRS_basis)`.
The placement-owned parent prefix stays separate. This avoids accumulating a
correction or moving its ownership into the user's placement control.

A placement control with current matrix C and saved rest pivot R exports the
constant delta `D = C * inverse(R)`. Premultiply each ORIGINAL bind/sample by D;
never repeatedly bake the last exported output into the same source scene.

Export validates a private document before writing, retains original source
identity, and protects the exact imported baseline. Destination overwrite is
backed up and staged before replacement. Unsupported authoring should fail
clearly, not silently normalize unknown records.

Stage-specific fixture IDs are appropriate in tests, not importer/renderer
branches. Unknown formats should produce useful diagnostics rather than guessed
semantics. Future adapters should reuse the scene/editing contracts instead of
hard-coding another game's asset paths into this addon.
