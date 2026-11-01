"""Synthetic desktop policy/registry contracts. No native SCM/WebView/Win32 claim."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config_models import DesktopPreferences, AppConfig
from windows_tray import DesktopBackground,StartupRegistration


class FakeTray:
    def __init__(self,icon,actions):
        self.actions=actions;self.alive=False;self.updates=[];self.stopped=0
    def start(self):self.alive=True
    def update(self,status,operational):self.updates.append((status,operational))
    def stop(self):self.alive=False;self.stopped+=1


class Registry:
    HKEY_CURRENT_USER=1;KEY_READ=2;KEY_SET_VALUE=4;REG_SZ=1
    def __init__(self):self.value=None
    @contextmanager
    def OpenKey(self,*args):yield self
    CreateKeyEx=OpenKey
    def QueryValueEx(self,*args):
        if self.value is None:raise FileNotFoundError()
        return self.value
    def SetValueEx(self,key,name,reserved,kind,value):self.value=(value,kind)
    def DeleteValue(self,*args):
        if self.value is None:raise FileNotFoundError()
        self.value=None


class TrayPolicyTests(unittest.TestCase):
    def setUp(self):
        self.window=Mock();self.preference=DesktopPreferences();self.refresh=Mock()
        self.registry=Registry();self.startup=StartupRegistration(self.registry,r'C:\Synthetic folder\Å\SAP-Lens.exe',packaged=True)
        self.controller=DesktopBackground(self.window,'synthetic.ico',lambda:self.preference,'http://127.0.0.1:18743',self.refresh,self.startup,FakeTray)

    def enable(self):
        self.preference=DesktopPreferences(close_to_tray=True)
        self.controller.loaded();self.controller.ready_backend()

    def test_defaults_normal_close_and_startup_never_registered_implicitly(self):
        self.controller.loaded();self.controller.ready_backend()
        self.assertIsNone(self.controller.tray);self.assertTrue(self.controller.on_closing());self.assertIsNone(self.registry.value)

    def test_close_hides_only_ready_backend_and_live_icon_then_explicit_exit_closes(self):
        self.enable();self.assertFalse(self.controller.on_closing());self.window.hide.assert_called_once()
        self.controller.tray.actions['Open SAP Lens']();self.window.show.assert_called_once();self.window.restore.assert_called_once()
        self.controller.tray.actions['Exit SAP Lens']();self.window.destroy.assert_called_once();self.assertTrue(self.controller.on_closing())
        tray=self.controller.tray;self.controller.shutdown();self.assertEqual(tray.stopped,1);self.assertIsNone(self.controller.tray)

    def test_start_minimized_initialization_and_failure_restore_are_safe(self):
        self.preference=DesktopPreferences(close_to_tray=True,start_minimized=True)
        self.controller.loaded();self.window.hide.assert_called_once();self.assertTrue(self.controller.on_closing())
        self.controller.ready_backend();self.controller.failed_backend();self.window.show.assert_called_once();self.assertTrue(self.controller.on_closing())
        self.assertFalse(self.controller.tray.updates[-1][1])

    def test_dead_icon_does_not_strand_hidden_window_or_spawn_backend(self):
        self.enable();self.controller.tray.alive=False
        self.assertTrue(self.controller.on_closing());self.controller.check_tray();self.window.show.assert_called_once();self.assertIsNone(self.controller.tray)
        self.assertIn('normal closing',self.controller.last_error)

    def test_exit_during_icon_initialization_cannot_leave_a_late_background_icon(self):
        owner=self.controller;created=[]
        class ClosingTray(FakeTray):
            def start(self):
                super().start();created.append(self);owner.shutdown()
        owner.tray_factory=ClosingTray
        with self.assertRaises(ValueError):owner.ensure_tray()
        self.assertIsNone(owner.tray);self.assertEqual(created[0].stopped,1);self.assertTrue(owner.exiting)

    def test_failed_initial_icon_can_never_cancel_close(self):
        def fail(*args):raise RuntimeError('synthetic notification unavailable')
        self.controller.tray_factory=fail;self.preference=DesktopPreferences(close_to_tray=True)
        with self.assertRaises(ValueError):self.controller.loaded()
        self.assertTrue(self.controller.on_closing());self.assertIsNone(self.controller.tray)

    def test_icon_failure_during_preferences_keeps_configuration_and_native_state(self):
        self.controller.tray_factory=Mock(side_effect=RuntimeError('synthetic icon failure'))
        with self.assertRaises(ValueError):
            with self.controller.preferences_change(self.preference,DesktopPreferences(close_to_tray=True)):
                self.fail('Must not publish preferences without a usable icon')
        self.assertIsNone(self.controller.tray);self.assertIsNone(self.registry.value)

    def test_browser_uses_owned_plain_origin_and_settings_restores_existing_window(self):
        self.enable()
        with patch('webbrowser.open') as browser:
            self.controller.tray.actions['Open Web Interface']();browser.assert_called_once_with('http://127.0.0.1:18743')
        self.controller.open_settings();self.assertIn('sap-lens-open-settings',self.window.evaluate_js.call_args.args[0])

    def test_settings_request_is_delivered_after_frontend_readiness(self):
        self.enable();self.window.evaluate_js.return_value=False
        self.controller.open_settings();self.assertTrue(self.controller.settings_requested)
        self.window.evaluate_js.return_value=True;self.controller.frontend_loaded();self.assertFalse(self.controller.settings_requested)

    def test_session_shutdown_is_not_cancelled_by_hide_on_close(self):
        class ClosingEvent:
            def __iadd__(self, callback):self.callback=callback;return self
        from types import SimpleNamespace
        event=ClosingEvent();self.window.native=SimpleNamespace(FormClosing=event)
        self.controller.attach_native_session_end();self.enable()
        arguments=SimpleNamespace(CloseReason='WindowsShutDown',Cancel=True)
        event.callback(None,arguments);self.assertFalse(arguments.Cancel);self.assertTrue(self.controller.on_closing())

    def test_refresh_gate_and_failure_status_do_not_modify_sources(self):
        self.enable();self.controller.refresh_sources();self.refresh.assert_called_once()
        self.controller.refresh_lock.acquire();self.controller.refresh_sources();self.assertEqual(self.refresh.call_count,1);self.controller.refresh_lock.release()
        self.refresh.side_effect=OSError('synthetic');self.controller.refresh_sources();self.assertIn('previous valid data retained',self.controller.tray.updates[-1][0])
        self.controller.failed_backend();self.controller.refresh_sources();self.assertEqual(self.refresh.call_count,2)

    def test_registry_quotes_spaces_and_unicode_and_removes_only_owned_value(self):
        self.startup.write(True);self.assertEqual(self.registry.value[0],'"C:\\Synthetic folder\\Å\\SAP-Lens.exe"')
        self.startup.write(False);self.assertIsNone(self.registry.value)
        self.startup.packaged=False
        with self.assertRaises(ValueError):self.startup.write(True)

    def test_preferences_rollback_registry_and_icon_when_existing_config_save_fails(self):
        before=self.preference;after=DesktopPreferences(close_to_tray=True,run_at_signin=True)
        self.registry.value=('synthetic previous registration',1)
        with self.assertRaises(OSError):
            with self.controller.preferences_change(before,after):
                self.assertIsNotNone(self.controller.tray);raise OSError('synthetic config publication failed')
        self.assertEqual(self.registry.value,('synthetic previous registration',1));self.assertIsNone(self.controller.tray);self.assertFalse(self.controller.exiting)

    def test_unpublished_configuration_rolls_back_native_effects_even_without_loader_exception(self):
        before=self.preference;after=DesktopPreferences(close_to_tray=True,run_at_signin=True)
        with self.assertRaises(ValueError):
            with self.controller.preferences_change(before,after):
                pass  # Existing loader rejected replacement and retained the old configuration.
        self.assertIsNone(self.registry.value);self.assertIsNone(self.controller.tray)

    def test_disabled_preference_restores_window_and_stops_icon_after_publication(self):
        self.enable();old=self.preference;new=DesktopPreferences()
        tray=self.controller.tray
        with self.controller.preferences_change(old,new):self.preference=new
        self.window.show.assert_called_once();self.assertEqual(tray.stopped,1);self.assertTrue(self.controller.on_closing())

    def test_new_preferences_are_backward_compatible_but_minimized_requires_tray(self):
        self.assertEqual(AppConfig().desktop,DesktopPreferences())
        with self.assertRaises(ValueError):DesktopPreferences(start_minimized=True)


class TrayPersistenceTests(unittest.TestCase):
    def test_actual_config_restart_portable_import_and_native_auth(self):
        import config
        from portable_config import export_configuration
        from main import create_app
        from fastapi.testclient import TestClient
        from desktop import NativeDialogs
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':root,'DATA_CSV_PATH':''}):
            config.get_settings.cache_clear()
            self.addCleanup(config.get_settings.cache_clear)
            value=config.get_settings().model_copy(deep=True);value.desktop=DesktopPreferences(close_to_tray=True,run_at_signin=True,start_minimized=True)
            config.save_configuration(value,value.revision);config.get_settings.cache_clear();self.assertTrue(config.get_settings().desktop.start_minimized)
            package=export_configuration(config.get_settings(),True);self.assertFalse(package['settings']['desktop']['run_at_signin'])
            package['settings']['desktop']={'close_to_tray':False,'run_at_signin':False,'start_minimized':False}
            client=TestClient(create_app(session_token='synthetic-session'),base_url='http://127.0.0.1:18743')
            response=client.post('/api/configuration/import',headers={'X-SAP-Lens':'synthetic-session'},json=package)
            self.assertEqual(response.status_code,200,response.text);self.assertTrue(config.get_settings().desktop.run_at_signin)
            bridge=NativeDialogs('synthetic-capability')
            with self.assertRaises(ValueError):bridge.desktop_runtime('invalid')
            with patch('desktop.is_windows',return_value=False):self.assertFalse(bridge.desktop_runtime('synthetic-capability')['windows'])

    def test_configuration_callback_rolls_back_without_weakening_revision_guards(self):
        import config
        from main import create_app
        from fastapi.testclient import TestClient
        calls=[]
        @contextmanager
        def change(before,after):
            calls.append((before.run_at_signin,after.run_at_signin));yield
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':root,'DATA_CSV_PATH':''}):
            config.get_settings.cache_clear();self.addCleanup(config.get_settings.cache_clear)
            client=TestClient(create_app(session_token='s',desktop_preferences=change),base_url='http://127.0.0.1:18743')
            value=config.get_settings().model_dump(mode='json');value['desktop']={'close_to_tray':True,'run_at_signin':True,'start_minimized':False}
            self.assertEqual(client.post('/api/configuration',headers={'X-SAP-Lens':'s'},json=value).status_code,200)
            self.assertEqual(calls,[(False,True)])
            self.assertEqual(client.post('/api/configuration',headers={'X-SAP-Lens':'s'},json=value).status_code,409)
            self.assertEqual(calls,[(False,True)])

    def test_native_configuration_transactions_do_not_interleave_across_async_validation(self):
        import asyncio
        import config
        from main import create_app
        calls=[]
        @contextmanager
        def change(before,after):
            calls.append(after.run_at_signin);yield
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':root,'DATA_CSV_PATH':''}):
            config.get_settings.cache_clear();self.addCleanup(config.get_settings.cache_clear)
            app=create_app(session_token='s',desktop_preferences=change)
            async def scenario():
                entered=asyncio.Event();release=asyncio.Event()
                async def load(configuration):
                    entered.set();await release.wait();config.save_configuration(configuration,configuration.revision)
                app.state.loader.load=load
                value=config.get_settings().model_dump(mode='json');value['data_csv_path']=str(Path(root)/'synthetic.csv');value['desktop']={'close_to_tray':True,'run_at_signin':True,'start_minimized':False}
                from fastapi import HTTPException
                from configuration_routes import configuration_router
                router=configuration_router(app.state.loader,desktop_preferences=change)
                endpoint=next(route.endpoint for route in router.routes if route.path=='/api/configuration' and 'POST' in route.methods)
                async def send():
                    try:
                        await endpoint(AppConfig.model_validate(value));return 200
                    except HTTPException as error:
                        return error.status_code
                first=asyncio.create_task(send());await entered.wait()
                second=asyncio.create_task(send());await asyncio.sleep(0)
                self.assertEqual(calls,[True]);release.set();statuses=await asyncio.gather(first,second)
                self.assertEqual(statuses,[200,409]);self.assertEqual(calls,[True])
            asyncio.run(scenario())
