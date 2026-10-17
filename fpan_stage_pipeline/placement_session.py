"""Transient, single-target placement session using ordinary Blender selection.

No renderer hooks or transform polling: only repair the selected parent/child
pair when selection changes. Blender excludes the selected child from a parent
transform, retaining its outline without double-transforming native animation.
"""
import time
import bpy
from bpy.app.handlers import persistent
from . import placement

_SESSION=None
_UPDATING=False
_TRACE=[]


def _trace(event, **values):
    _TRACE.append(dict(event=event,**values))
    del _TRACE[:-32]


def diagnostic():
    return list(_TRACE)


def owns_context(context):
    return (_SESSION is not None and context.window==_SESSION['window']
            and context.scene==_SESSION['scene'] and context.view_layer==_SESSION['view_layer'])


def _select_pair(context,target,control):
    layer=context.view_layer
    for obj in context.selected_objects:
        if obj not in (target,control):
            obj.select_set(False,view_layer=layer)
    target.select_set(True,view_layer=layer)
    control.select_set(True,view_layer=layer)
    layer.objects.active=control


def stop(restore=True):
    global _SESSION,_UPDATING
    session=_SESSION
    _SESSION=None
    if session is None:
        return
    _UPDATING=True
    try:
        settings=session['scene'].fpan_stage
        settings.placement_editing=False
        settings.placement_target=None
        settings.placement_status=''
        if restore and session['window'].scene==session['scene']:
            with bpy.context.temp_override(window=session['window']):
                target=session['target']
                for obj in bpy.context.selected_objects:
                    obj.select_set(False)
                target.select_set(True)
                bpy.context.view_layer.objects.active=target
    except (ReferenceError,RuntimeError):
        pass
    finally:
        _UPDATING=False
    _trace('stop',restore=restore)


def update(settings,context):
    global _SESSION,_UPDATING
    if _UPDATING:
        return
    if not settings.placement_editing:
        stop()
        return
    try:
        if context.mode!='OBJECT' or context.scene.get('fpan_source_mode')!='COMPILED_ONLY':
            raise ValueError('Select a compiled FPAN object in Object Mode')
        target=placement.target_for_object(context.active_object)
        if target is None or context.window is None:
            raise ValueError('Select an FPAN object before enabling placement editing')
        if _SESSION is not None:
            stop()
        control=placement.ensure_control(target)
        _SESSION=dict(window=context.window,scene=context.scene,target=target,control=control,
                      view_layer=context.view_layer)
        _UPDATING=True
        settings.placement_editing=True
        settings.placement_target=target
        settings.placement_status='G/R/S: offset | click FPAN object: switch target'
        _UPDATING=False
        _select_pair(context,target,control)
        _trace('start',target=target.name,control=control.name)
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick,first_interval=0.05)
    except (ValueError,RuntimeError,ReferenceError) as error:
        stop(False)
        _UPDATING=True
        settings.placement_editing=False
        settings.placement_status=str(error)
        _UPDATING=False


def synchronize(context):
    """Synchronize once at a UI boundary; also used before keyboard transforms."""
    session=_SESSION
    if session is None:
        return False
    if (context.window!=session['window'] or context.scene!=session['scene']
            or context.view_layer!=session['view_layer'] or context.mode!='OBJECT'):
        stop(False)
        return False
    target=session['target']
    control=placement.control_for_object(target)
    if control is None or control!=session['control']:
        # Undo/deletion must not silently recreate controls behind the user.
        stop(False)
        return False
    incoming=placement.target_for_object(context.active_object)
    if incoming is not None and incoming!=target:
        control=placement.ensure_control(incoming)
        target=incoming
        session.update(target=target,control=control)
        context.scene.fpan_stage.placement_target=target
        _trace('retarget',target=target.name)
    if target.hide_get() or control.hide_get():
        stop(False)
        return False
    selected=set(context.selected_objects)
    if context.active_object!=control or selected!={target,control}:
        _select_pair(context,target,control)
        _trace('selection_pair',target=target.name)
    return True


def _tick():
    if _SESSION is None:
        return None
    started=time.perf_counter()
    try:
        window=_SESSION['window']
        with bpy.context.temp_override(window=window):
            synchronize(bpy.context)
    except (ReferenceError,RuntimeError,ValueError) as error:
        _trace('error',message=str(error))
        scene=_SESSION['scene'] if _SESSION is not None else None
        stop(False)
        try:
            if scene is not None:
                scene.fpan_stage.placement_status=str(error)
        except ReferenceError:
            pass
    # Only bounded diagnostic state, never geometry or per-frame matrix hashes.
    if _SESSION is not None:
        _SESSION['last_tick_ms']=(time.perf_counter()-started)*1000
    return 0.05 if _SESSION is not None else None


@persistent
def _cleanup(_unused):
    global _UPDATING
    stop(False)
    _UPDATING=True
    try:
        for scene in bpy.data.scenes:
            settings=getattr(scene,'fpan_stage',None)
            if settings is not None:
                settings.placement_editing=False
                settings.placement_target=None
    finally:
        _UPDATING=False


def register():
    for handlers in (bpy.app.handlers.load_pre,bpy.app.handlers.load_post,
                     bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if _cleanup not in handlers:
            handlers.append(_cleanup)


def unregister():
    stop()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for handlers in (bpy.app.handlers.load_pre,bpy.app.handlers.load_post,
                     bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if _cleanup in handlers:
            handlers.remove(_cleanup)
