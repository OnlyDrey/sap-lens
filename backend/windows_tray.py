"""Windows Desktop-only notification icon. No GUI/service imports outside this host.

The adapter owns one hidden Win32 message window on its own thread. The controller
owns policy; it never creates another backend or changes the loopback boundary.
"""
import ctypes
from ctypes import wintypes as w
from contextlib import contextmanager
import logging
from pathlib import Path
import subprocess
import sys
import threading

log = logging.getLogger('desktop')


class Win32Tray:
    CALLBACK = 0x8000 + 37
    UPDATE = CALLBACK + 1
    ITEMS = ('Open SAP Lens', 'Open Web Interface', 'Refresh Data Sources', 'Settings', 'Exit SAP Lens')

    def __init__(self, icon, actions):
        self.icon_path = str(icon)
        self.actions = actions
        self.status = 'Starting'
        self.operational = False
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.error = None
        self.hwnd = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name='sap-lens-tray', daemon=True)
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            self.stop()
            raise RuntimeError('Windows notification area is unavailable. Normal window closing is retained.')

    @property
    def alive(self):
        return bool(self.thread and self.thread.is_alive() and not self.error and not self.stopping.is_set())

    def update(self, status, operational):
        self.status, self.operational = status, operational
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, self.UPDATE, 0, 0)

    def stop(self):
        self.stopping.set()
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, 0x10, 0, 0)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)

    def _run(self):
        icon = None
        registered = False
        try:
            user = self.user = ctypes.WinDLL('user32', use_last_error=True)
            shell = ctypes.WinDLL('shell32', use_last_error=True)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            result = ctypes.c_ssize_t
            callback = ctypes.WINFUNCTYPE(result, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

            class WindowClass(ctypes.Structure):
                _fields_ = [('style', w.UINT), ('proc', callback), ('class_extra', ctypes.c_int),
                            ('window_extra', ctypes.c_int), ('instance', w.HINSTANCE),
                            ('icon', w.HICON), ('cursor', w.HANDLE), ('background', w.HANDLE),
                            ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]

            class Guid(ctypes.Structure):
                _fields_ = [('a', w.DWORD), ('b', w.WORD), ('c', w.WORD), ('d', ctypes.c_byte * 8)]

            class Notification(ctypes.Structure):
                _fields_ = [('size', w.DWORD), ('window', w.HWND), ('id', w.UINT), ('flags', w.UINT),
                            ('message', w.UINT), ('icon', w.HICON), ('tip', w.WCHAR * 128),
                            ('state', w.DWORD), ('mask', w.DWORD), ('info', w.WCHAR * 256),
                            ('timeout', w.UINT), ('title', w.WCHAR * 64), ('info_flags', w.DWORD),
                            ('guid', Guid), ('balloon_icon', w.HICON)]

            def declare(dll, name, args, returns):
                method = getattr(dll, name)
                method.argtypes, method.restype = args, returns
                return method

            declare(kernel, 'GetModuleHandleW', [w.LPCWSTR], w.HINSTANCE)
            declare(user, 'RegisterClassW', [ctypes.POINTER(WindowClass)], w.ATOM)
            declare(user, 'UnregisterClassW', [w.LPCWSTR, w.HINSTANCE], w.BOOL)
            declare(user, 'CreateWindowExW', [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND,
                    w.HMENU, w.HINSTANCE, ctypes.c_void_p], w.HWND)
            declare(user, 'DefWindowProcW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], result)
            declare(user, 'PostMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL)
            declare(user, 'DestroyWindow', [w.HWND], w.BOOL)
            declare(user, 'GetMessageW', [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], ctypes.c_int)
            declare(user, 'TranslateMessage', [ctypes.POINTER(w.MSG)], w.BOOL)
            declare(user, 'DispatchMessageW', [ctypes.POINTER(w.MSG)], result)
            declare(user, 'PostQuitMessage', [ctypes.c_int], None)
            declare(user, 'LoadImageW', [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT], w.HANDLE)
            declare(user, 'DestroyIcon', [w.HICON], w.BOOL)
            declare(user, 'RegisterWindowMessageW', [w.LPCWSTR], w.UINT)
            declare(user, 'CreatePopupMenu', [], w.HMENU)
            declare(user, 'AppendMenuW', [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR], w.BOOL)
            declare(user, 'GetCursorPos', [ctypes.POINTER(w.POINT)], w.BOOL)
            declare(user, 'SetForegroundWindow', [w.HWND], w.BOOL)
            declare(user, 'TrackPopupMenu', [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, w.HWND, ctypes.c_void_p], w.UINT)
            declare(user, 'DestroyMenu', [w.HMENU], w.BOOL)
            declare(shell, 'Shell_NotifyIconW', [w.DWORD, ctypes.POINTER(Notification)], w.BOOL)
            instance = kernel.GetModuleHandleW(None)
            class_name = 'SAPLensNotificationArea'
            taskbar_created = user.RegisterWindowMessageW('TaskbarCreated')
            note = Notification()

            def notify(operation):
                note.tip = ('SAP Lens — ' + self.status)[:127]
                return shell.Shell_NotifyIconW(operation, ctypes.byref(note))

            def invoke(index):
                # Window/HTTP work must not block the native notification message pump.
                def action():
                    try:
                        self.actions[self.ITEMS[index]]()
                    except Exception:
                        log.warning('Tray operation unsuccessful; application data retained')
                threading.Thread(target=action, name='sap-lens-tray-action', daemon=True).start()

            def menu():
                handle = user.CreatePopupMenu()
                if not handle:
                    raise OSError('Tray menu unavailable')
                try:
                    user.AppendMenuW(handle, 1, 0, 'SAP Lens — ' + self.status)
                    for index, label in enumerate(self.ITEMS):
                        disabled = index in (1, 2) and not self.operational
                        user.AppendMenuW(handle, 1 if disabled else 0, index + 1, label)
                    point = w.POINT()
                    if not user.GetCursorPos(ctypes.byref(point)):
                        return
                    user.SetForegroundWindow(self.hwnd)
                    selected = user.TrackPopupMenu(handle, 0x182, point.x, point.y, 0, self.hwnd, None)
                    user.PostMessageW(self.hwnd, 0, 0, 0)
                    if 1 <= selected <= len(self.ITEMS):
                        invoke(selected - 1)
                finally:
                    user.DestroyMenu(handle)

            @callback
            def procedure(hwnd, message, wp, lp):
                try:
                    if message == self.CALLBACK:
                        if lp == 0x203:  # WM_LBUTTONDBLCLK
                            invoke(0)
                        elif lp == 0x205:  # WM_RBUTTONUP
                            menu()
                        return 0
                    if message == 0x11:  # WM_QUERYENDSESSION: never veto sign-out/shutdown.
                        return 1
                    if message == 0x16 and wp:  # WM_ENDSESSION
                        invoke(4)
                        return 0
                    if message == self.UPDATE:
                        if not notify(1):
                            self.error = 'Windows notification icon unavailable'
                            user.PostQuitMessage(0)
                        return 0
                    if taskbar_created and message == taskbar_created:
                        if not notify(0):  # Restore the icon, never another backend.
                            self.error = 'Windows notification icon unavailable'
                            user.PostQuitMessage(0)
                        return 0
                    if message == 0x10:
                        notify(2)
                        user.DestroyWindow(hwnd)
                        return 0
                    if message == 2:
                        user.PostQuitMessage(0)
                        return 0
                except Exception:
                    self.error='Windows tray operation unavailable'
                    user.PostQuitMessage(0)
                    log.warning('Tray notification handler unsuccessful')
                return user.DefWindowProcW(hwnd, message, wp, lp)

            window_class = WindowClass()
            window_class.proc, window_class.instance, window_class.name = procedure, instance, class_name
            if not user.RegisterClassW(ctypes.byref(window_class)):
                raise OSError('Notification window class unavailable')
            registered = True
            self.hwnd = user.CreateWindowExW(0, class_name, 'SAP Lens tray', 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise OSError('Notification window unavailable')
            icon = user.LoadImageW(None, self.icon_path, 1, 0, 0, 0x50)
            if not icon:
                raise OSError('Application icon unavailable')
            note.size, note.window, note.id = ctypes.sizeof(note), self.hwnd, 1
            note.flags, note.message, note.icon = 7, self.CALLBACK, icon
            if self.stopping.is_set() or not notify(0):
                raise OSError('Notification icon unavailable')
            self.ready.set()
            message = w.MSG()
            while not self.stopping.is_set():
                received = user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if received <= 0:
                    break
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        except Exception:
            self.error = 'Windows notification area unavailable'
            log.warning('Windows tray initialization unsuccessful; normal close retained')
        finally:
            if self.hwnd:
                shell.Shell_NotifyIconW(2, ctypes.byref(note))
                user.DestroyWindow(self.hwnd)
                self.hwnd = None
            if icon:
                user.DestroyIcon(icon)
            if registered:
                user.UnregisterClassW(class_name, instance)
            self.ready.set()


class StartupRegistration:
    """Current-user sign-in launch only; no service, elevation or credentials."""
    NAME = 'SAPLensDesktop'
    KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

    def __init__(self, registry=None, executable=None, packaged=None):
        if registry is None:
            import winreg
            registry = winreg
        self.registry = registry
        self.executable = executable or sys.executable
        self.packaged = bool(getattr(sys, 'frozen', False)) if packaged is None else packaged

    def read(self):
        r = self.registry
        try:
            with r.OpenKey(r.HKEY_CURRENT_USER, self.KEY, 0, r.KEY_READ) as key:
                return r.QueryValueEx(key, self.NAME)
        except FileNotFoundError:
            return None

    def write(self, enabled):
        if enabled and not self.packaged:
            raise ValueError('Windows sign-in startup requires the packaged SAP Lens EXE.')
        value = (subprocess.list2cmdline([self.executable]), self.registry.REG_SZ) if enabled else None
        self.restore(value)

    def restore(self, value):
        r = self.registry
        with r.CreateKeyEx(r.HKEY_CURRENT_USER, self.KEY, 0, r.KEY_SET_VALUE) as key:
            if value is None:
                try:
                    r.DeleteValue(key, self.NAME)
                except FileNotFoundError:
                    pass
            else:
                r.SetValueEx(key, self.NAME, 0, value[1], value[0])


class DesktopBackground:
    def __init__(self, window, icon, preferences, origin, refresh, startup=None, tray_factory=Win32Tray):
        self.window, self.icon, self.preferences = window, icon, preferences
        self.origin, self.refresh = origin, refresh
        self.startup = startup or StartupRegistration()
        self.tray_factory = tray_factory
        self.tray = None
        self.exiting = False
        self.operational = False
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.last_error = None
        self.settings_requested = False
        self._session_end_handler = None

    def check_tray(self):
        tray = self.tray
        if tray and not tray.alive:
            self.last_error = 'Windows tray unavailable; normal closing is active.'
            self.restore()
            tray.stop()
            if self.tray is tray: self.tray = None

    def ensure_tray(self):
        with self.lock:
            if self.exiting: raise ValueError('SAP Lens is exiting.')
            if self.tray:
                return
            try:
                tray = self.tray_factory(self.icon, {
                    'Open SAP Lens': self.restore,
                    'Open Web Interface': self.open_web,
                    'Refresh Data Sources': self.refresh_sources,
                    'Settings': self.open_settings,
                    'Exit SAP Lens': self.exit,
                })
                tray.start()
                if self.exiting:
                    tray.stop()
                    raise ValueError('SAP Lens is exiting.')
            except Exception:
                self.last_error = 'Windows notification area unavailable; normal window closing is retained.'
                raise ValueError(self.last_error) from None
            self.tray = tray
            self.last_error = None
            log.info('Windows notification icon initialized')
            tray.update('Ready' if self.operational else 'Starting', self.operational)

    def restore(self):
        if self.exiting: return
        self.window.show()
        self.window.restore()

    def open_web(self):
        if self.operational and not self.exiting:
            import webbrowser
            webbrowser.open(self.origin)  # Plain owned root performs the existing guarded handoff.

    def attach_native_session_end(self):
        # pywebview's cancellable closing event omits CloseReason. Its existing
        # WinForms host supplies it, so allow session shutdown after that callback.
        def allow_session_end(sender, args):
            if str(args.CloseReason) in ('WindowsShutDown', 'TaskManagerClosing'):
                self.exiting = True
                args.Cancel = False
        self._session_end_handler = allow_session_end
        self.window.native.FormClosing += allow_session_end

    def open_settings(self):
        self.settings_requested = True
        self.restore()
        if self.operational:
            delivered = self.window.evaluate_js("(()=>{if(!window.__sapLensSettingsReady)return false;window.dispatchEvent(new Event('sap-lens-open-settings'));return true})()")
            if delivered:
                self.settings_requested = False

    def frontend_loaded(self):
        if self.settings_requested:
            self.open_settings()

    def refresh_sources(self):
        tray = self.tray
        if self.exiting or not self.operational or not tray or not tray.alive or not self.refresh_lock.acquire(blocking=False):
            return
        try:
            tray.update('Refreshing data sources', True)
            self.refresh()
            tray.update('Ready', True)
        except Exception:
            tray.update('Refresh failed; previous valid data retained', True)
            log.warning('Tray source refresh unsuccessful; application data retained')
        finally:
            self.refresh_lock.release()

    def loaded(self):
        if self.preferences().close_to_tray:
            self.ensure_tray()
            if self.preferences().start_minimized:
                self.window.hide()

    def ready_backend(self):
        self.operational = True
        if self.tray:
            self.tray.update('Ready', True)

    def failed_backend(self):
        self.operational = False
        if self.tray:
            self.tray.update('Backend unavailable — exit and reopen SAP Lens', False)
            self.restore()

    def on_closing(self):
        tray = self.tray
        if not self.exiting and tray and tray.alive and self.operational and self.preferences().close_to_tray:
            self.window.hide()
            log.info('Desktop window hidden; owned backend retained')
            return False
        return True

    def exit(self):
        log.info('Explicit desktop exit requested')
        self.exiting = True
        self.window.destroy()

    def shutdown(self):
        self.exiting = True
        if self.tray:
            self.tray.stop()
            self.tray = None

    @contextmanager
    def preferences_change(self, before, after):
        with self.lock:
            created = not self.tray and after.close_to_tray
            previous_startup = self.startup.read() if before.run_at_signin != after.run_at_signin else None
            startup_changed = False
            try:
                if created:
                    self.ensure_tray()
                if before.run_at_signin != after.run_at_signin:
                    try:
                        self.startup.write(after.run_at_signin)
                    except OSError:
                        self.last_error='Windows sign-in startup could not be configured. Check current-user registry permissions or organization policy.'
                        raise
                    startup_changed = True
                yield
                if before != after and self.preferences() != after:
                    raise ValueError('Desktop preferences were not published; startup registration is unchanged.')
            except BaseException:
                if startup_changed:
                    self.startup.restore(previous_startup)
                if created and self.tray:
                    self.tray.stop()
                    self.tray = None
                raise
            else:
                if not after.close_to_tray and self.tray:
                    self.restore()
                    self.tray.stop()
                    self.tray = None
