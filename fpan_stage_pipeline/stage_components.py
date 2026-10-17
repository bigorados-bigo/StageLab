"""Read-only coverage inventory; never execute stage Squirrel scripts."""
import re


def script_objects(stage):
    """Decode the literal BgObject records; never evaluate Squirrel code."""
    source = stage / 'object.txt'
    if not source.is_file():
        return []
    text = re.sub(r'//[^\r\n]*', '', source.read_text(encoding='cp932', errors='strict'))
    objects = []
    for name, body in re.findall(r'\b(data\w*)\s*=\s*\[([\s\S]*?)\]', text):
        commands = []
        for record in re.findall(r'\{([^{}]*)\}', body):
            values = {}
            for field in record.split(','):
                if not field.strip():
                    continue
                key, sep, raw = field.partition('=')
                key, raw = key.strip(), raw.strip()
                if not sep or not re.fullmatch(r'[A-Za-z_]\w*',key):
                    raise ValueError(f'Unsupported BgObject field in {name}')
                if re.fullmatch(r'"[^"\\]*"',raw):
                    values[key] = raw[1:-1]
                elif re.fullmatch(r'[+-]?\d+(?:\.\d+)?',raw):
                    values[key] = float(raw) if '.' in raw else int(raw)
                else:
                    raise ValueError(f'Unsupported BgObject expression {raw!r} in {name}')
            if 'tag' not in values:
                raise ValueError(f'Missing BgObject command tag in {name}')
            commands.append(values)
        objects.append(dict(name=name,commands=commands))
    return objects


def inventory(stage):
    source = stage / 'object.txt'
    if not source.is_file():
        return []
    text = re.sub(r'//[^\r\n]*', '', source.read_text(encoding='cp932', errors='replace'))
    references = re.findall(r'\bpanidata\s*=\s*"([^"]+)"', text)
    frames = sorted(set(re.findall(r'\btag\s*=\s*"frm"\s*,\s*name\s*=\s*"([^"]+)"', text)))
    objects = len(re.findall(r'\bdata\w*\s*=\s*\[', text))
    return [dict(reference=ref, exists=(stage / ref.replace('\\','/').split('/')[-1]).is_file(),
                 object_count=objects, frames=frames, supported=False) for ref in references]
