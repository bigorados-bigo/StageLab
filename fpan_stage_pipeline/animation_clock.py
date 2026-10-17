"""BgList-owned sample spacing, independent of stage identity."""
import math


def sample_spacing(settings):
    mode = int(settings.get('fpan_bglist_InterpolationType', 0))
    if mode == 0:
        return 1
    if mode == 1:
        return 2
    if mode == 2:
        value = float(settings.get('fpan_bglist_InterpolationNum', 0))
        if math.isfinite(value) and value >= 1 and value.is_integer():
            return int(value)
    raise ValueError('Unsupported or invalid BgList matrix interpolation settings')


def sample_phase(frame, spacing, count, loop=True):
    position = max(0.0, float(frame)) / spacing
    if loop:
        position %= count
    else:
        position = min(position, count - 1)
    index = int(position)
    following = (index + 1) % count if loop else min(index + 1, count - 1)
    return index, following, position - index


def affine_mix(first, second, fraction):
    # Interpolate stored matrix coefficients without destroying affine shear.
    # Exact native in-between coefficients still require a synchronized trace.
    return type(first)(tuple(tuple(a + (b-a)*fraction for a,b in zip(row_a,row_b))
                             for row_a,row_b in zip(first,second)))
