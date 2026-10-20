"""Windows per-session single-instance ownership and existing-window activation."""
import ctypes
from ctypes import wintypes


class WindowsInstance:
    def __init__(self, kernel=None):
        self.kernel = kernel or ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = None

    def acquire(self) -> bool:
        self.handle = self.kernel.CreateMutexW(None, False, 'Local\\SAPLensDesktop')
        if not self.handle:
            raise OSError('Cannot create the application instance lock')
        # GetLastError must be read immediately after CreateMutexW.
        return ctypes.get_last_error() != 183

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def activate_existing_window() -> bool:
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    window = user.FindWindowW(None, 'SAP Lens')
    if not window:
        return False
    user.ShowWindow(window, 9)  # SW_RESTORE
    user.SetForegroundWindow(window)
    return True  # Windows may restrict focus stealing; the existing window still owns the app.
