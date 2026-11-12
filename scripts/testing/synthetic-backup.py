"""Emit a disposable synthetic backup for browser tests, never from user storage."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from config_models import AppConfig
from desktop_test_mutex import desktop_mutex_patch
from instance import WindowsInstance
from maintenance import backup
from version import VERSION


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        data = root / 'data'
        data.mkdir()
        os.environ.update(SAP_LENS_CONFIG_DIR=str(data), SAP_LENS_DATA_DIR=str(data),
                          SAP_LENS_DEPLOYMENT_MODE='desktop', DATA_CSV_PATH='')
        (data / 'deployment.json').write_text(json.dumps(dict(version=1, mode='desktop')), encoding='utf-8')
        (data / 'settings.json').write_text(AppConfig().model_dump_json(), encoding='utf-8')
        target = root / 'exports' / 'synthetic.tar.gz'
        with desktop_mutex_patch(WindowsInstance):
            backup(data, target, 'desktop', VERSION)
        if '--encrypted' in sys.argv:
            from backup_crypto import create_key,plan,unwrap,seal,host_key
            key=root/'synthetic.key';create_key(key,data)
            os.environ['SAP_LENS_BACKUP_KEY_FILE']=str(key)
            secret=sys.stdin.readline(4098).rstrip('\r\n')
            planned=plan('synthetic-browser',host_key(data),secret)
            derived,header=unwrap('synthetic-browser',planned,host_key(data))
            encrypted=root/'synthetic.slbak';seal(target,encrypted,derived,header);target=encrypted
        sys.stdout.buffer.write(target.read_bytes())


if __name__ == '__main__':
    main()
