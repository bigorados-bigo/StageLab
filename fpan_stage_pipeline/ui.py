import bpy

from . import viewport, placement


def _inspector_target(context):
    settings=context.scene.fpan_stage
    if settings.placement_editing and settings.placement_target is not None:
        return placement.target_for_object(settings.placement_target)
    return placement.target_for_object(context.active_object)


class FPAN_PT_stage_pipeline(bpy.types.Panel):
    bl_label = "FPAN Stage Pipeline"
    bl_idname = "FPAN_PT_stage_pipeline"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "FPAN Stage"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fpan_stage
        layout.prop(settings, "profile")
        layout.prop(settings, "clear_scene")
        layout.operator("fpan.import_stage", icon="IMPORT")
        layout.prop(settings, "animation_preview_mode")
        layout.prop(settings, "exact_additive_viewport")
        layout.prop(settings, "native_camera_mode")
        layout.prop(settings, "stage_postprocess")
        layout.prop(settings, "scripted_effects")
        if settings.native_camera_mode == "FREE":
            layout.prop(settings, "free_camera_fog")
            layout.prop(settings, "free_camera_additive_depth_compatibility")
        if settings.native_camera_mode == "LOCKED":
            layout.prop(settings, "locked_camera_fog")
            layout.prop(settings, "gameplay_camera_x")
            layout.prop(settings, "gameplay_camera_y")
            layout.prop(settings, "gameplay_camera_zoom")
            layout.prop(settings, "gameplay_camera_step")
            row = layout.row(align=True)
            left = row.operator("fpan.nudge_gameplay_camera", text="Left")
            left.direction = "LEFT"
            up = row.operator("fpan.nudge_gameplay_camera", text="Up")
            up.direction = "UP"
            down = row.operator("fpan.nudge_gameplay_camera", text="Down")
            down.direction = "DOWN"
            right = row.operator("fpan.nudge_gameplay_camera", text="Right")
            right.direction = "RIGHT"
            layout.label(text="Shortcuts: Alt+Shift+Arrow")
        if settings.native_camera_mode in {"FREE", "LOCKED"}:
            layout.prop(settings, "additive_fog_compatibility")
        layout.prop(settings, "geometry_edit_mode")
        if context.scene.get('fpan_source_mode')=='COMPILED_ONLY':
            edit_box=layout.box()
            edit_box.operator('fpan.toggle_placement',text='Placement editing',icon='EMPTY_AXIS',
                              depress=settings.placement_editing)
            if settings.placement_editing:
                target=settings.placement_target
                edit_box.label(text='Target: '+(target.name if target else 'none'))
                edit_box.label(text='G/R/S; click an FPAN object to switch')
                edit_box.label(text='Turn off for ordinary/vertex selection')
                if context.space_data.type=='VIEW_3D' and not context.space_data.overlay.show_overlays:
                    edit_box.label(text='Enable Overlays to see the mesh outline',icon='INFO')
            elif settings.placement_status:
                edit_box.label(text=settings.placement_status,icon='INFO')
        layout.prop(settings, "extended_inspection_clipping")
        layout.prop(settings, "two_sided_compatibility")
        layout.prop(settings, "rear_inspection_mode")
        diagnostic = viewport.draw_diagnostic()
        layout.label(
            text=(
                f"Draw: {diagnostic.get('status')} | "
                f"gizmo={diagnostic.get('show_gizmo')} overlay={diagnostic.get('show_overlays')}"
            )
        )
        layout.operator("fpan.validate_stage", icon="CHECKMARK")
        layout.separator()
        layout.label(text=settings.validation_status)
        if "fpan_stage_directory" in context.scene:
            box = layout.box()
            box.label(text=f"Stage: {context.scene.get('fpan_stage_directory')}")
            box.label(text=f"Models: {context.scene.get('fpan_model_count')}")
            box.label(text=f"Editable FBX loops: {context.scene.get('fpan_loop_preview_objects')}")
            box.label(text=f"Binary animated tracks: {context.scene.get('fpan_compiled_changing_tracks', 0)}")
            box.label(text=str(context.scene.get("fpan_animation_binding_status", "Animation status unavailable")))
            box.label(text=f"Preview: {context.scene.get('fpan_animation_preview_mode', 'n/a')}")
            box.label(text=f"Source: {context.scene.get('fpan_source_mode', 'legacy import')}")
            if context.scene.get('fpan_unrendered_components', '[]') != '[]':
                pat_status=str(diagnostic.get('pat','PAT effects: awaiting native viewport draw'))
                box.label(text=pat_status, icon='ERROR' if 'unsupported' in pat_status else 'INFO')
            box.label(text=f"Matrix sample spacing: {context.scene.get('fpan_runtime_sample_spacing', 1)} ticks")
        export_box = layout.box()
        export_box.label(text="Stage export", icon="EXPORT")
        export_box.operator('fpan.export_stage_copy', icon='EXPORT')
        export_box.label(text='All vertex moves + placement G/R/S')
        export_box.label(text='Topology, zero scale and edited keys blocked')
        export_box.label(text='Overwrite confirmation + automatic backup')
        if context.mode!='OBJECT':
            export_box.label(text='Return to Object Mode to export',icon='INFO')


class FPAN_PT_object_inspector(bpy.types.Panel):
    bl_label = "Selected FPAN Object"
    bl_idname = "FPAN_PT_object_inspector"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "FPAN Stage"
    bl_parent_id = "FPAN_PT_stage_pipeline"

    @classmethod
    def poll(cls, context):
        return _inspector_target(context) is not None

    def draw(self, context):
        obj = _inspector_target(context)
        layout = self.layout
        layout.label(text=obj.name)
        layout.label(text=f"Node: {obj.get('fpan_node_index')} / type {obj.get('fpan_node_type')}")
        layout.label(text=f"Blend mode: {obj.get('fpan_blend_mode', 'n/a')}")
        layout.label(text=f"Compiled samples: {obj.get('fpan_compiled_track_samples', 1)}")
        if context.scene.get('fpan_source_mode') == 'COMPILED_ONLY':
            if obj.type == 'MESH':
                layout.label(text="Tab: edit existing vertex positions")
                layout.label(text="Native preview follows vertex moves")
                layout.label(text="Topology/UV export not supported", icon='INFO')
            control=placement.control_for_object(obj)
            if control is not None:
                layout.label(text='Placement control: '+control.name)
                layout.label(text='G/R/S included in Export Edited Stage Copy')
                layout.operator('fpan.reset_placement', icon='LOOP_BACK')
        if obj.get("fpan_lazy_compiled_track"):
            layout.operator("fpan.materialize_selected_track", icon="ACTION")
        if obj.active_material is not None:
            layout.label(text=f"Render class: {obj.active_material.get('fpan_render_class', 'unclassified')}")
        if obj.get("fpan_authored_loop_period") is not None:
            layout.label(text=f"Editable cycle: {obj.get('fpan_authored_loop_period')} frames")
            layout.label(text=f"Infinite repeat: {bool(obj.get('fpan_infinite_post_repeat'))}")
        if obj.get("fpan_default_hidden_reason"):
            layout.label(text=obj.get("fpan_default_hidden_reason"), icon="INFO")


CLASSES = (FPAN_PT_stage_pipeline, FPAN_PT_object_inspector)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
