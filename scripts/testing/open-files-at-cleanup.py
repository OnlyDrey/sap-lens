"""Linux diagnostic for the Windows-only failure `PermissionError: [WinError 32]` in test teardown.

Runs backend test modules in one process and reports every file that is still open inside a TemporaryDirectory at the moment that
directory is cleaned up. Linux deletes such files without complaint; Windows refuses, so this finds the handle before a Windows build does.
Usage: python scripts/testing/open-files-at-cleanup.py [MODULE ...]   (default: every backend test module). Exit 1 when something is open.
"""
import sys,os,unittest,importlib,tempfile,traceback
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parents[2]/"backend"/"tests"))
found={}
orig=tempfile.TemporaryDirectory.cleanup
def cleanup(self):
    root=os.path.realpath(self.name)
    for f in os.listdir('/proc/self/fd'):
        try: p=os.readlink('/proc/self/fd/'+f)
        except OSError: continue
        if p.startswith(root+'/'):
            test=next((l.name for l in reversed(traceback.extract_stack()) if l.name.startswith(('test_','tearDown','setUp','doCleanups'))),'?')
            found.setdefault((current[0],p[len(root)+1:]),test)
    orig(self)
tempfile.TemporaryDirectory.cleanup=cleanup
current=['']
names=sys.argv[1:] or sorted(p.stem for p in (__import__('pathlib').Path(__file__).resolve().parents[2]/'backend'/'tests').glob('test_*.py') if p.stem not in {'test_test_profiles','test_linux_lifecycle','test_validation_entrypoint'})
if not os.path.isdir('/proc/self/fd'):raise SystemExit('This diagnostic needs /proc (Linux).')
for name in names:
    current[0]=name
    m=importlib.import_module(name)
    r=unittest.TextTestRunner(stream=open(os.devnull,'w'),verbosity=0).run(unittest.defaultTestLoader.loadTestsFromModule(m))
for (module,path),where in sorted(found.items()): print('OPEN AT CLEANUP',module,path,'in',where)
print('Files open at temporary-directory cleanup:',len(found))
sys.exit(1 if found else 0)
