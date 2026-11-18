"""Local container readiness probe; never sends credentials or reads datasets.

With in-container TLS the probe connects to the loopback listener over HTTPS and verifies the configured certificate itself
(pinned as the only trust anchor, with the public host name), so verification is never disabled and no other CA is trusted.
"""
import os
import ssl
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


def probe(environ=os.environ):
    origin = urlsplit(environ.get('SAP_LENS_PUBLIC_ORIGIN', 'http://127.0.0.1:18743'))
    port = environ.get('SAP_LENS_PORT', '18743')
    certificate = environ.get('SAP_LENS_TLS_CERT_FILE', '')
    handlers = [ProxyHandler({})]
    if certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # verifies the chain and the host name
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(certificate)
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN  # the configured certificate is the anchor, also when it is not a CA
        handlers.append(HTTPSHandler(context=context))
        # Connect by the public name so the certificate's SAN is checked; it resolves to the loopback listener through the Host mapping below.
        import socket
        name, original = origin.hostname, socket.getaddrinfo
        def loopback(host, *args, **kwargs):
            return original('127.0.0.1' if host == name else host, *args, **kwargs)
        socket.getaddrinfo = loopback
        url = f'https://{origin.hostname if ":" not in origin.hostname else "[" + origin.hostname + "]"}:{port}/health/ready'
    else:
        url = f'http://127.0.0.1:{port}/health/ready'
    with build_opener(*handlers).open(Request(url, headers={'Host': origin.netloc}), timeout=3) as response:
        return response.status == 200


if __name__ == '__main__':
    raise SystemExit(0 if probe() else 1)
