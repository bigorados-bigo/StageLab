import pathlib

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import core


class FPAN_OT_import_stage(bpy.types.Operator, ImportHelper):
    bl_idname = "fpan.import_stage"
    bl_label = "Import FPAN Stage"
    bl_description = "Import an authoring FBX and join its retail FbxExp metadata"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="bg.fbx;bg.fbx.bin", options={"HIDDEN"})

    def execute(self, context):
        selected = pathlib.Path(self.filepath)
        stage = selected if selected.is_dir() else selected.parent
        settings = context.scene.fpan_stage
        try:
            result = core.import_stage(stage, clear_scene=settings.clear_scene)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        context.scene.fpan_stage.stage_directory = str(stage)
        from . import viewport
        viewport.sync_scene(context.scene)
        context.scene.fpan_stage.validation_status = "Imported; validation pending"
        self.report(
            {"INFO"},
            (
                f"Imported {result['stage']}: {result['models']} models, "
                f"{context.scene.get('fpan_compiled_changing_tracks', 0)} compiled animation tracks"
            ),
        )
        return {"FINISHED"}


class FPAN_OT_export_vertex_copy(bpy.types.Operator, ExportHelper):
    bl_idname = 'fpan.export_vertex_copy'
    bl_label = 'Save Selected Vertex Test Copy'
    bl_options = {'INTERNAL'}
    bl_description = 'Experimental: selected local vertex positions ONLY; retains original normals, animation and all unselected data. Never installs into the game'
    filename_ext = '.fbx.bin'
    filter_glob: StringProperty(default='*.fbx.bin', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.scene.get('fpan_source_mode') == 'COMPILED_ONLY' and bool(context.selected_objects)

    def draw(self, context):
        self.layout.label(text='Selected local vertex positions ONLY', icon='ERROR')
        self.layout.label(text='Original normals, materials and animation retained')
        self.layout.label(text='Not game-validated; reimport the copy first')
        self.layout.label(text='Save outside the extracted BG folder')

    def execute(self, context):
        from . import geometry_export
        try:
            count = geometry_export.selected_position_copy(context.scene, context.selected_objects, self.filepath)
        except (ValueError, OSError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Saved {count} selected mesh(es): vertex positions only; reimport copy to verify')
        return {'FINISHED'}


class FPAN_OT_export_placement_copy(bpy.types.Operator, ExportHelper):
    bl_idname = 'fpan.export_placement_copy'
    bl_label = 'Save Placement Movement Test Copy'
    bl_options = {'INTERNAL'}
    bl_description = 'Experimental: export ALL moved placement controls, preserving original geometry and independent native animation cycles. Movement only, not rotation/scale'
    filename_ext = '.fbx.bin'
    filter_glob: StringProperty(default='*.fbx.bin', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.scene.get('fpan_source_mode') == 'COMPILED_ONLY'

    def draw(self, context):
        self.layout.label(text='ALL placement movements (G) only', icon='INFO')
        self.layout.label(text='Native animation retained; original vertices retained')
        self.layout.label(text='Rotation/scale and combined vertex edits blocked')
        self.layout.label(text='Not game-validated; save a NEW external file')

    def execute(self, context):
        from . import placement_export
        try:
            count = placement_export.scene_translation_copy(context.scene, self.filepath)
        except (ValueError, OSError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Saved {count} placement movement(s), preserving native cycles; test copy only')
        return {'FINISHED'}


class FPAN_OT_export_stage_copy(bpy.types.Operator, ExportHelper):
    bl_idname = 'fpan.export_stage_copy'
    bl_label = 'Export Edited Stage Copy'
    bl_description = 'Save ALL existing vertex-position edits and placement movement/rotation/scale together, preserving native animation. Topology and animation authoring remain unsupported'
    filename_ext = '.bin'
    filter_glob: StringProperty(default='*.fbx.bin', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.scene.get('fpan_source_mode') == 'COMPILED_ONLY'

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = 'bg-edited.fbx.bin'
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        self.layout.label(text='All vertex positions + placement G/R/S', icon='INFO')
        self.layout.label(text='Selection does not limit export')
        self.layout.label(text='Native animation, original UVs/normals/materials retained')
        self.layout.label(text='Topology, zero scale and Blender keys blocked')
        self.layout.label(text='Existing files are backed up before overwrite')

    def execute(self, context):
        from . import placement_export
        try:
            # ExportHelper's file browser supplies Blender's standard overwrite
            # confirmation. The writer additionally preserves the replaced file.
            result = placement_export.scene_edit_copy(context.scene, self.filepath, overwrite=True)
        except (ValueError, OSError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Saved {result['vertex_meshes']} vertex-edited mesh(es) and {result['placements']} placement transform(s)")
        return {'FINISHED'}


class FPAN_OT_validate_stage(bpy.types.Operator):
    bl_idname = "fpan.validate_stage"
    bl_label = "Validate Stage"
    bl_description = "Check structural metadata and report known unsupported records"

    def execute(self, context):
        errors, warnings = core.validate_scene(context.scene)
        if errors:
            status = f"FAIL: {errors[0]}"
            self.report({"ERROR"}, status)
            context.scene.fpan_stage.validation_status = status
            return {"CANCELLED"}
        status = "PASS" if not warnings else f"PASS with warning: {warnings[0]}"
        context.scene.fpan_stage.validation_status = status
        self.report({"WARNING"} if warnings else {"INFO"}, status)
        return {"FINISHED"}


class FPAN_OT_toggle_placement(bpy.types.Operator):
    bl_idname = 'fpan.toggle_placement'
    bl_label = 'Placement Editing'
    bl_description = 'Toggle persistent single-target placement editing; turn off to return to ordinary object/vertex selection'
    bl_options = {'REGISTER','UNDO'}

    @classmethod
    def poll(cls,context):
        return context.scene.get('fpan_source_mode')=='COMPILED_ONLY'

    def execute(self,context):
        settings=context.scene.fpan_stage
        settings.placement_editing=not settings.placement_editing
        if not settings.placement_editing and settings.placement_status:
            self.report({'WARNING'},settings.placement_status)
        return {'FINISHED'}


class FPAN_OT_placement_transform(bpy.types.Operator):
    bl_idname = 'fpan.placement_transform'
    bl_label = 'Placement Transform'
    bl_options = {'INTERNAL'}
    action: EnumProperty(items=[(s,s.title(),'') for s in ('TRANSLATE','ROTATE','RESIZE')])

    @classmethod
    def poll(cls,context):
        from . import placement_session
        return (context.mode=='OBJECT' and context.area is not None and context.area.type=='VIEW_3D'
                and hasattr(context.scene,'fpan_stage') and context.scene.fpan_stage.placement_editing
                and placement_session.owns_context(context))

    def invoke(self,context,event):
        from . import placement_session
        try:
            if not placement_session.synchronize(context):
                return {'CANCELLED'}
            placement_session._trace('keyboard_transform',action=self.action)
            getattr(bpy.ops.transform,self.action.lower())('INVOKE_DEFAULT')
        except (ValueError,RuntimeError) as error:
            self.report({'ERROR'},str(error))
            return {'CANCELLED'}
        # Blender's own transform operator owns modal input, cancellation,
        # snapping and undo. This wrapper only closes the click->G timer race.
        return {'FINISHED'}


class FPAN_OT_edit_placement(bpy.types.Operator):
    bl_idname = 'fpan.edit_placement'
    bl_label = 'Select Placement Control'
    bl_description = 'Select a standard Blender parent control; G/R/S offsets placement without overwriting native animation. Movement-only test export is available separately'
    bl_options = {'REGISTER','UNDO'}

    @classmethod
    def poll(cls,context):
        from . import placement
        return (context.mode=='OBJECT' and context.scene.get('fpan_source_mode')=='COMPILED_ONLY'
                and placement.target_for_object(context.active_object) is not None)

    def execute(self,context):
        from . import placement
        try:
            control=placement.ensure_control(context.active_object)
        except ValueError as error:
            self.report({'ERROR'},str(error))
            return {'CANCELLED'}
        for obj in context.selected_objects:
            obj.select_set(False)
        control.select_set(True)
        context.view_layer.objects.active=control
        return {'FINISHED'}


class FPAN_OT_reset_placement(bpy.types.Operator):
    bl_idname = 'fpan.reset_placement'
    bl_label = 'Reset Placement Offset'
    bl_description = 'Restore this placement control to its initial transform without modifying the native track'
    bl_options = {'REGISTER','UNDO'}

    @classmethod
    def poll(cls,context):
        from . import placement
        return context.mode=='OBJECT' and placement.control_for_object(context.active_object) is not None

    def execute(self,context):
        from . import placement
        control=placement.control_for_object(context.active_object)
        try:
            placement.reset_control(control)
        except ValueError as error:
            self.report({'ERROR'},str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class FPAN_OT_materialize_selected_track(bpy.types.Operator):
    bl_idname = "fpan.materialize_selected_track"
    bl_label = "Make Selected Branch Editable"
    bl_description = "Convert the selected object's compiled transform and any animated FPAN parents into editable Blender keys"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from . import placement
        obj = placement.target_for_object(context.active_object)
        while obj is not None:
            if obj.get("fpan_lazy_compiled_track"):
                return True
            obj = obj.parent
        return False

    def execute(self, context):
        from . import placement
        obj = placement.target_for_object(context.active_object)
        animations = core._runtime_animations(context.scene)
        node_index = int(obj.get("fpan_node_index", -1))
        if animations is None or node_index < 0 or node_index >= len(animations):
            self.report({"ERROR"}, "Compiled FPAN track is unavailable")
            return {"CANCELLED"}
        materialized = []
        current = obj
        while current is not None:
            current_index = int(current.get("fpan_node_index", -1))
            if (
                0 <= current_index < len(animations)
                and current.get("fpan_lazy_compiled_track")
                and core.materialize_compiled_track(current, current_index, animations[current_index])
            ):
                materialized.append((current.name, len(animations[current_index])))
                core.extend_authoring_timeline(context.scene, len(animations[current_index]))
            current = current.parent
        if not materialized:
            self.report({"ERROR"}, "Selected branch is static or already editable")
            return {"CANCELLED"}
        context.scene.fpan_stage.animation_preview_mode = "AUTHORING"
        context.scene.frame_set(min(context.scene.frame_current, context.scene.frame_end))
        self.report(
            {"INFO"},
            f"Materialized {len(materialized)} track(s), through {context.scene.frame_end} frames",
        )
        return {"FINISHED"}


class FPAN_OT_nudge_gameplay_camera(bpy.types.Operator):
    bl_idname = "fpan.nudge_gameplay_camera"
    bl_label = "Nudge Gameplay Camera"
    bl_description = "Move the captured gameplay view without changing stage data"
    bl_options = {"REGISTER"}

    direction: EnumProperty(
        items=(
            ("LEFT", "Left", "Move the rendered gameplay view left"),
            ("RIGHT", "Right", "Move the rendered gameplay view right"),
            ("UP", "Up", "Move the rendered gameplay view up"),
            ("DOWN", "Down", "Move the rendered gameplay view down"),
        )
    )

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, "fpan_stage")

    def execute(self, context):
        settings = context.scene.fpan_stage
        step = float(settings.gameplay_camera_step)
        if self.direction == "LEFT":
            settings.gameplay_camera_x += step
        elif self.direction == "RIGHT":
            settings.gameplay_camera_x -= step
        elif self.direction == "UP":
            settings.gameplay_camera_y -= step
        elif self.direction == "DOWN":
            settings.gameplay_camera_y += step
        else:
            return {"CANCELLED"}
        settings.native_camera_mode = "LOCKED"
        settings.gameplay_camera_preview = True
        return {"FINISHED"}


CLASSES = (
    FPAN_OT_import_stage,
    FPAN_OT_export_vertex_copy,
    FPAN_OT_export_placement_copy,
    FPAN_OT_export_stage_copy,
    FPAN_OT_validate_stage,
    FPAN_OT_toggle_placement,
    FPAN_OT_placement_transform,
    FPAN_OT_edit_placement,
    FPAN_OT_reset_placement,
    FPAN_OT_materialize_selected_track,
    FPAN_OT_nudge_gameplay_camera,
)

_KEYMAP_ITEMS = []


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        # Object Mode's map handles G/R/S before the generic 3D View map.
        # Poll falls through to Blender unchanged whenever the session is off.
        keymap = keyconfig.keymaps.new(name='Object Mode',space_type='EMPTY')
        for key,action in (('G','TRANSLATE'),('R','ROTATE'),('S','RESIZE')):
            item=keymap.keymap_items.new('fpan.placement_transform',key,'PRESS',head=True)
            item.properties.action=action
            _KEYMAP_ITEMS.append((keymap,item))
        keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
        for key, direction in (
            ("LEFT_ARROW", "LEFT"),
            ("RIGHT_ARROW", "RIGHT"),
            ("UP_ARROW", "UP"),
            ("DOWN_ARROW", "DOWN"),
        ):
            item = keymap.keymap_items.new(
                FPAN_OT_nudge_gameplay_camera.bl_idname,
                key,
                "PRESS",
                shift=True,
                alt=True,
                repeat=True,
            )
            item.properties.direction = direction
            _KEYMAP_ITEMS.append((keymap, item))


def unregister():
    for keymap, item in reversed(_KEYMAP_ITEMS):
        keymap.keymap_items.remove(item)
    _KEYMAP_ITEMS.clear()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
