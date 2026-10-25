"""Read administrator-owned EnvironmentFile values without executing shell code."""
import argparse
import os
from pathlib import Path
import shlex
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def configure(path):
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,separator,value=line.partition('=')
        if not separator or not key.startswith('SAP_LENS_') or not key.replace('_','').isalnum():raise ValueError('Invalid server environment entry.')
        parsed=shlex.split(value)
        if len(parsed)>1:raise ValueError('Quote environment values containing spaces.')
        os.environ[key]=parsed[0] if parsed else ''
    os.environ['SAP_LENS_DEPLOYMENT_MODE']='server'
    from deployment import ServerSettings
    return ServerSettings.from_env()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env',required=True,type=Path);p.add_argument('--check',action='store_true');a=p.parse_args()
    try:
        configure(a.env)
        if not a.check:
            from server import run
            sys.argv=[sys.argv[0]]
            sys.exit(run())
    except (OSError,ValueError):p.exit(1,'Invalid server configuration; private details omitted.\n')
