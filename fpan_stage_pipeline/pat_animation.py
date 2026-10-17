"""Literal BgObject frame clock, independent of FBX matrix sampling."""


def frame_pair(commands, tick):
    frames=[command for command in commands if command['tag']=='frm']
    if not frames:
        raise ValueError('BgObject has no frame commands')
    delay=next((command['val'] for command in commands if command['tag']=='startdelay'),0)
    if delay < 0 or int(delay)!=delay:
        raise ValueError('Unsupported BgObject delay')
    durations=[]
    for command in frames:
        duration=command.get('wait',0)
        if duration <= 0 or int(duration)!=duration:
            raise ValueError('Unsupported BgObject frame duration')
        durations.append(int(duration))
    if tick < delay:
        return None
    phase=(tick-delay)%sum(durations)
    for index,duration in enumerate(durations):
        if phase < duration:
            return frames[index]['name'],frames[(index+1)%len(frames)]['name'],phase/duration
        phase-=duration
    raise AssertionError('Invalid PAT phase')


def mix_property(first, second, tag, fraction, default):
    a=first.get(tag,default)
    b=second.get(tag,default)
    if len(a)!=len(b):
        raise ValueError(f'Incompatible PAT property {tag}')
    return tuple(x+(y-x)*fraction for x,y in zip(a,b))
