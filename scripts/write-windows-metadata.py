"""Generate PyInstaller version metadata from the application's version constant."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from version import VERSION


def expected_metadata():
    return {
        'CompanyName': 'SAP Lens contributors',
        'FileDescription': 'SAP Lens Windows Desktop',
        'FileVersion': VERSION,
        'InternalName': 'SAP-Lens',
        'OriginalFilename': 'SAP-Lens.exe',
        'ProductName': 'SAP Lens',
        'ProductVersion': VERSION,
    }


def main():
    numbers = tuple(int(part) for part in VERSION.split('.')) + (0,)
    if len(numbers) != 4 or any(not 0 <= part <= 65535 for part in numbers):
        raise ValueError('Application version must have three valid PE version components.')
    output = ROOT / 'backend' / 'build' / 'version-info.txt'
    output.parent.mkdir(parents=True, exist_ok=True)
    strings = ',\n    '.join(f'StringStruct({key!r}, {value!r})' for key, value in expected_metadata().items())
    output.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    {strings}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding='utf-8')
    print('Windows version metadata generated.')


if __name__ == '__main__':
    main()
