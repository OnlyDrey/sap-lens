"""Local container readiness probe; never sends credentials or reads datasets."""
import os
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

if __name__=='__main__':
    origin=urlsplit(os.environ.get('SAP_LENS_PUBLIC_ORIGIN','http://127.0.0.1:18743'))
    request=Request('http://127.0.0.1:'+os.environ.get('SAP_LENS_PORT','18743')+'/health/ready',headers={'Host':origin.netloc})
    with build_opener(ProxyHandler({})).open(request,timeout=3) as response:
        if response.status!=200: raise SystemExit(1)
