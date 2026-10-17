# StageLab

Stage import, native-look preview, editing and export tools.

**v0.1 targets UNDER NIGHT IN-BIRTH II Sys:Celes FPAN stages in Blender 5.0.**
Other games and interchange formats are a future direction, not supported
features. This is an early preview release, not a claim of complete engine
emulation or arbitrary scene export.

## Install

1. Download `StageLab-v0.1.0.zip` from [Releases](https://github.com/bigorados-bigo/StageLab/releases).
2. In Blender: **Edit > Preferences > Add-ons > menu > Install from Disk**.
3. Select the ZIP and enable **StageLab**. Restart Blender when updating.
4. Open the 3D View sidebar (`N`), then the **FPAN Stage** tab.

No pip packages, external DLLs, or mod loader are bundled or required for the
Blender addon. Testing has been on Windows with Blender 5.0.1/OpenGL; other
platforms and GPU backends are not validated.

## Import and preview

Use your own extracted game assets. Select a stage's `bg.fbx.bin` using
**Import FPAN Stage**. Keep its textures and supporting files alongside it;
keep the original extracted `bg/BgList.txt` hierarchy for stage camera, timing,
fog and composition metadata. A standalone binary does not contain all of that
context. Game assets and an unpacker are not included.

Enable **Native D3D9 viewport** for the custom native-look preview. This name
describes the emulated draw contract: it is a Blender GPU renderer, not a D3D9
DLL. Choose **Locked gameplay** or **Flyable native look**. Free flight uses
Blender navigation and higher-precision depth; locked mode retains the recovered
game depth contract. Fog/postprocessing toggles are available.

## Edit and export

- **Vertex edits:** turn Placement editing off, select the mesh, and use Edit
  Mode (`Tab`) to move existing vertices. Do not add/delete vertices or faces.
- **Object placement:** in Object Mode, enable **Placement editing** and use
  `G`, `R`, `S`. This controls a saved parent offset without replacing native
  animation. Pick another imported object to switch targets. Directly moving
  the animation-owned object outside this workflow may snap back on playback.
- Return to Object Mode and use **Export Edited Stage Copy**. It includes all
  supported vertex and placement edits, not just the current selection.
- Existing destinations use Blender's overwrite confirmation. Before replacement,
  previous bytes are retained as `filename.<hash>.bak`. The exact imported source
  remains protected so binary-backed playback and repeated export keep a stable
  baseline. Save elsewhere and reimport to establish a new baseline.
- Save your `.blend` too: it preserves the editable session and controls.

Output is FPAN's compiled **FbxExp `.fbx.bin`**, not Autodesk FBX. Native sample
counts and independent animation cycles are retained; placement transforms are
composed into the original matrices rather than baking Blender's timeline.

## v0.1 boundaries

- Vertex positions and placement translation/rotation/scale are exported,
  including nonuniform/mirrored scale and nested animated parents.
- Original normals, UVs, colors, materials, textures and PAT scripts are retained,
  **not authored/exported** by this release. Large geometry edits may need normals
  work that this exporter does not yet support.
- Topology edits, new/deleted native nodes, reparenting, Blender-authored animation,
  constraints, modifiers, shape keys, and singular/near-zero placement scale are
  unsupported and relevant structural checks block export.
- Scripted PAT preview covers decoded shipped forms; unsupported records are
  reported. It is not a general-purpose Squirrel interpreter or a promise that
  unknown future effects will work.
- Locked native image projection and Blender's ordinary overlays/picking are
  not fully aligned. Use flyable view for selection/editing when needed.
- Offline screenshot/movie rendering through the custom renderer is not yet a
  supported export workflow.

See [validation](docs/VALIDATION.md), [game testing](docs/GAME_TESTING.md), and
[maintainer notes](docs/MAINTAINER.md).

## Development

The addon lives in `fpan_stage_pipeline/`; its module name is intentionally
stable. Build a release with `python tools/build_release.py`. Run synthetic
tests with `python tools/run_tests.py --blender /path/to/blender`.

Do not commit extracted game data, executable patches, local paths/logs,
personal files or research captures. Provide minimal reproduction steps with
Blender version, stage ID, camera mode and the operation that failed.

## Credits

Maintained by Bigo. Thanks to Armonté and the French Bread modding community
for review and format/tool knowledge; WistfulHopes' FbxExp importer and
Blender-MBTL-BG-IO were useful format references. This repository does not bundle
those tools or grant rights to game assets. Not affiliated with French Bread,
Arc System Works or Blender Foundation.

## License

Licensing is undecided for this public preview. No open-source license grant
has been attached yet; public visibility should not be mistaken for a selected
redistribution license. Game assets remain outside this repository.
