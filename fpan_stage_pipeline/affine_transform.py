"""Preserve native affine locals despite Blender Object's TRS-only basis.

World = parent * placement-prefix * correction * Blender-basis.
correction = native-local * inverse(Blender-basis). The prefix stays separate
from this frame-owned correction so G/R/S placement never changes its owner.
"""
from mathutils import Matrix


def _matrix(values):
    return Matrix([values[i:i+4] for i in range(0,16,4)])


def _flat(matrix):
    return [v for row in matrix for v in row]


def correction(obj):
    values=obj.get('fpan_affine_correction')
    return _matrix(values) if values is not None else Matrix.Identity(4)


def parent_prefix(obj):
    values=obj.get('fpan_affine_parent_prefix')
    return _matrix(values) if values is not None else obj.matrix_parent_inverse.copy()


def set_parent_prefix(obj,prefix):
    if 'fpan_affine_correction' in obj:
        obj['fpan_affine_parent_prefix']=_flat(prefix)
        obj.matrix_parent_inverse=prefix @ correction(obj)
    else:
        obj.matrix_parent_inverse=prefix


def release(obj):
    if 'fpan_affine_correction' in obj:
        obj.matrix_parent_inverse=parent_prefix(obj)
        del obj['fpan_affine_correction']
        del obj['fpan_affine_parent_prefix']


def set_native_basis(obj,matrix):
    prefix=parent_prefix(obj)
    obj.matrix_basis=matrix
    basis=obj.matrix_basis.copy()
    error=max(abs(a-b) for ra,rb in zip(matrix,basis) for a,b in zip(ra,rb))
    if error<=1e-6:
        release(obj)
        return
    try:
        value=matrix @ basis.inverted()
    except ValueError:
        raise ValueError('Singular native affine matrix cannot be represented faithfully in Blender')
    obj['fpan_affine_parent_prefix']=_flat(prefix)
    obj['fpan_affine_correction']=_flat(value)
    obj.matrix_parent_inverse=prefix @ value
