"""Installer resource checks supplement, never replace, portable payload verification."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


class InstallerValidationError(ValueError):
    """Only fixed, nonprivate diagnostics may be shown in build logs."""


def verify(path, expected=None):
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
    parser.add_argument('--compiler-fixture-channel',choices=['alpha','beta','rc','stable'])
    args=parser.parse_args()
    try:
        expected=None
        if args.compiler_fixture_channel:
            from version import make_deployment_info
            expected=make_deployment_info('0.1.0',args.compiler_fixture_channel,'1','a'*40,'1','1',1)
        verify(args.installer,expected)
        if expected is not None:print('Compiler fixture only; no application payload or native installation was accepted.')
    except InstallerValidationError as error:parser.exit(1,'Installer verification failed: '+str(error)+'\n')
    except Exception as error:parser.exit(1,'Installer verification failed ('+type(error).__name__+'); private details omitted.\n')


if __name__=='__main__':main()
