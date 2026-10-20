"""Generate PyInstaller version metadata from the application's version constant."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from version import VERSION


def main():
    numbers = tuple(int(part) for part in VERSION.split('.')) + (0,)
    assert len(numbers) == 4
    output = ROOT / 'backend' / 'build' / 'version-info.txt'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Company'),
    StringStruct('FileDescription', 'SAP Lens Windows Desktop'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('InternalName', 'SAP-Lens'),
    StringStruct('OriginalFilename', 'SAP-Lens.exe'),
    StringStruct('ProductName', 'SAP Lens'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
''', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
