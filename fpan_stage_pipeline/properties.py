import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from bpy.props import FloatProperty


def update_animation_preview(self, context):
    from . import core
    core.refresh_animation_preview(context.scene)


def update_exact_additive(self, context):
    from . import render_engine, viewport
    render_engine.set_enabled(context.scene, self.exact_additive_viewport)
    viewport.update_exact_additive(self, context)


def update_placement(self,context):
    from . import placement_session
    placement_session.update(self,context)


class FPANStageSettings(bpy.types.PropertyGroup):
    placement_editing: BoolProperty(name='Placement editing',default=False,
        description='Keep one FPAN mesh and its offset control selected; G/R/S changes placement while preserving native animation. Turn off for vertex editing',
        options={'SKIP_SAVE'},update=update_placement)
    placement_target: PointerProperty(type=bpy.types.Object,options={'SKIP_SAVE'})
    placement_status: StringProperty(options={'SKIP_SAVE'})
    stage_directory: StringProperty(name="Stage directory", subtype="DIR_PATH")
    profile: EnumProperty(
        name="Profile",
        items=(
            ("AUTO", "Auto", "Detect the supported game/stage profile"),
            ("UNI2", "UNI2", "UNDER NIGHT IN-BIRTH II / current FPAN profile"),
        ),
        default="AUTO",
    )
    clear_scene: BoolProperty(
        name="Clear current scene",
        description="Start a new scene before importing the stage",
        default=True,
    )
    validation_status: StringProperty(name="Validation", default="Not validated")
    scripted_effects: BoolProperty(
        name="Scripted PAT effects",
        description="Draw supported object.txt/PAT effects in the native viewport; unsupported records are reported separately",
        default=True,
        update=update_exact_additive,
    )
    animation_preview_mode: EnumProperty(
        name="Animation view",
        description="Switch without modifying the editable source animation",
        items=(
            ("AUTHORING", "Editable / Safe Preview", "Use editable Blender actions where materialized and lossless compiled matrices for untouched tracks"),
            ("COMPILED", "Compiled Runtime Preview", "Evaluate the authoritative sampled FPAN object-local matrices"),
        ),
        default="AUTHORING",
        update=update_animation_preview,
    )
    exact_additive_viewport: BoolProperty(
        name="Native D3D9 viewport",
        description="Use the ordered FPAN RenderEngine with native blend, alpha-test, and depth-write behavior",
        default=False,
        update=update_exact_additive,
    )
    gameplay_camera_preview: BoolProperty(
        name="Native gameplay camera",
        description=(
            "Use the stage's BgList FOV, vanishing point, camera offset, fog, and "
            "retail coordinate transform in the custom viewport"
        ),
        default=False,
        update=update_exact_additive,
    )
    native_camera_mode: EnumProperty(
        name="Native-look camera",
        description="Choose the captured locked battle view or a flyable Blender view using the stage FOV and fog",
        items=(
            ("OFF", "Off", "Use the ordinary Blender viewport contract"),
            ("LOCKED", "Locked gameplay", "Use the captured retail battle-camera transform"),
            ("FREE", "Flyable native look", "Use Blender navigation with the stage FOV, fog, and D3D9 material contract"),
        ),
        default="LOCKED",
        update=update_exact_additive,
    )
    free_camera_fog: BoolProperty(
        name="Apply stage fog while flying",
        description=(
            "Apply the retail stage fog to Blender's free camera. Disabled by "
            "default because leaving the authored battle-camera volume can fog "
            "the entire inspection view; locked gameplay always keeps native fog"
        ),
        default=False,
        update=update_exact_additive,
    )
    locked_camera_fog: BoolProperty(
        name="Apply stage fog in gameplay camera",
        description=(
            "Apply the stage's captured fog parameters in the locked gameplay "
            "camera. Enabled by default to match the retail presentation"
        ),
        default=True,
        update=update_exact_additive,
    )
    stage_postprocess: BoolProperty(
        name="Native background color / bloom",
        description="Apply the recovered background bloom and final shadow-lift shader in both native camera modes",
        default=True,
        update=update_exact_additive,
    )
    additive_fog_compatibility: BoolProperty(
        name="Prevent additive-card fog boxes",
        description=(
            "In either native-look camera, prevent fog from turning the opaque "
            "black rectangle of additive DXT1 cards into a visible colored box. "
            "Disable only when inspecting the literal captured D3D9 fog shader"
        ),
        default=True,
        update=update_exact_additive,
    )
    free_camera_additive_depth_compatibility: BoolProperty(
        name="Prevent additive-card depth boxes while flying",
        description=(
            "In flyable native view, keep additive cards depth-tested against "
            "solid geometry but stop their opaque-alpha rectangle from writing "
            "depth over later effects. Locked gameplay always retains the "
            "captured native depth-write ordering"
        ),
        default=True,
        update=update_exact_additive,
    )
    gameplay_camera_x: FloatProperty(
        name="Gameplay camera horizontal",
        description=(
            "Retail battle-camera horizontal translation; -2.4 is the captured "
            "neutral/spawn baseline, while the running game may move it dynamically"
        ),
        default=-2.4,
        update=update_exact_additive,
    )
    gameplay_camera_y: FloatProperty(
        name="Gameplay camera vertical",
        description="Vertical retail camera translation for stage-height inspection",
        default=0.0,
        update=update_exact_additive,
    )
    gameplay_camera_zoom: FloatProperty(
        name="Gameplay camera zoom",
        description="Preview-only projection zoom; values below 1 show more of the stage",
        default=1.0,
        min=0.1,
        max=4.0,
        soft_min=0.5,
        soft_max=2.0,
        update=update_exact_additive,
    )
    gameplay_camera_step: FloatProperty(
        name="Camera nudge step",
        description="Distance moved by the gameplay-camera arrow controls and shortcuts",
        default=0.1,
        min=0.001,
        soft_max=1.0,
        update=update_exact_additive,
    )
    geometry_edit_mode: BoolProperty(
        name="Geometry editing view",
        description="Overlay selectable Blender wire/edit cages while retaining the D3D9 native-look pass",
        default=False,
        update=update_exact_additive,
    )
    editor_gizmos: BoolProperty(
        name="Show editing gizmos",
        description="Show Blender tool/navigation gizmos without disabling the native viewport hook",
        default=True,
        update=update_exact_additive,
    )
    editor_overlays: BoolProperty(
        name="Show editing overlays",
        description="Show Blender extras and relationship overlays without disabling the native viewport hook",
        default=True,
        update=update_exact_additive,
    )
    extended_inspection_clipping: BoolProperty(
        name="Extended inspection clipping",
        description=(
            "Extend Blender's free-view far clipping distance for large FPAN stages; "
            "preview-only and never exported"
        ),
        default=True,
        update=update_exact_additive,
    )
    rear_inspection_mode: BoolProperty(
        name="Rear inspection: hide additive FX",
        description=(
            "Hide camera-composition additive effects while inspecting the stage from behind; "
            "preview-only and never exported"
        ),
        default=False,
        update=update_exact_additive,
    )
    two_sided_compatibility: BoolProperty(
        name="Inspection-only two-sided",
        description="Disable native back-face culling only for free inspection; this is not game-accurate",
        default=False,
        update=update_exact_additive,
    )


CLASSES = (FPANStageSettings,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fpan_stage = PointerProperty(type=FPANStageSettings)


def unregister():
    del bpy.types.Scene.fpan_stage
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
