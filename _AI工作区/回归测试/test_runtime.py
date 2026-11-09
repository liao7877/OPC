"""Portable, synthetic regression fixtures; no user data or external writes."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import opc_runtime
opc_runtime.ensure_supported()
import contextlib
import http.client
import json
import os
import plistlib
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch, Mock
import opc_model as model
import opc_privacy as privacy
import opc_publish as publish
import opc_resolver as resolver
import opc_service as service


class PrivacyTests(unittest.TestCase):
    def test_paths_all_depths_and_company_renames(self):
        for p in ['private/a', '.zcode/config.json', '.claude/settings.local.json', '.codex/config.toml', 'C999-New/个人/a', 'C002-New/E1234/memory/a', 'renamed/P0005-New/a', 'P0005/a', '.opc-sync/x', '_AI工作区/秘密/x']:
            self.assertTrue(privacy.private_path(p, [], ['P0005']), p)
        self.assertFalse(privacy.private_path('C999-New/skills/public/SKILL.md', [], ['P0005']))
        self.assertTrue(privacy.private_path('x/y/.env.local', ['*/.env.*']))
        self.assertTrue(privacy.private_path('clients/acme/contract.pdf', ['clients/acme']))
        self.assertTrue(privacy.private_path('Company/Private/customer.txt'))

    def test_push_fails_closed_and_url_alias(self):
        args = ('origin', ['https://github.com/owner/repo.git'], 'backup', '/secure/backup.git')
        for name, url in [('origin', 'ssh://git@github.com/owner/repo'), ('other', 'git@github.com:owner/repo.git'), ('backup', 'https://github.com/owner/repo.git'), ('other', '/secure/backup.git')]:
            self.assertFalse(privacy.push_allowed(name, url, *args))
        self.assertTrue(privacy.push_allowed('backup', '/secure/backup.git', *args))
        self.assertFalse(privacy.push_allowed('backup', '/secure/backup.git', '', [], 'backup', '/secure/backup.git'))

    def test_filter_callback_uses_shared_policy(self):
        namespace = {}
        source = 'def callback(filename):\n' + '\n'.join('    '+line for line in publish.filename_callback(['*.key'], ['P0005']).splitlines())
        exec(source, namespace)
        self.assertIsNone(namespace['callback'](b'C999/private/key'))
        self.assertIsNone(namespace['callback'](b'old/P0005-name/x'))
        self.assertEqual(namespace['callback'](b'public.py'), b'public.py')

    def test_filter_failure_stops_validation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(privacy, 'policy', return_value=([], [])), patch.object(publish, 'run', side_effect=[b'1', b'', RuntimeError('filter failed')]) as run, patch.object(publish, 'verify_history') as verify:
            with self.assertRaisesRegex(RuntimeError, 'filter failed'):
                publish.build_release(tmp)
            verify.assert_not_called()

    def test_invalid_private_declaration_rejected(self):
        for item in ['bad', {'C001/project/P0005': {}}, {'bad/path': {'availability':'optional','reason':'x'}}]:
            with patch.object(resolver, '_load_toml', return_value={'private_entities': item}):
                with self.assertRaises(ValueError):
                    resolver.private_entities(str(ROOT))

    def test_private_absence_not_missing_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = NS(home_abs=tmp, root=tmp)
            with patch.object(resolver, 'load_company', return_value=cfg), patch.object(resolver, 'entity_types', return_value={'project':'P'}), patch.object(resolver, 'private_entities', return_value={'C001/project/P0005': {'availability':'optional','reason':'fixture'}}):
                with self.assertRaises(resolver.PrivateEntityUnavailable):
                    resolver.resolve_entity('C001', 'project', 'P0005')
                with self.assertRaises(FileNotFoundError) as ordinary:
                    resolver.resolve_entity('C001', 'project', 'P0006')
                self.assertNotIsInstance(ordinary.exception, resolver.PrivateEntityUnavailable)
                (Path(tmp)/'P0005-mounted').mkdir()
                with self.assertRaises(FileNotFoundError) as child:
                    resolver.resolve_entity('C001', 'project', 'P0005', ['missing.md'])
                self.assertNotIsInstance(child.exception, resolver.PrivateEntityUnavailable)


class TenantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.t = service.Tenant.__new__(service.Tenant)
        self.t.base, self.t.cid = str(self.base), 'C001'
        self.t.pctx = NS(cfg=NS(root=str(self.base)))
        self.t.tctx = self.t.dctx = None
        self.t.gen_lock = threading.Lock()
        self.t.last_source_snapshot = None
        self.t.last_error = self.t.last_integration_error = ''
        self.t.last_integration_ok = True

    def test_content_hash_and_delete_detection(self):
        p = self.base/'source.md'; p.write_text('one'); stamp = p.stat().st_mtime_ns
        a = self.t._source_snapshot()
        p.write_text('two'); os.utime(p, ns=(stamp, stamp))
        b = self.t._source_snapshot(); self.assertNotEqual(a, b)
        p.unlink(); self.assertNotEqual(b, self.t._source_snapshot())

    def test_busy_watcher_preserves_pending_change(self):
        self.t.last_source_snapshot = ('old',)
        with patch.object(self.t, 'regenerate', return_value=(True, [])) as regen, patch.object(self.t, '_patrol_async'):
            with self.t.gen_lock:
                self.assertFalse(self.t._watch_once())
            self.assertEqual(self.t.last_source_snapshot, ('old',))
            self.assertTrue(self.t._watch_once()); regen.assert_called_once()

    def test_integration_failed_conflict_recovery(self):
        kernel = Mock(); kernel.snapshot.return_value = {'bindings': {'b': {}}}
        with patch.object(service.opc_sync, 'SyncKernel', return_value=kernel), patch.object(service.opc_sync, 'register_configured_connectors'), patch.object(service.opc_integration_bridge, 'refresh_local_records') as refresh:
            for status in ['failed', 'conflict', 'synced']:
                kernel.reconcile.return_value = {'b': {'status':status}}
                self.t.sync_integrations()
                self.assertEqual(self.t.last_integration_ok, status == 'synced')
            self.assertEqual(refresh.call_count, 3)
            self.assertEqual(kernel.write_projection.call_count, 3)
            self.assertEqual(self.t.last_integration_error, '')

    def test_changed_source_does_not_publish(self):
        with patch.object(self.t, '_source_snapshot', side_effect=[('a',), ('b',)]), patch.object(self.t, 'sync_integrations'), patch.object(service.opc_resolver, 'sync_agent_chains', return_value=([], [])), patch.object(service.opc_tickets, 'generate'), patch.object(service.opc_dashboards, 'generate_all'), patch.object(service.opc_model, 'sync_kb_index'), patch.object(service.opc_projection, 'publish_legacy_snapshot') as pub:
            ok, errors = self.t.regenerate()
            self.assertFalse(ok); self.assertIn('source_changed', errors[0]); pub.assert_not_called()
            self.assertIsNone(self.t.last_source_snapshot)

    def test_periodic_uses_same_generation_path(self):
        with patch.object(self.t, 'regenerate', return_value=(False, ['failure'])) as regen, patch.object(self.t, 'patrol'):
            self.assertEqual(self.t._periodic_once(), (False, ['failure']))
            regen.assert_called_once_with('periodic')

    def test_generation_lock_reentrant_and_serializes_threads(self):
        entered = threading.Event(); release = threading.Event(); second = threading.Event()
        def first():
            with model.generation_lock(self.base), model.generation_lock(self.base):
                entered.set(); release.wait(3)
        def other():
            with model.generation_lock(self.base): second.set()
        a=threading.Thread(target=first); b=threading.Thread(target=other)
        a.start(); self.assertTrue(entered.wait(2)); b.start()
        try: self.assertFalse(second.wait(.15))
        finally: release.set(); a.join(3); b.join(3)
        self.assertTrue(second.is_set()); self.assertFalse(a.is_alive() or b.is_alive())


class HttpTests(unittest.TestCase):
    def test_real_http_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); (base/'dashboard.html').write_text('dashboard')
            (base/'private').mkdir(); (base/'private'/'secret.txt').write_text('secret')
            release=base/'.opc-data/releases/fixture/artifacts'; release.mkdir(parents=True)
            (release/'dashboard-data.js').write_text('window.DASHBOARD_DATA = {"state":"published"};')
            (base/'dashboard-data.js').write_text('window.DASHBOARD_DATA = {"state":"partial"};')
            (base/'.opc-data/current.js').write_text('window.OPC_CURRENT = '+json.dumps({'base':'releases/fixture/','artifacts':{'dashboard-data.js':'artifacts/dashboard-data.js'}})+';')
            t=NS(base=tmp, cid='C001', last_error='', last_integration_ok=False, last_integration_error='offline', last_findings=[], open_items=lambda: [], regenerate=lambda why:(True, []), patrol=lambda:[])
            server=service.ThreadingHTTPServer(('127.0.0.1',0),service.make_handler({'C001':t},'C001'))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            def request(path, method='GET', headers=None):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                c.request(method,path,headers=headers or {}); r=c.getresponse(); body=r.read(); c.close(); return r.status,body
            try:
                self.assertEqual(request('/C001/dashboard.html')[0],200)
                self.assertIn(b'published',request('/C001/dashboard-data.js')[1])
                self.assertNotIn(b'partial',request('/C001/dashboard-data.js')[1])
                for path in ['/C001/private/secret.txt','/C001/','/C001/%2e%2e/private/secret.txt','/C001/.opc-sync/projection.json']:
                    self.assertNotEqual(request(path)[0],200,path)
                self.assertEqual(request('/api/ping',headers={'Host':f'evil.example:{server.server_port}'})[0],403)
                self.assertEqual(request('/api/C001/sync','POST',{'Origin':'http://evil.example'})[0],403)
                status, body=request('/api/C001/sync','POST'); payload=json.loads(body)
                self.assertEqual(status,200); self.assertTrue(payload['partial']); self.assertFalse(payload['integration_ok'])
            finally: server.shutdown(); server.server_close(); thread.join(3)

    def test_host_and_origin(self):
        for value in ['127.0.0.1:8765','localhost:8765','[::1]:8765']:
            self.assertTrue(service._allowed_host(value,8765))
        for value in ['localhost:8766','user@localhost:8765','localhost:8765/path','evil:8765','localhost']:
            self.assertFalse(service._allowed_host(value,8765))
        self.assertFalse(service._same_origin({'Origin':'https://localhost:8765','Host':'localhost:8765'}))


class StartupTests(unittest.TestCase):
    def test_macos_plist(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(service.sys,'platform','darwin'), patch.object(service,'_ROOT',tmp), patch.object(service,'_launch_agent_path',return_value=Path(tmp)/'service.plist'), patch.object(service,'_startup_command',return_value=['/python with spaces/python','/opc/service.py']), patch.dict(os.environ, {'CI':'true'}):
            path=service.register_startup(12345); data=plistlib.loads(Path(path).read_bytes())
            self.assertEqual(data['ProgramArguments'], ['/python with spaces/python','/opc/service.py','--port','12345'])
            self.assertTrue(data['RunAtLoad'])

    def test_windows_vbs_and_linux_cron(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(service.sys,'platform','win32'), patch.object(service,'_startup_dir',return_value=tmp), patch.object(service,'_startup_command',return_value=['C:/Program Files/Python/python.exe','C:/OPC/opc_service.py']):
            text=Path(service.register_startup(12345)).read_text()
            self.assertIn('12345',text); self.assertIn('""C:/Program Files/Python/python.exe""',text)
        text='0 1 * * * unrelated\n# OPC-Service\n@reboot old\n'
        self.assertEqual(service._cron_update(text,'@reboot new'),'0 1 * * * unrelated\n# OPC-Service\n@reboot new\n')
        with patch.object(service.sys,'platform','linux'), patch.object(service,'_startup_command',return_value=['python3','/opc/service.py']), patch.object(service,'_system_run',side_effect=[NS(returncode=0,stdout=text,stderr=''),NS(returncode=0,stdout='',stderr='')]) as run:
            service.register_startup(12345)
            self.assertIn('12345',run.call_args.kwargs['input'])

    def test_single_instance_gate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(service, '_ROOT', tmp), patch.object(service, '_serve', return_value=0) as serve:
            lock=Path(tmp)/'_AI工作区/运行日志/service-instance';lock.parent.mkdir(parents=True)
            with model.file_lock(lock):
                self.assertEqual(service.main([]),0)
                serve.assert_not_called()
            self.assertEqual(service.main([]),0)
            serve.assert_called_once()

    def test_bootstrap_does_not_hide_failures(self):
        with patch.object(resolver, 'all_company_ids', return_value=['C001']), patch.object(resolver.subprocess, 'run', return_value=NS(returncode=1, stdout='failure', stderr='')), patch.object(resolver, 'install_session_gates', return_value=[]), patch.object(resolver, 'doctor', return_value=([], [])), patch.object(service, 'register_startup', side_effect=RuntimeError('registration failure')), patch.object(service, 'ensure_started') as started:
            errors, _ = resolver.bootstrap(str(ROOT))
            self.assertEqual(len(errors),4)
            started.assert_called_once()

    def test_public_target_records_exact_remote_revision(self):
        with patch.object(privacy,'_git',side_effect=['origin','https://example.test/public.git']), patch.object(publish,'run',return_value=b'abc123 refs/heads/main\n'):
            self.assertEqual(publish.public_target(ROOT),('https://example.test/public.git','abc123'))
        with patch.object(privacy,'_git',side_effect=['origin','url1\nurl2']):
            with self.assertRaises(RuntimeError):publish.public_target(ROOT)

    def test_system_commands_bounded(self):
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('crontab',10)) as run:
            with self.assertRaises(RuntimeError): service._system_run(['crontab','-'])
            self.assertEqual(run.call_args.kwargs['timeout'],10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
