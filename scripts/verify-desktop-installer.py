"""Installer resource checks supplement, never replace, portable payload verification."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def verify(path):
    import pefile
    from version import BUILD_INFO
    pe=pefile.PE(str(path))
    try:
        if pe.OPTIONAL_HEADER.Subsystem != 2: raise ValueError('Installer must use the Windows GUI subsystem.')
        directory=pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']]
        if directory.VirtualAddress or directory.Size:raise ValueError('Signing must remain disabled.')
        metadata={}
        for group in getattr(pe,'FileInfo',[]):
            for entry in group:
                for table in getattr(entry,'StringTable',[]):
                    for key,value in table.entries.items():metadata[key.decode('utf-8')]=value.decode('utf-8')
        if metadata.get('ProductName')!='SAP Lens' or metadata.get('ProductVersion')!=BUILD_INFO['version']:
            raise ValueError('Installer product identity differs from the validated package.')
        fixed=pe.VS_FIXEDFILEINFO[0]
        numbers=[fixed.FileVersionMS>>16,fixed.FileVersionMS&65535,fixed.FileVersionLS>>16,fixed.FileVersionLS&65535]
        if numbers!=BUILD_INFO['file_version']:raise ValueError('Installer numeric version differs.')
        product=[fixed.ProductVersionMS>>16,fixed.ProductVersionMS&65535,fixed.ProductVersionLS>>16,fixed.ProductVersionLS&65535]
        if product!=BUILD_INFO['file_version']:raise ValueError('Installer numeric product version differs.')
        print('Installer PE resources/version verified; signing disabled. Native installed-payload checks remain mandatory.')
    finally:pe.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--installer',type=Path,required=True)
    try:verify(parser.parse_args().installer)
    except Exception as error:parser.exit(1,'Installer verification failed ('+type(error).__name__+'); private details omitted.\n')
