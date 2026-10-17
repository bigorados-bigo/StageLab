"""Standard Blender parent controls; keep placement separate from native tracks."""
import bpy
from mathutils import Matrix
from . import affine_transform


def target_for_object(obj):
    if obj is None:
        return None
    if 'fpan_node_index' in obj and int(obj['fpan_node_index']) != 0:
        return obj
    if obj.get('fpan_placement_control'):
        matches=[child for child in obj.children
                 if child.get('fpan_node_index') == obj.get('fpan_placement_node')]
        return matches[0] if len(matches)==1 else None
    return None


def control_for_object(obj):
    target=target_for_object(obj)
    if target is None:
        return None
    parent=target.parent
    return parent if (parent is not None and parent.get('fpan_placement_control')
                      and target_for_object(parent)==target) else None


def ensure_control(obj):
    target=target_for_object(obj)
    if target is None:
        raise ValueError('Select an imported FPAN node, not the inspection root')
    if target.library or target.override_library:
        raise ValueError('Placement controls require a local editable object')
    existing=control_for_object(target)
    if existing is not None:
        return existing
    if target.parent_type != 'OBJECT':
        raise ValueError('Non-object parenting requires a separate placement contract')
    if target.constraints:
        raise ValueError('Remove target constraints before inserting a placement control')
    basis=target.matrix_basis.copy()
    inverse=affine_transform.parent_prefix(target)
    rest=Matrix.Translation(basis.translation)
    control=bpy.data.objects.new(target.name+' Placement',None)
    for collection in target.users_collection:
        collection.objects.link(control)
    if not control.users_collection:
        bpy.context.scene.collection.objects.link(control)
    control.empty_display_type='PLAIN_AXES'
    control.empty_display_size=0.25
    control['fpan_placement_control']=True
    control['fpan_placement_node']=int(target['fpan_node_index'])
    control['fpan_placement_rest_matrix']=[value for row in rest for value in row]
    control.parent=target.parent
    # P @ inverse @ rest @ inverse(rest) @ basis preserves the initial world
    # transform. Place the control pivot at the child's current origin instead
    # of at the old parent's distant origin. Frame handlers still own ONLY the
    # child's basis, never this control. Preserve inverse matrices verbatim.
    control.matrix_parent_inverse=inverse
    control.matrix_basis=rest
    target.parent=control
    affine_transform.set_parent_prefix(target,rest.inverted())
    target.matrix_basis=basis
    return control


def reset_control(control):
    if control.animation_data is not None or control.constraints:
        raise ValueError('Remove animation/constraints on the placement control before resetting it')
    values=control.get('fpan_placement_rest_matrix')
    if values is None or len(values)!=16:
        raise ValueError('Placement control is missing its rest transform')
    control.matrix_basis=Matrix([values[index:index+4] for index in range(0,16,4)])
