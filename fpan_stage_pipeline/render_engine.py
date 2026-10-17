"""Blender RenderEngine integration for the captured UNI2 FPAN draw contract."""

from __future__ import annotations

import bpy

from . import viewport


ENGINE_ID = "FPAN_NATIVE"


class FPANNativeRenderEngine(bpy.types.RenderEngine):
    bl_idname = ENGINE_ID
    bl_label = "FPAN Native Preview"
    bl_use_preview = False
    bl_use_gpu_context = True
    bl_use_postprocess = True

    def __del__(self):
        for name in ('_fpan_bloom_target',):
            cached = getattr(self, name, None)
            if cached is not None:
                try:
                    cached[-1].free()
                except (ReferenceError, RuntimeError):
                    pass

    def view_update(self, context, depsgraph):
        viewport.invalidate_updated_geometry(depsgraph)

    def view_draw(self, context, depsgraph):
        viewport.draw_render_engine(self, context, depsgraph)

    def update(self, data, depsgraph):
        pass

    def render(self, depsgraph):
        self.report({"WARNING"}, "FPAN Native Preview currently supports the interactive viewport only")


def set_enabled(scene, enabled):
    if enabled:
        if "fpan_previous_color_view" not in scene:
            scene["fpan_previous_color_view"] = scene.view_settings.view_transform
            scene["fpan_previous_color_look"] = scene.view_settings.look
            scene["fpan_previous_color_exposure"] = scene.view_settings.exposure
            scene["fpan_previous_color_gamma"] = scene.view_settings.gamma
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        if scene.render.engine != ENGINE_ID:
            scene["fpan_previous_render_engine"] = scene.render.engine
            scene.render.engine = ENGINE_ID
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.type = "RENDERED"
                area.tag_redraw()
    elif scene.render.engine == ENGINE_ID:
        previous = scene.get("fpan_previous_render_engine", "BLENDER_EEVEE")
        try:
            scene.render.engine = previous
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE"
        if "fpan_previous_color_view" in scene:
            scene.view_settings.view_transform = scene["fpan_previous_color_view"]
            scene.view_settings.look = scene.get("fpan_previous_color_look", 'None')
            scene.view_settings.exposure = scene.get("fpan_previous_color_exposure", 0.0)
            scene.view_settings.gamma = scene.get("fpan_previous_color_gamma", 1.0)
            for key in ('view', 'look', 'exposure', 'gamma'):
                del scene['fpan_previous_color_' + key]


CLASSES = (FPANNativeRenderEngine,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for scene in bpy.data.scenes:
        if scene.render.engine == ENGINE_ID:
            set_enabled(scene, False)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
