# StageLab v0.1.0 — public preview

First public release of StageLab: a general stage-tooling project whose first
supported adapter is UNI2 FPAN in Blender5.0.

Download **StageLab-v0.1.0.zip**, install it through Blender's Add-ons > Install
from Disk, enable StageLab, and open the FPAN Stage sidebar. The GitHub source
archive is for development; the named addon ZIP is the installable artifact.

Includes compiled-stage import, native-look locked/free preview, supported PAT
effects, existing-vertex editing, placement G/R/S and one combined compiled
export workflow. The exporter retains independent native animation cycles.

Please read the README's boundaries before editing. No game assets, extractor,
mod loader or archive modifications are included. Other games/formats, topology
authoring and Blender-authored animation export are future work.

Tested locally on Windows/Blender5.0.1. BG001 vertex/placement/R/S exports were
confirmed in game by the user; broader cross-stage and affine checks are
automated local tests, not a promise of complete game-accurate rendering.
