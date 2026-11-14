"""Installer resource checks supplement, never replace, portable payload verification."""
import argparse
import json
import re
import uuid
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))


class InstallerValidationError(ValueError):
    """Only fixed, nonprivate diagnostics may be shown in build logs."""


def bound_identity(payload_sha256, directory=None):
    """The identity recorded for the verified payload EXE, instead of whatever the checkout's current build identity is.

    `verify-windows-package.py` writes `backend/build/artifact-identity/<exe-sha256>.json` only after it has checked that the identity embedded in
    that exact executable is consistent, so an installer built from an earlier commit is compared with the identity of ITS payload and not with the
    current repository. Missing, linked, oversized or inconsistent records are refused; there is no fallback to the current identity."""
    from version import BASE_PATTERN, base_numbers, release_file_version
    if not isinstance(payload_sha256, str) or not re.fullmatch('[0-9a-f]{64}', payload_sha256):
        raise InstallerValidationError('Payload checksum is not a SHA-256 digest.')
    path = Path(directory or ROOT / 'backend/build/artifact-identity') / f'{payload_sha256}.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise InstallerValidationError('No build identity is bound to the payload executable; run package verification for it first.')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        identity = record['identity']
        ok = (isinstance(record, dict) and record.get('schema') == 1 and record.get('exe_sha256') == payload_sha256 and isinstance(identity, dict)
              and set(identity) == {'version', 'file_version', 'source_sha'} and isinstance(identity['version'], str)
              and re.fullmatch('[0-9a-f]{40}', str(identity['source_sha'])) and isinstance(identity['file_version'], list) and len(identity['file_version']) == 4
              and all(type(n) is int and 0 <= n <= 65535 for n in identity['file_version']))
        if ok:
            base = re.match('(' + BASE_PATTERN + ')', identity['version'])
            ok = bool(base) and identity['file_version'][:3] == base_numbers(base[1])
        if ok and re.fullmatch('(' + BASE_PATTERN + r')(-(alpha|beta|rc)\.[1-9][0-9]{0,4})?', identity['version']):
            ok = identity['file_version'] == release_file_version(identity['version'])   # the numeric contract is not negotiable per record
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise InstallerValidationError('The build identity bound to the payload is malformed or violates the version contract.')
    return dict(version=identity['version'], file_version=identity['file_version'], source_sha=identity['source_sha'])


def verify(path, expected=None, acceptance_id=None):
    import pefile
    from version import BUILD_INFO
    expected=BUILD_INFO if expected is None else expected
    pe=pefile.PE(str(path))
    try:
        if pe.OPTIONAL_HEADER.Subsystem != 2: raise InstallerValidationError('Installer must use the Windows GUI subsystem.')
        directory=pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']]
        if directory.VirtualAddress or directory.Size:raise InstallerValidationError('Signing must remain disabled.')
        metadata={}
        for group in getattr(pe,'FileInfo',[]):
            for entry in group:
                for table in getattr(entry,'StringTable',[]):
                    for key,value in table.entries.items():
                        name=key.decode('utf-8')
                        if name in metadata:raise InstallerValidationError('Installer contains duplicate version strings.')
                        # Inno updates fixed-width resource templates in-place.
                        # Ignore only its trailing space/NUL padding, not leading
                        # whitespace, embedded NULs or any product/version text.
                        metadata[name]=value.decode('utf-8').rstrip(' \x00')
        description = 'SAP Lens Setup'
        if acceptance_id is not None:
            try:
                identity = str(uuid.UUID(acceptance_id)).upper()
            except ValueError:
                raise InstallerValidationError('Invalid acceptance identity.') from None
            if identity == '5DB5BC51-A860-44CA-93CA-09AE85812DF0':
                raise InstallerValidationError('Acceptance identity must differ from production.')
            description = 'SAP Lens Acceptance ' + identity
        if metadata.get('FileDescription') != description:
            raise InstallerValidationError('Installer production/test identity resource differs.')
        if metadata.get('ProductName')!='SAP Lens':
            raise InstallerValidationError('Installer ProductName differs from SAP Lens.')
        if metadata.get('ProductVersion')!=expected['version']:
            raise InstallerValidationError('Installer ProductVersion differs from the validated build identity.')
        versions=getattr(pe,'VS_FIXEDFILEINFO',[])
        if len(versions)!=1:raise InstallerValidationError('Installer must contain one fixed version resource.')
        fixed=versions[0]
        numbers=[fixed.FileVersionMS>>16,fixed.FileVersionMS&65535,fixed.FileVersionLS>>16,fixed.FileVersionLS&65535]
        if numbers!=expected['file_version']:raise InstallerValidationError('Installer numeric file version differs.')
        product=[fixed.ProductVersionMS>>16,fixed.ProductVersionMS&65535,fixed.ProductVersionLS>>16,fixed.ProductVersionLS&65535]
        if product!=expected['file_version']:raise InstallerValidationError('Installer numeric product version differs.')
        print('Installer PE resources/version verified; signing disabled. Native installed-payload checks remain mandatory.')
    finally:pe.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--installer',type=Path,required=True)
    parser.add_argument('--acceptance-id')
    parser.add_argument('--payload-sha256', help='verify against the build identity bound to this payload executable instead of the current checkout identity')
    parser.add_argument('--compiler-fixture-channel',choices=['alpha','beta','rc','stable'])
    args=parser.parse_args()
    try:
        expected=None
        if args.compiler_fixture_channel:
            from version import make_deployment_info
            expected=make_deployment_info('0.1.0',args.compiler_fixture_channel,'1','a'*40,'1','1',1)
        if args.payload_sha256:
            if args.compiler_fixture_channel: raise InstallerValidationError('--payload-sha256 and --compiler-fixture-channel are exclusive.')
            expected = bound_identity(args.payload_sha256)
        verify(args.installer,expected,args.acceptance_id)
        if expected is not None:print('Compiler fixture only; no application payload or native installation was accepted.')
    except InstallerValidationError as error:parser.exit(1,'Installer verification failed: '+str(error)+'\n')
    except Exception as error:parser.exit(1,'Installer verification failed ('+type(error).__name__+'); private details omitted.\n')


if __name__=='__main__':main()
