# v0.1 validation scope

Release snapshot: development addon v0.23.28, published as StageLab v0.1.0.

## Observed in UNI2

The local user tested BG001 exports in game: vertex-position changes, placement
movement, and then rotation/scale visibly loaded. These are concrete fixtures,
not proof that every possible edit or every stage has been tested in game.

## Automated local checks

- All 29 extracted stage files passed multi-mesh binary position round trips.
- All 29 passed native affine world-matrix comparisons at sampled playback phases.
- BG001/BG004/BG020 passed combined vertex + rotation/nonuniform-scale export and
  full reimport at multiple independent-loop boundaries, including nested controls.
- A synthetic changing-shear hierarchy passed 600 frames, save/reopen and reset;
  maximum observed world-matrix element error was approximately 4.77e-7.
- BG001/BG004/BG020/BG024 passed GPU smoke tests switching locked/free/locked.
- Temporary-file tests cover overwrite backups, unchanged repeated saves, exact
  source protection and cleanup of staged temporary files.

Float32 matrix multiplication is not bit-identical between all equivalent
factorizations. Matrix checks use declared numeric tolerances; unchanged binary
re-exports and untouched source fields use byte-identity checks.

## Reproducible tests shipped here

The `tests/` fixtures generate their own tiny binary scenes. They need Blender,
but no game assets or machine-specific stage paths. They are a focused safety
suite, not replacements for proprietary-asset regression or GPU/manual tests.

The public repository intentionally excludes raw game captures, binaries and
the private research database. Do not interpret missing public captures as a
claim of independently reproducible in-game coverage.
