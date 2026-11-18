"""HTTPS session client for the disposable Docker acceptance scripts.

The server certificate is always verified: the installation's own certificate file is the only trust anchor and the host name is checked.
Nothing here disables TLS verification, sends Basic credentials or reads real data.
"""
import http.client
import json
import ssl
import subprocess

PASSWORD = 'Synthetic container password 123!'


class Session:
    def __init__(self, port, certificate, host='localhost'):
        self.port, self.host, self.cookies = port, host, {}
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(str(certificate))
        self.context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN

    def request(self, method, path, body=None, headers=None, cookies=True):
        connection = http.client.HTTPSConnection('127.0.0.1', self.port, timeout=10, context=self.context)
        head = {'X-SAP-Lens': '1', 'Content-Type': 'application/json', 'Host': f'{self.host}:{self.port}', **(headers or {})}
        if cookies and self.cookies:
            head['Cookie'] = '; '.join(f'{name}={value}' for name, value in self.cookies.items())
            if method != 'GET' and 'sap-lens-csrf' in self.cookies: head.setdefault('X-SAP-Lens-CSRF', self.cookies['sap-lens-csrf'])
        try:
            connection.request(method, path, json.dumps(body) if isinstance(body, dict) else body, headers=head)
            response = connection.getresponse(); raw = response.read()
            for line in response.headers.get_all('Set-Cookie') or []:
                name, _, value = line.split(';', 1)[0].partition('=')
                if value and value != '""': self.cookies[name.strip()] = value
                else: self.cookies.pop(name.strip(), None)
                if name.strip() == 'sap-lens-session':
                    flags = line.lower()
                    if 'httponly' not in flags or 'secure' not in flags or 'samesite=lax' not in flags: raise ValueError('Session cookie is missing HttpOnly, Secure or SameSite.')
            return response.status, raw
        finally: connection.close()

    def json(self, method, path, body=None, expect=200, **options):
        status, raw = self.request(method, path, body, **options)
        if status != expect: raise ValueError(f'{method} {path}: expected {expect}, got {status}.')
        return json.loads(raw) if raw else None

    def plain_http_is_refused(self):
        """The listener speaks TLS only: a plain HTTP request gets no application answer."""
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request('GET', '/api/auth/state', headers={'Host': f'{self.host}:{self.port}'})
            return connection.getresponse().status >= 400
        except (OSError, http.client.HTTPException): return True
        finally: connection.close()


def activate(session, issue_code, username='admin'):
    """First-run activation as an operator does it: a locally issued one-time code, then the account, then sign-in."""
    if session.json('GET', '/api/auth/state')['setup_required'] is not True: raise ValueError('A fresh installation must require setup.')
    if session.request('POST', '/api/auth/activate', dict(code='x' * 43, username=username, display_name='Synthetic Administrator', password=PASSWORD))[0] != 401:
        raise ValueError('An invented activation code was accepted.')
    code = json.loads(issue_code())['code']
    session.json('POST', '/api/auth/activate', dict(code=code, username=username, display_name='Synthetic Administrator', password=PASSWORD))
    if session.request('POST', '/api/auth/activate', dict(code=code, username='second', display_name='Second', password=PASSWORD))[0] not in {401, 409}:
        raise ValueError('The activation code was accepted twice.')
    if session.json('GET', '/api/auth/state')['setup_required'] is not False: raise ValueError('Setup stayed open after activation.')
    sign_in(session, username)


def sign_in(session, username='admin', password=PASSWORD):
    session.cookies.clear()
    session.json('POST', '/api/auth/login', dict(username=username, password=password))
    return session.json('GET', '/api/auth/me')


def docker(*args, **options):
    return subprocess.check_output(['docker', *map(str, args)], text=True, **options).strip()
