"""Verify the distinct onedir headless bundle without weakening the desktop verifier."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import zipfile

ROOT=Path(__file__).resolve().parents[1]
WINSW_SHA='05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def verify(directory):
    spec=importlib.util.spec_from_file_location('desktop_verifier',ROOT/'scripts/verify-windows-package.py')
    rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')): raise ValueError('Links are forbidden.')
    if digest(directory/'SAPLensService.exe')!=WINSW_SHA: raise ValueError('Service wrapper integrity mismatch.')
    if {p.name for p in directory.iterdir()} != {'app','SAPLensService.exe','manage-server-service.ps1','README.md','LICENSE-WinSW.txt'}:
        raise ValueError('Unexpected server bundle root files.')
    executable=directory/'app/SAP-Lens.exe';data=executable.read_bytes()
    pe=struct.unpack_from('<I',data,0x3c)[0]
    if data[:2]!=b'MZ' or data[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<H',data,pe+4)[0]!=0x8664:
        raise ValueError('Expected a Windows x64 PE.')
    if struct.unpack_from('<H',data,pe+24+68)[0]!=3: raise ValueError('Service host must use console lifecycle signals.')
    rules.inspect_resources(data)  # Same version/icon/manifest/signature protections.
    from PyInstaller.archive.readers import CArchiveReader
    class CheckedReader(CArchiveReader):
        @classmethod
        def _parse_toc(cls, data):
            rules.validate_toc(data)
            return super()._parse_toc(data)
    archive=CheckedReader(str(executable));modules=[]
    with executable.open('rb') as stream:
        stream.seek(archive._end_offset-archive._COOKIE_LENGTH)
        _,length,offset,size,_,_=struct.unpack(archive._COOKIE_FORMAT,stream.read(archive._COOKIE_LENGTH))
    if archive._start_offset<0 or offset+size+archive._COOKIE_LENGTH!=length:
        raise ValueError('Inconsistent executable archive layout.')
    if 'server' not in archive.toc: raise ValueError('Missing headless entry point.')
    for name,entry in archive.toc.items():
        contents=archive.extract(name)
        if entry[-1]=='z':
            embedded=archive.open_embedded_archive(name);modules.extend(embedded.toc)
            for module in embedded.toc: embedded.extract(module)
        elif name=='build-version.json':
            if json.loads(contents)!=rules.metadata_module().BUILD_INFO: raise ValueError('Embedded identity mismatch.')
    if not {'main','deployment','version'} <= set(modules) or any(n=='webview' or n.startswith('webview.') for n in modules):
        raise ValueError('Server modules are missing or desktop modules were included.')
    if {p.name for p in (directory/'app').iterdir()} != {'SAP-Lens.exe','_internal'}:
        raise ValueError('Unexpected application files.')
    internal=directory/'app/_internal'
    for path in internal.rglob('*'):
        if path.is_symlink(): raise ValueError('Links are not distribution inputs.')
        if not path.is_file():continue
        name=path.relative_to(internal).as_posix()
        rules.validate_names([name])
        if name.endswith(('.html','.js','.css','.json','.txt')): rules.secret_check(path.read_bytes())
        if name=='base_library.zip':
            with zipfile.ZipFile(path) as zipped:
                rules.validate_names(zipped.namelist())
                if zipped.testzip(): raise ValueError('Corrupt standard library archive.')
    expected={p.relative_to(ROOT/'frontend/dist').as_posix():digest(p) for p in (ROOT/'frontend/dist').rglob('*') if p.is_file()}
    actual={p.relative_to(internal/'frontend/dist').as_posix():digest(p) for p in (internal/'frontend/dist').rglob('*') if p.is_file()}
    if not expected or actual!=expected: raise ValueError('Frontend integrity mismatch.')
    if json.loads((internal/'build-version.json').read_text())!=rules.metadata_module().BUILD_INFO:
        raise ValueError('External build identity mismatch.')
    for name in ('sap-lens.ico','sap-lens.png'):
        if digest(internal/'assets'/name)!=digest(ROOT/'assets'/name): raise ValueError('Canonical branding mismatch.')
    if not any(internal.glob('python3*.dll')): raise ValueError('Python runtime missing.')
    files={p.relative_to(directory).as_posix():digest(p) for p in directory.rglob('*') if p.is_file()}
    report={'schema':1,'verification':'passed','signing':'disabled','format':'onedir-console-service',
            'native_service_smoke':'pending','identity':rules.metadata_module().BUILD_INFO,'files':files}
    (directory/'verification-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Server PE/resources, embedded modules, frontend, wrapper, privacy and file checksums verified. Native SCM tests remain required.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    try:verify(parser.parse_args().directory)
    except Exception as error: parser.exit(1,f'Server package verification failed ({type(error).__name__}); private details omitted.\n')
