bl_info = {
    "name": "StageLab",
    "author": "Bigo",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "3D Viewport > Sidebar > FPAN Stage",
    "description": "UNI2 FPAN stage import, native-look preview, editing and compiled export",
    "doc_url": "https://github.com/bigorados-bigo/StageLab",
    "tracker_url": "https://github.com/bigorados-bigo/StageLab/issues",
    "category": "Import-Export",
}

from . import core, operators, properties, render_engine, ui, viewport, placement_session


def register():
    render_engine.register()
    properties.register()
    placement_session.register()
    operators.register()
    ui.register()
    core.register_handlers()
    viewport.register()


def unregister():
    placement_session.unregister()
    viewport.unregister()
    core.unregister_handlers()
    ui.unregister()
    operators.unregister()
    properties.unregister()
    render_engine.unregister()
