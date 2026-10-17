"""Resolve compiler texture references to shipped stage assets."""

import pathlib


def resolve_texture_path(stage, reference):
    """Retain exact assets; allow authored image suffixes to resolve to DDS.

    FbxExp can retain e.g. ``name.png`` while the game ships ``name.dds``.
    The alias is a source-format rule and never depends on a stage identifier.
    """
    stage = pathlib.Path(stage)
    if not str(reference).strip():
        return None
    name = pathlib.Path(str(reference).replace('\\', '/')).name
    exact = stage / name
    if exact.is_file():
        return exact
    wanted = pathlib.Path(name).with_suffix('.dds').name.casefold()
    matches = [path for path in stage.iterdir() if path.is_file() and path.name.casefold() == wanted]
    if len(matches) == 1:
        return matches[0]
    return None
