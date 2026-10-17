"""UNI2 BgObject projection, row-vector convention.

Recovered from supported executable routine VA 0x518FC0. PAT coordinates are
screen-authored, not FPAN mesh units. Keep this conversion outside mesh import.
No stage IDs, fitted ring centers, or trace-frame offsets belong here.
"""
import math


def multiply(left, right):
    if len(left) != 16 or len(right) != 16:
        raise ValueError('Expected two row-major 4x4 matrices')
    if not all(math.isfinite(v) for v in (*left, *right)):
        raise ValueError('Non-finite projection matrix')
    return tuple(sum(left[row*4+k]*right[k*4+column] for k in range(4))
                 for row in range(4) for column in range(4))


def bg_object_projection(view, projection, viewport, inverse_half_width,
                         inverse_half_height):
    """Match 0x518FC0's S(1,-1,1/720) * N * V * P * viewport.

    N uses camera fields +0x26C/+0x270. The literal 1/720 is from the
    executable, not an assumed output-resolution setting.
    """
    if not (math.isfinite(inverse_half_width) and inverse_half_width > 0
            and math.isfinite(inverse_half_height) and inverse_half_height > 0):
        raise ValueError('Invalid native screen normalization')
    normalization = (inverse_half_width,0,0,0,
                     0,-inverse_half_height,0,0,
                     0,0,1/720,0,
                     0,0,0,1)
    return multiply(normalization, multiply(multiply(view, projection), viewport))


def project(position, matrix):
    if len(position) not in (3,4) or len(matrix) != 16:
        raise ValueError('Expected position and row-major 4x4 matrix')
    if not all(math.isfinite(v) for v in (*position, *matrix)):
        raise ValueError('Non-finite PAT projection input')
    vector = (*position, 1) if len(position)==3 else position
    result = tuple(sum(vector[k]*matrix[k*4+column] for k in range(4))
                   for column in range(4))
    if result[3] <= 0:
        return None
    return (*tuple(v/result[3] for v in result[:3]), 1/result[3])


def parts_projection():
    """Generic PAT part camera from VA 0x4C1860, BEFORE actor placement.

    This seemingly identity XY transform carries nontrivial Z and W into
    BgObject projection. Dividing it out early loses the native parallax/RHW.
    Constants preserve the executable's binary32 literals.
    """
    import struct
    f32 = lambda value: struct.unpack('<f',struct.pack('<f',value))[0]
    cotangent = f32(1/math.tan(struct.unpack('<f',struct.pack('<I',0x3FA78D36))[0]/2))
    q = f32(1000/(1000-f32(0.01)))
    near_q = f32(-f32(0.01)*q)
    return (f32(f32(f32(1/640)*cotangent)*640),0,0,0,
            0,f32(f32(f32(1/480)*cotangent)*480),0,0,
            0,0,f32(q/1024),1/1024,
            0,0,f32(f32(cotangent*q)+near_q),cotangent)
