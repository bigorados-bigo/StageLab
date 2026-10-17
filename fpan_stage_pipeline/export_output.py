"""Normal save destinations with recoverable overwrite and atomic replacement."""
import hashlib
import os
import pathlib
import tempfile


def write_candidate(destination, data, *, source, overwrite=False):
    output=pathlib.Path(destination).resolve()
    source=pathlib.Path(source).resolve()
    if output==source or (output.exists() and output.samefile(source)):
        raise ValueError('This is the imported source file. Choose another filename so the original animation baseline remains available.')
    if output.is_dir():
        raise ValueError('Choose a filename, not just a folder')
    if not output.parent.is_dir():
        raise ValueError('Destination folder does not exist')
    previous=output.read_bytes() if output.exists() else None
    if previous is not None and not overwrite:
        raise ValueError('File already exists; confirm overwrite in the export file browser')
    if previous==data:
        return None
    backup=None
    if previous is not None:
        checksum=hashlib.sha256(previous).hexdigest()
        backup=output.with_name(output.name+'.'+checksum[:16]+'.bak')
        if not backup.exists():
            with backup.open('xb') as stream:
                stream.write(previous)
        if backup.read_bytes()!=previous:
            raise ValueError('Overwrite backup could not be verified; original left unchanged')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent,prefix='.fpan-export-',suffix='.tmp',delete=False) as stream:
            temporary=pathlib.Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if (output.read_bytes() if output.exists() else None)!=previous:
            raise ValueError('Destination changed during export; retry the save')
        os.replace(temporary,output)
        temporary=None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup
