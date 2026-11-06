"""Native Windows identity and private-ACL helpers (ctypes, no subprocess).

Backup, restore and state files are made private to the running user and SYSTEM. This used to start `powershell` (to read the SID) and `icacls.exe`
for every file: a restore of hundreds of files, or each progress write of a backup, opened a visible console window per call. These helpers call
the same Windows APIs in-process instead:

* `current_user_sid()` reads the SID of the effective identity (the impersonation token of the calling thread if there is one, otherwise the
  process token), so a service account, an elevated desktop user and an impersonated thread each get their own SID. Nothing is cached: the call is a
  few microseconds and an identity can differ between contexts.
* `make_private(path)` replaces the DACL with a protected one granting full control to that SID and SYSTEM only, which is what
  `icacls /inheritance:r /grant:r <sid>:F SYSTEM:F` did.

Failures raise `WindowsIdentityError` naming the API and the Windows error code; there is never a substitute identity or a silent skip."""
import ctypes
import re
from types import SimpleNamespace
from ctypes import wintypes

TOKEN_QUERY = 0x0008
TOKEN_USER = 1
ERROR_NO_TOKEN = 1008
ERROR_INSUFFICIENT_BUFFER = 122
SDDL_REVISION_1 = 1
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SID_FORMAT = re.compile(r'S-1-\d+(?:-\d+)+')


class WindowsIdentityError(OSError):
    """A Windows identity or security API failed. The message names the API and the Windows error code."""


def _load():
    advapi32, kernel32 = ctypes.WinDLL('advapi32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentThread.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenThreadToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenThreadToken.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    return SimpleNamespace(advapi32=advapi32, kernel32=kernel32, last_error=ctypes.get_last_error)


def _fail(api, name):
    return WindowsIdentityError(f'{name} failed (Windows error {api.last_error()}).')


def current_user_sid(api=None):
    """SID string (for example S-1-5-21-...-1001) of the effective identity of the calling thread. Raises WindowsIdentityError; never guesses."""
    api = api or _load()
    token = wintypes.HANDLE()
    # An impersonating thread's identity wins; with none (ERROR_NO_TOKEN) the process token is the effective identity.
    if not api.advapi32.OpenThreadToken(api.kernel32.GetCurrentThread(), TOKEN_QUERY, True, ctypes.byref(token)):
        if api.last_error() != ERROR_NO_TOKEN:
            raise _fail(api, 'OpenThreadToken')
        if not api.advapi32.OpenProcessToken(api.kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            raise _fail(api, 'OpenProcessToken')
    try:
        size = wintypes.DWORD(0)
        api.advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
        if size.value == 0 or api.last_error() != ERROR_INSUFFICIENT_BUFFER:
            raise _fail(api, 'GetTokenInformation(size)')
        buffer = ctypes.create_string_buffer(size.value)
        if not api.advapi32.GetTokenInformation(token, TOKEN_USER, buffer, size, ctypes.byref(size)):
            raise _fail(api, 'GetTokenInformation')
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]   # TOKEN_USER starts with SID_AND_ATTRIBUTES { PSID Sid; DWORD Attributes }
        text = wintypes.LPWSTR()
        if not api.advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise _fail(api, 'ConvertSidToStringSidW')
        try:
            value = text.value
        finally:
            api.kernel32.LocalFree(text)
    finally:
        api.kernel32.CloseHandle(token)
    if not value or not SID_FORMAT.fullmatch(value):
        raise WindowsIdentityError('The Windows identity returned an unexpected SID format.')
    return value


def private_sddl(sid, inherit_children=False):
    """Protected DACL: full control for `sid` and SYSTEM only. Containers also pass it to new children (OI/CI)."""
    flags = 'OICI' if inherit_children else ''
    return f'D:P(A;{flags};FA;;;{sid})(A;{flags};FA;;;SY)'


def make_private(path, inherit_children=False, api=None):
    """Make a file or directory private to the effective user and SYSTEM (inheritance removed). In-process; raises WindowsIdentityError on failure."""
    api = api or _load()
    apply_sddl(path, private_sddl(current_user_sid(api), inherit_children), api)


def apply_sddl(path, sddl, api=None):
    """Replace the DACL of `path` with the one described by `sddl` (inheritance removed when the SDDL is protected)."""
    api = api or _load()
    descriptor = ctypes.c_void_p()
    if not api.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None):
        raise _fail(api, 'ConvertStringSecurityDescriptorToSecurityDescriptorW')
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not api.advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present.value:
            raise _fail(api, 'GetSecurityDescriptorDacl')
        result = api.advapi32.SetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION, None, None, dacl, None)
        if result:
            raise WindowsIdentityError(f'SetNamedSecurityInfoW failed (Windows error {result}).')
    finally:
        api.kernel32.LocalFree(descriptor)


#: Principals that stand for "other users" in SDDL: Everyone, Users, Authenticated Users, Interactive, Network, Anonymous, Guests.
BROAD_PRINCIPALS = {'WD': 'Everyone', 'BU': 'Users', 'AU': 'Authenticated Users', 'IU': 'Interactive', 'NU': 'Network', 'AN': 'Anonymous', 'BG': 'Guests',
                    'S-1-1-0': 'Everyone', 'S-1-5-32-545': 'Users', 'S-1-5-11': 'Authenticated Users', 'S-1-5-4': 'Interactive', 'S-1-5-2': 'Network',
                    'S-1-5-7': 'Anonymous', 'S-1-5-32-546': 'Guests'}

def _grants_content_access(rights):
    if rights.lower().startswith('0x'):
        return bool(int(rights, 16) & (0x1 | 0x2 | 0x4 | 0x10000000 | 0x80000000 | 0x40000000 | 0x1F01FF | 0x120089))
    return any(code in ('GR', 'GW', 'GA', 'FR', 'FW', 'FA') for code in re.findall(r'[A-Z]{2}', rights))


def broad_access(sddl):
    """Names of broad principals (Everyone, Users, Authenticated Users, ...) that an SDDL DACL allows to read or change the file. Pure and testable."""
    dacl = sddl.split('D:', 1)[1] if 'D:' in sddl else ''
    dacl = dacl.split('S:', 1)[0]
    found = []
    for ace in re.findall(r'\(([^)]*)\)', dacl):
        parts = ace.split(';')
        if len(parts) < 6 or parts[0] != 'A':
            continue                                                   # only ACCESS_ALLOWED entries grant; deny entries never widen access
        name = BROAD_PRINCIPALS.get(parts[5].upper())
        if name and _grants_content_access(parts[2]) and name not in found:
            found.append(name)
    return found


def file_sddl(path, api=None):
    api = api or _load()
    descriptor = ctypes.c_void_p()
    result = api.advapi32.GetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None, None, None, ctypes.byref(descriptor))
    if result:
        raise WindowsIdentityError(f'GetNamedSecurityInfoW failed (Windows error {result}).')
    try:
        text = wintypes.LPWSTR()
        if not api.advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, SDDL_REVISION_1, DACL_SECURITY_INFORMATION, ctypes.byref(text), None):
            raise _fail(api, 'ConvertSecurityDescriptorToStringSecurityDescriptorW')
        try:
            return text.value
        finally:
            api.kernel32.LocalFree(text)
    finally:
        api.kernel32.LocalFree(descriptor)


def exposed_to_other_users(path, api=None):
    """Broad principals with access to `path` (empty list = not exposed through well-known broad groups). Raises WindowsIdentityError when the ACL cannot be read."""
    return broad_access(file_sddl(path, api))
