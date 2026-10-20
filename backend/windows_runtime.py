"""Check the Evergreen WebView2 registration before pywebview can fall back to IE."""

def webview2_available(registry=None) -> bool:
    if registry is None:
        import winreg as registry
    client = r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for hive in (registry.HKEY_CURRENT_USER, registry.HKEY_LOCAL_MACHINE):
        for view in (registry.KEY_WOW64_32KEY, registry.KEY_WOW64_64KEY):
            try:
                with registry.OpenKey(hive, client, 0, registry.KEY_READ | view) as key:
                    version, _ = registry.QueryValueEx(key, 'pv')
                if tuple(int(part) for part in version.split('.')) >= (86, 0, 622, 0):
                    return True
            except (OSError, ValueError, TypeError):
                continue
    return False
