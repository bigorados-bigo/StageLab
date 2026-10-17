"""Profile-scoped FPAN render semantics used by preview backends.

This module is Blender-independent so the contract can be regression-tested
before any viewport or RenderEngine integration is allowed to consume it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrawState:
    rgb_source: str
    rgb_destination: str
    alpha_source: str = "SRC_ALPHA"
    alpha_destination: str = "ONE"
    alpha_test: str = "GREATER"
    alpha_reference: int = 0
    depth_test: str = "LESS_EQUAL"
    depth_write: bool = True
    cull: str = "CW"


def uni2_draw_state(compiled_blend_mode: int) -> DrawState:
    """Return the native state observed for the UNI2 FPAN blend classes."""
    return DrawState(
        rgb_source="SRC_ALPHA",
        rgb_destination="ONE" if compiled_blend_mode > 0 else "INV_SRC_ALPHA",
    )


def alpha_test_passes(state: DrawState, source_alpha_8bit: int) -> bool:
    if state.alpha_test == "GREATER":
        return source_alpha_8bit > state.alpha_reference
    raise ValueError(f"unsupported alpha test: {state.alpha_test}")


def draw_pixel(state: DrawState, source, destination, source_depth, destination_depth):
    """Reference one-pixel D3D9 draw; returns (rgba, depth, drawn)."""
    source_alpha_8bit = max(0, min(255, round(float(source[3]) * 255.0)))
    if not alpha_test_passes(state, source_alpha_8bit):
        return tuple(destination), destination_depth, False
    if state.depth_test != "LESS_EQUAL":
        raise ValueError(f"unsupported depth test: {state.depth_test}")
    if source_depth > destination_depth:
        return tuple(destination), destination_depth, False

    source_alpha = float(source[3])
    destination_rgb_factor = 1.0 if state.rgb_destination == "ONE" else 1.0 - source_alpha
    rgb = tuple(
        min(1.0, float(source[channel]) * source_alpha + float(destination[channel]) * destination_rgb_factor)
        for channel in range(3)
    )
    # Captures use separate alpha SRC_ALPHA/ONE for both RGB blend classes.
    alpha = min(1.0, source_alpha * source_alpha + float(destination[3]))
    depth = source_depth if state.depth_write else destination_depth
    return rgb + (alpha,), depth, True
