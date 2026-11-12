#!/usr/bin/env python3
"""One entry point for the SAP Lens test profiles (changed, fast, smoke, targeted, regression, release).

Standard library only; works on Windows and Linux. Feature ownership comes from
scripts/test-map.json. See docs/development/TESTING.md.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import fnmatch
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def python_exe():
    """Python 3.12 x64 for every child command: this interpreter when it is 3.12, else the ready project .venv, never a silent fallback."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_system import python_env
    return python_env.test_interpreter(ROOT)

FRONTEND = ROOT / 'frontend'
BACKEND_TESTS = ROOT / 'backend' / 'tests'
BROWSER_TESTS = FRONTEND / 'tests'
MAP = ROOT / 'scripts' / 'test-map.json'
BASE_PORT = 18745
SLOWEST_REQUESTED = False
SLOWEST = 10            # --slowest N: how many of the slowest tests the summary lists (0 hides them)
_LOG = None             # --log FILE: a copy of everything this runner prints, including relayed worker output


class Tee:
    """Write to the console and the --log file."""
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.console.write(text)
        self.log.write(plain(text))                                     # the log never contains colour markers or escape sequences
        return len(text)

    def flush(self):
        self.console.flush()
        self.log.flush()


# Glyphs that test titles and Playwright output use, spelled in ASCII for a console that cannot show them (Windows PowerShell 5.1 with a
# redirected or piped stdout uses the ANSI code page and showed `›` as `ΓÇ║`). The --log copy keeps the original UTF-8 text.
ASCII_GLYPHS = str.maketrans({'›': '>', '»': '>', '✘': 'x', '✓': '+', '✔': '+', '─': '-', '│': '|', '–': '-', '—': '-', '…': '...',
                              '·': '.', '→': '->', '←': '<-', '×': 'x', '“': '"', '”': '"', '‘': "'", '’': "'"})


def ascii_text(text: str) -> str:
    """Readable ASCII: known glyphs spelled out, accents dropped (déjà -> deja), anything else `?`."""
    import unicodedata
    decomposed = unicodedata.normalize('NFKD', text.translate(ASCII_GLYPHS))
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).encode('ascii', 'replace').decode('ascii')


# Status colours, for the terminal only. Status words and counts are wrapped in invisible markers (STX kind US text ETX). The console
# renders them as ANSI sequences or Windows console attributes, or drops them; the --log copy, JSON reports and plain streams never
# contain them. A child process (backend worker, run-tests.py under validate.py) passes the markers up when SAP_LENS_TEST_COLOR_MARKERS=1.
COLOR_MARK = re.compile('\x02([a-z]+)\x1f(.*?)\x03', re.S)
COLORS = {'pass': ('32', 0x0A), 'fail': ('31', 0x0C), 'warn': ('33', 0x0E), 'skip': ('90', 0x08), 'info': ('36', 0x0B)}
PAINT = False   # main() decides for the runner, run_backend_worker() for a worker; importing the module never paints


def paint(text, kind: str) -> str:
    """`text` in the colour of `kind` (pass, fail, warn, skip, info) when the terminal shows colours; unchanged otherwise."""
    text = str(text)
    return f'\x02{kind}\x1f{text}\x03' if PAINT and text else text


def plain(text: str) -> str:
    return COLOR_MARK.sub(r'\2', text)


def status(word: str, kind: str, width: int = 0) -> str:
    """A coloured status word padded to `width` with uncoloured spaces, so columns stay aligned."""
    return paint(word, kind) + ' ' * max(0, width - len(word))


def count(value: int, kind: str) -> str:
    """A count coloured only when it is not zero (zero failures stay neutral)."""
    return paint(value, kind) if value else str(value)


def _windows_handle(stream):
    import ctypes
    import msvcrt
    return ctypes.windll.kernel32, msvcrt.get_osfhandle(stream.fileno())


def _enable_windows_ansi(stream) -> bool:
    """Turn on ANSI processing for this console (Windows 10+, Windows Terminal, PowerShell 5.1 and 7 alike); False when unavailable."""
    try:
        import ctypes
        kernel32, handle = _windows_handle(stream)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 0x0004) or bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError, ImportError):
        return False


def color_mode(stream, enable_windows_ansi=_enable_windows_ansi) -> str:
    """'ansi', 'native' (Windows console attributes) or '' (no colour).

    NO_COLOR (any value) and SAP_LENS_TEST_COLOR=never switch colours off; SAP_LENS_TEST_COLOR=always forces ANSI. Otherwise only an
    interactive terminal gets colours: redirected output, files and pipes stay free of escape sequences, and TERM=dumb has none."""
    choice = os.environ.get('SAP_LENS_TEST_COLOR', 'auto').strip().lower()
    if os.environ.get('NO_COLOR') or choice in {'never', 'no', '0', 'off'}:
        return ''
    if choice in {'always', 'yes', '1', 'on'}:
        return 'ansi'
    if not getattr(stream, 'isatty', lambda: False)():
        return ''
    if os.name != 'nt':
        return '' if os.environ.get('TERM', '') == 'dumb' else 'ansi'
    return 'ansi' if enable_windows_ansi(stream) else 'native'


class SafeConsole:
    """Console stream that never fails on a character and never shows mojibake.

    A real console (Windows console API, a Linux terminal) and a UTF-8 pipe get the text unchanged. A redirected or piped stdout on
    Windows is written in the ANSI code page while Windows PowerShell 5.1 reads native output in the OEM code page, so any non-ASCII
    character arrives garbled (`›` became `ΓÇ║`); non-UTF-8 streams get readable ASCII, while UTF-8 pipes preserve Unicode. The --log copy
    always keeps the original UTF-8 text. SAP_LENS_TEST_ASCII=1 or 0 forces the choice."""
    def __init__(self, stream, colors: str | None = None):
        self.stream = stream
        self.colors = color_mode(stream) if colors is None else colors   # 'ansi', 'native', 'markers' (pass them up) or ''
        self.encoding = getattr(stream, 'encoding', None) or 'utf-8'
        forced = os.environ.get('SAP_LENS_TEST_ASCII')
        utf8 = self.encoding.lower().replace('-', '').replace('_', '') in {'utf8', 'utf8sig'}
        self.ascii = forced == '1' if forced in {'0', '1'} else not utf8

    def write(self, text):
        if self.ascii:
            text = ascii_text(text)                                     # the markers are ASCII control characters and survive
        if self.colors == 'ansi':
            text = COLOR_MARK.sub(lambda match: f'\x1b[{COLORS[match[1]][0]}m{match[2]}\x1b[0m', text)
        elif self.colors == 'native':
            self._native(text)
            return len(text)
        elif self.colors != 'markers':
            text = plain(text)
        self._raw(text)
        return len(text)

    def _raw(self, text):
        try:
            self.stream.write(text)
        except UnicodeEncodeError:
            self.stream.write(ascii_text(text))

    def set_attribute(self, attribute: int | None) -> None:
        """Windows console text attribute; None restores the colour the console had when the runner started."""
        try:
            import ctypes
            kernel32, handle = _windows_handle(self.stream)
            if not hasattr(self, '_default'):
                info = ctypes.create_string_buffer(22)                  # CONSOLE_SCREEN_BUFFER_INFO; wAttributes at offset 8
                self._default = int.from_bytes(info.raw[8:10], 'little') if kernel32.GetConsoleScreenBufferInfo(handle, info) else 0x07
            kernel32.SetConsoleTextAttribute(handle, self._default if attribute is None else attribute)
        except (AttributeError, OSError, ValueError, ImportError):
            pass

    def _native(self, text):
        position = 0
        for match in COLOR_MARK.finditer(text):
            self._raw(text[position:match.start()])
            self.stream.flush()
            self.set_attribute(COLORS[match[1]][1])
            self._raw(match[2])
            self.stream.flush()
            self.set_attribute(None)
            position = match.end()
        self._raw(text[position:])

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return getattr(self.stream, 'isatty', lambda: False)()


def emit(text: str) -> None:
    sys.stdout.write(text)          # a Tee when --log is set, so the copy happens there
    sys.stdout.flush()


def load_map() -> dict:
    return json.loads(MAP.read_text(encoding='utf-8'))


def backend_modules() -> list[str]:
    return sorted(path.stem for path in BACKEND_TESTS.glob('test_*.py'))


def browser_specs() -> list[str]:
    return sorted(path.name[:-len('.spec.ts')] for path in BROWSER_TESTS.glob('*.spec.ts'))


def selection(features: list[str] | None) -> tuple[list[str], list[str]]:
    """Backend modules and browser spec names for the named features (all when None)."""
    mapping = load_map()['features']
    names = list(mapping) if not features else features
    unknown = [name for name in names if name not in mapping]
    if unknown:
        raise SystemExit(f'Unknown feature(s): {", ".join(unknown)}. Known: {", ".join(mapping)}')
    return ([m for n in names for m in mapping[n]['backend']], [s for n in names for s in mapping[n]['browser']])


def coverage_problems() -> list[str]:
    """Every test file must belong to exactly one feature, so no profile can silently drop tests."""
    mapping = load_map()['features']
    problems = []
    for kind, actual in (('backend', backend_modules()), ('browser', browser_specs())):
        listed = [name for feature in mapping.values() for name in feature[kind]]
        problems += [f'{kind} test not mapped to a feature: {name}' for name in sorted(set(actual) - set(listed))]
        problems += [f'{kind} mapping names a missing test file: {name}' for name in sorted(set(listed) - set(actual))]
        problems += [f'{kind} test mapped more than once: {name}' for name in sorted({n for n in listed if listed.count(n) > 1})]
    hints = load_map().get('browser_seconds_hint', {})
    problems += [f'browser_seconds_hint names a missing spec: {name}' for name in sorted(set(hints) - set(browser_specs()))]
    return problems


# ---------------------------------------------------------------------------- change selection (Fast Validation)

def _pattern(glob: str) -> re.Pattern:
    out, i = '', 0
    while i < len(glob):
        if glob.startswith('**/', i):
            out += '(?:.*/)?'; i += 3
        elif glob.startswith('**', i):
            out += '.*'; i += 2
        elif glob[i] == '*':
            out += '[^/]*'; i += 1
        else:
            out += re.escape(glob[i]); i += 1
    return re.compile(out + r'\Z')


def classify(path: str, rules: dict | None = None) -> str:
    """docs, backend_tests, frontend_tests, frontend or core. Core is the default, so an unmapped path runs the whole backend suite."""
    rules = rules or load_map()['change_rules']
    for category in ('docs', 'backend_tests', 'frontend_tests', 'frontend'):
        if any(_pattern(glob).match(path) for glob in rules[category]):
            return category
    return 'core'


def changed_files(base: str | None) -> list[str] | None:
    """Paths that differ from `base` (working tree included); None when the base is unusable, which selects the safe baseline."""
    if not base or set(base) == {'0'}:
        return None
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    present = lambda: git('cat-file', '-e', base + '^{commit}').returncode == 0
    if not present():
        git('fetch', '--no-tags', '--depth=1', 'origin', base)  # a shallow CI checkout may lack the previous commit
    if not present():
        return None
    done = git('diff', '--name-only', base)
    return sorted(set(done.stdout.split())) if done.returncode == 0 else None


def plan_changes(files: list[str] | None) -> dict:
    """What Fast Validation runs for a change. Never less than: the repository integrity tests; the whole backend for any backend source,
    script, workflow, dependency or unmapped change; build, lint and the @smoke browser tests for any frontend change."""
    mapping = load_map()
    rules = mapping['change_rules']
    always = [m for feature in rules['always'] for m in mapping['features'][feature]['backend']]
    if files is None:
        return dict(backend='full', modules=[], frontend=True, browser=True, specs=[], reasons=['no usable base commit: safe baseline (whole backend, frontend checks, browser smoke)'], files=None)
    modules, specs, reasons = set(always), set(), []
    backend_full = frontend = False
    for path in files:
        category = classify(path, rules)
        if category == 'docs':
            continue
        if category == 'backend_tests':
            name = Path(path).stem
            if name.startswith('test_'):
                if (BACKEND_TESTS / f'{name}.py').exists():  # a deleted test module has nothing left to run
                    modules.add(name)
            else:
                backend_full = True  # a shared helper or fixture: its users are unknown
                reasons.append(f'{path}: shared test helper')
        elif category == 'frontend_tests':
            frontend = True
            name = Path(path).name[:-len('.spec.ts')] if path.endswith('.spec.ts') else None
            if name and (BROWSER_TESTS / f'{name}.spec.ts').exists():
                specs.add(name)
        elif category == 'frontend':
            frontend = True
        else:
            backend_full = True
            reasons.append(f'{path}: core (backend source, script, workflow, dependency or unmapped path)')
    return dict(backend='full' if backend_full else 'modules' if len(modules) > len(always) else 'repository',
                modules=sorted(modules), frontend=frontend, browser=frontend, specs=sorted(specs), reasons=reasons[:12], files=files)


# ---------------------------------------------------------------------------- change selection for QUICK and TARGETED
# CI keeps the conservative `changed` plan above (whole backend for any backend change). Local QUICK and TARGETED resolve what a change
# reaches from the import graphs of the code itself, then from test-map.json validation_sources; anything unresolved selects broadly.

BROAD_SPECS = 25        # a browser helper used by more specs than this selects the regression browser set rather than nearly the whole suite
BROAD_FEATURES = 4      # a frontend file whose consumers span more features than this is "widely shared": run the regression browser set


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def features_for(path: str) -> set[str]:
    mapping = load_map()
    return {area for rule in mapping['validation_sources'] if _matches(path, rule['patterns']) for area in rule['areas']}


def python_module(path: str) -> str | None:
    parts = Path(path).parts
    if len(parts) == 2 and parts[0] == 'backend' and path.endswith('.py'):
        return Path(path).stem
    if len(parts) == 3 and parts[:2] in (('backend', 'routers'), ('backend', 'tests')) and path.endswith('.py'):
        return ('routers.' if parts[1] == 'routers' else '') + Path(path).stem
    return None


def python_import_graph() -> dict[str, set[str]]:
    """module -> modules that import it, over backend/, backend/routers/ and backend/tests/ (static imports, including function-level ones)."""
    paths = {}
    for path in [*(ROOT / 'backend').glob('*.py'), *(ROOT / 'backend' / 'routers').glob('*.py'), *BACKEND_TESTS.glob('*.py')]:
        paths[python_module(path.relative_to(ROOT).as_posix())] = path
    reverse: dict[str, set[str]] = {name: set() for name in paths}
    for name, path in paths.items():
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level and name.startswith('routers.'):
                    base = 'routers' + ('.' + base if base else '')
                targets = [base, *(f'{base}.{alias.name}' if base else alias.name for alias in node.names)]
            for target in targets:
                if target in reverse and target != name:
                    reverse[target].add(name)
    return reverse


def dependents(start: set[str], reverse: dict[str, set[str]]) -> set[str]:
    seen, pending = set(start), list(start)
    while pending:
        for importer in reverse.get(pending.pop(), ()):
            if importer not in seen:
                seen.add(importer); pending.append(importer)
    return seen


TS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)['"]([^'"]+)['"]""")


def ts_import_graph() -> dict[str, set[str]]:
    """file -> files that import it, over frontend/src and frontend/tests (paths relative to the repository root)."""
    files = [p for p in [*(FRONTEND / 'src').rglob('*'), *BROWSER_TESTS.rglob('*')] if p.suffix in ('.ts', '.tsx') and 'node_modules' not in p.parts]
    known = {p.relative_to(ROOT).as_posix() for p in files}
    reverse: dict[str, set[str]] = {name: set() for name in known}
    for path in files:
        importer = path.relative_to(ROOT).as_posix()
        for spec in TS_IMPORT.findall(path.read_text(encoding='utf-8', errors='replace')):
            if spec.startswith('@/'):
                base = (FRONTEND / 'src' / spec[2:]).as_posix()
            elif spec.startswith('.'):
                base = os.path.normpath(path.parent / spec).replace(os.sep, '/')
            else:
                continue
            for candidate in (base, base + '.ts', base + '.tsx', base + '/index.ts', base + '/index.tsx'):
                rel = os.path.relpath(candidate, ROOT).replace(os.sep, '/')
                if rel in reverse:
                    reverse[rel].add(importer)
                    break
    return reverse


def page_roots_reached(path: str, ts: dict[str, set[str]]) -> set[str] | None:
    """Page roots (profiles.page_specs) that render `path`, walking the import graph up and stopping at each root. None when the
    file is shared: it reaches the area's container, App.tsx or any file outside the area without passing through a page root."""
    page_specs = load_map()['profiles'].get('page_specs', {})
    area = next((prefix for prefix in load_map()['profiles'].get('page_core_specs', {}) if path.startswith(prefix)), None)
    if area is None:
        return None
    if path in page_specs:
        return {path}
    pages: set[str] = set()
    seen, pending = {path}, [path]
    while pending:
        for importer in ts.get(pending.pop(), ()):
            if importer in page_specs:
                pages.add(importer)
            elif importer not in seen:
                if not importer.startswith(area) or not ts.get(importer):
                    return None                                                  # escapes the area or reaches a top-level container
                seen.add(importer); pending.append(importer)
    return pages or None


def plan_targeted(files: list[str]) -> dict:
    """What QUICK and TARGETED run for these changed paths. Never silent: every path is either resolved, documentation, or broadens the run."""
    mapping = load_map()
    profiles = mapping['profiles']
    py: dict | None = None
    ts: dict | None = None
    modules: set[str] = set()
    specs: set[str] = set()
    features: set[str] = set()
    reasons: list[str] = []
    backend_only: set[str] = set()                                               # features reached through a page map: their backend modules, not every spec
    broad_backend = broad_browser = frontend = security = False
    for path in files:
        category = classify(path)
        if category == 'docs':
            continue
        if _matches(path, profiles['selection_system']):
            features.add('repository')
            reasons.append(f'{path}: test selection system; its own tests run')
            if path.startswith('frontend/'):
                frontend = broad_browser = True
            continue
        if _matches(path, profiles['security_sensitive']):
            security = True
        module = python_module(path)
        if category == 'backend_tests':
            if module and module.startswith('test_'):
                if (BACKEND_TESTS / f'{module}.py').exists():
                    modules.add(module)
                continue
            py = py if py is not None else python_import_graph()
            users = {name for name in dependents({module}, py) if name.startswith('test_')} if module in (py or {}) else set()
            if users:
                modules |= users; reasons.append(f'{path}: test helper imported by {len(users)} test modules')
            else:
                broad_backend = True; reasons.append(f'{path}: shared backend fixture with unknown users: whole backend')
            continue
        if category == 'frontend_tests':
            frontend = True
            if path.endswith('.spec.ts'):
                if (ROOT / path).exists():
                    specs.add(Path(path).name[:-len('.spec.ts')])
            elif '/unit/' not in path:
                ts = ts if ts is not None else ts_import_graph()
                users = {Path(name).name[:-len('.spec.ts')] for name in dependents({path}, ts) if name.endswith('.spec.ts')}
                if len(users) > BROAD_SPECS:
                    broad_browser = True; reasons.append(f'{path}: browser helper used by {len(users)} specs: regression browser set (FULL runs them all)')
                elif users:
                    specs |= users; reasons.append(f'{path}: browser helper imported by {len(users)} specs')
                else:
                    broad_browser = True; reasons.append(f'{path}: browser helper with unknown users: regression browser set')
            continue
        if module is not None:                                                   # backend source
            py = py if py is not None else python_import_graph()
            users = {name for name in dependents({module}, py) if name.startswith('test_')}
            owners = features_for(path)
            modules |= users
            features |= owners
            if users or owners:
                reasons.append(f'{path}: {len(users)} test modules import it' + (f'; features {", ".join(sorted(owners))}' if owners else ''))
            else:
                broad_backend = True; reasons.append(f'{path}: not imported by any test and not mapped: whole backend')
            continue
        if path.startswith('frontend/src/'):
            frontend = True
            if not path.endswith(('.ts', '.tsx')):
                broad_browser = True; reasons.append(f'{path}: stylesheet or asset used everywhere: regression browser set')
                continue
            ts = ts if ts is not None else ts_import_graph()
            reached = dependents({path}, ts)
            specs |= {Path(name).name[:-len('.spec.ts')] for name in reached if name.endswith('.spec.ts')}
            owners = set().union(*(features_for(name) for name in reached)) - {'shared-ui'}
            if '/components/Shared/' in path or '/components/Settings/ComponentLibrary' in path:
                specs.add('component-library')
            pages = page_roots_reached(path, ts) if len(owners) <= BROAD_FEATURES else None
            if pages:
                profile = mapping['profiles']
                area = next(prefix for prefix in profile['page_core_specs'] if path.startswith(prefix))
                page_selection = set(profile['page_core_specs'][area]).union(*(profile['page_specs'][page] for page in pages))
                specs |= page_selection; backend_only |= owners
                reasons.append(f"{path}: renders on {', '.join(sorted(Path(page).stem for page in pages))}: {len(page_selection)} specs")
                continue
            if len(owners) > BROAD_FEATURES:
                broad_browser = True; reasons.append(f'{path}: used by {len(owners)} features: regression browser set')
            elif not owners and not any(name.endswith('.spec.ts') for name in reached) and '/components/Shared/' not in path:
                broad_browser = True; reasons.append(f'{path}: no known consumer or owning feature yet: regression browser set')
            else:
                features |= owners; reasons.append(f'{path}: consumers in {", ".join(sorted(owners)) or "no feature"}')
            continue
        if category == 'frontend':                                               # package manifests, Vite/TS config, icon catalogue
            frontend = broad_browser = True; reasons.append(f'{path}: frontend toolchain: regression browser set')
            continue
        owners = features_for(path)
        if owners:
            features |= owners; reasons.append(f'{path}: features {", ".join(sorted(owners))}')
        else:
            broad_backend = broad_browser = True; reasons.append(f'{path}: unmapped: whole backend and the regression browser set')
    if security:
        modules |= set(profiles['security_modules']); reasons.append('security-sensitive path: the security modules always run')
    expanded, pending = features | backend_only, list(features | backend_only)
    while pending:
        for dependency in mapping.get('validation_dependencies', {}).get(pending.pop(), []):
            if dependency not in expanded:
                expanded.add(dependency); pending.append(dependency)
    for name in expanded:
        modules |= set(mapping['features'][name]['backend'])
    for name in features - {'shared-ui'}:
        specs |= set(mapping['features'][name]['browser'])
    modules |= {m for name in mapping['change_rules']['always'] for m in mapping['features'][name]['backend']}
    return dict(modules=sorted(modules), specs=sorted(specs), features=sorted(features | backend_only), broad_backend=broad_backend, broad_browser=broad_browser,
                browser=frontend or bool(specs) or broad_browser, frontend=frontend, security=security, reasons=reasons)


def local_changes(base: str) -> list[str] | None:
    """Changed paths against `base` for QUICK and TARGETED, including untracked files; None when the base is unusable."""
    files = changed_files(base)
    if files is None:
        return None
    untracked = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return sorted(set(files) | set(untracked))


def release_modules() -> set[str]:
    mapping = load_map()
    return {m for name in mapping['profiles']['release_features'] for m in mapping['features'][name]['backend']}


# ---------------------------------------------------------------------------- backend

class QuietResult(unittest.TextTestResult):
    """unittest's own result with a periodic heartbeat instead of one line or dot per test. Output a test prints is buffered by the runner
    (`buffer=True`) and shown only with that test's failure, so expected diagnostics of negative tests stay out of a passing run."""
    heartbeat = float(os.environ.get('SAP_LENS_TEST_HEARTBEAT', '30'))
    label = os.environ.get('SAP_LENS_TEST_LABEL', 'backend')

    def startTestRun(self):
        super().startTestRun()
        self._started = self._last = time.perf_counter()

    def _failed_now(self, test, kind):
        self.stream.write(f'[{self.label}] {paint(kind, "fail")}: {test.id()}\n')    # at once; the traceback follows in the summary
        self.stream.flush()

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._failed_now(test, 'FAIL')

    def addError(self, test, err):
        super().addError(test, err)
        self._failed_now(test, 'ERROR')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._failed_now(subtest, 'FAIL')

    def stopTest(self, test):
        super().stopTest(test)
        now = time.perf_counter()
        if self.heartbeat and now - self._last >= self.heartbeat:
            self._last = now
            failed = len(self.failures) + len(self.errors)
            self.stream.write(f'[{self.label}] {self.testsRun} tests, {count(failed, "fail")} failed, {count(len(self.skipped), "skip")} skipped, {clock(now - self._started)}\n')
            self.stream.flush()


def run_backend_worker(names: list[str], output: Path) -> int:
    """Run unittest names in this process and write a JSON result (used as a subprocess).

    Default: quiet and buffered (captured output printed only for failing tests). SAP_LENS_TEST_VERBOSE=1: one line per test, unbuffered,
    which is the mode to use when debugging what a test prints."""
    global PAINT
    # The parent passes colour markers through when its terminal shows colours. Read and drop the switch here, so that tests importing
    # this module or starting run-tests.py themselves see exactly what an uncoloured run prints.
    PAINT = os.environ.pop('SAP_LENS_TEST_COLOR_MARKERS', '0') == '1'
    sys.path.insert(0, str(BACKEND_TESTS))
    verbose = os.environ.get('SAP_LENS_TEST_VERBOSE') == '1'
    suite = unittest.TestLoader().loadTestsFromNames(names)
    # Leaked files, sockets and processes are reported in the summary instead of disappearing into the per-test output buffer.
    import warnings
    leaks: list[str] = []
    warnings.simplefilter('default', ResourceWarning)
    original_show = warnings.showwarning
    def show(message, category, filename, lineno, file=None, line=None):
        if issubclass(category, ResourceWarning):
            leaks.append(f'{Path(filename).name}:{lineno}: {str(message)[:160]}')
        else:
            original_show(message, category, filename, lineno, file, line)
    warnings.showwarning = show
    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 0, stream=sys.stderr, buffer=not verbose, durations=None,
                                     resultclass=unittest.TextTestResult if verbose else QuietResult)
    result = runner.run(suite)
    slowest = sorted(((round(seconds, 2), str(test)) for test, seconds in getattr(result, 'collectedDurations', [])), reverse=True)[:25]
    output.write_text(json.dumps({
        'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': [[str(test), reason] for test, reason in result.skipped], 'seconds': time.perf_counter() - started, 'slowest': slowest,
        'resource_warnings': sorted(set(leaks)),
    }), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


def split_modules(modules: list[str], jobs: int) -> list[list[str]]:
    """Longest-first balancing from measured hints, falling back to the number of test functions."""
    hints = load_map().get('backend_seconds_hint', {})
    weight = lambda m: hints.get(m, 0.08 * len((BACKEND_TESTS / f'{m}.py').read_text(encoding='utf-8').split('    def test_')))
    groups: list[list[str]] = [[] for _ in range(max(1, jobs))]
    loads = [0.0] * len(groups)
    for module in sorted(modules, key=weight, reverse=True):
        index = loads.index(min(loads))
        groups[index].append(module)
        loads[index] += weight(module)
    return [group for group in groups if group]


def run_backend(names: list[str], jobs: int, label: str, split: bool) -> dict:
    started = time.perf_counter()
    groups = split_modules(names, jobs) if split else [names]
    print(f'{paint("[start]", "info")} {label}: {len(names)} module(s) or name(s) in {len(groups)} process(es)', flush=True)
    with tempfile.TemporaryDirectory(prefix='sap-lens-backend-') as scratch:
        def launch(index_group: tuple[int, list[str]]) -> tuple[int, Path]:
            index, group = index_group
            out = Path(scratch) / f'{index}.json'
            command = [python_exe(), '-W', 'error::DeprecationWarning', str(Path(__file__).resolve()), '_backend', str(out), *group]
            env = dict(os.environ, SAP_LENS_TEST_LABEL=f'backend {index + 1}/{len(groups)}' if len(groups) > 1 else 'backend',
                       PYTHONIOENCODING='utf-8', SAP_LENS_TEST_COLOR_MARKERS='1' if PAINT else '0')   # the runner reads the worker as UTF-8; a test name or traceback never fails to encode
            # Relay the worker's lines through this process so they can also go to --log; a killed worker still ends the loop.
            with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace') as process:
                for line in process.stdout:
                    emit(line)
                code = process.wait()
            return code, out
        with ThreadPoolExecutor(len(groups)) as pool:
            outcomes = list(pool.map(launch, enumerate(groups)))
        merged = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'shards': [], 'slowest': []}
        for code, out in outcomes:
            if not out.exists():                                         # the worker died before writing its result: infrastructure
                merged.setdefault('infrastructure', []).append(f'backend worker exited with code {code} without a result')
            data = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {'tests': 0, 'failures': 0, 'errors': 1, 'skipped': [], 'seconds': 0.0}
            merged['shards'].append(round(data.get('seconds', 0.0), 1))
            for key in ('tests', 'failures', 'errors'):
                merged[key] += data[key]
            merged['skipped'] += data['skipped']
            merged['slowest'] += [[seconds, 'backend', name] for seconds, name in data.get('slowest', [])]
            merged.setdefault('resource_warnings', []).extend(data.get('resource_warnings', []))
        merged['slowest'] = sorted(merged['slowest'], reverse=True)[:SLOWEST]
    merged.update(name=label, seconds=time.perf_counter() - started, ok=not merged['failures'] and not merged['errors'] and all(c == 0 for c, _ in outcomes))
    # Aggregate lines in unittest's own format keep scripts/testing/ci.py counts correct after parallel workers.
    print(f"\nRan {merged['tests']} tests in {merged['seconds']:.3f}s")
    print((paint('OK', 'pass') if merged['ok'] else paint('FAILED', 'fail')) + (f" (skipped={len(merged['skipped'])})" if merged['skipped'] else ''), flush=True)
    return merged


# ---------------------------------------------------------------------------- browser

def npm() -> str:
    # SAP_LENS_NPM replaces npm with another executable (the runner's own tests use a fake Playwright to exercise lifecycle and reporting).
    return os.environ.get('SAP_LENS_NPM') or shutil.which('npm') or shutil.which('npm.cmd') or 'npm'


def playwright_command(arguments: list[str]) -> list[str]:
    """Invoke the installed CLI without npm.cmd/CMD interpreting grep pipes as commands."""
    if os.environ.get('SAP_LENS_NPM'):  # executable test double for process lifecycle tests
        return [npm(), '--prefix', str(FRONTEND), 'run', 'test:browser', '--', *arguments]
    return [shutil.which('node') or 'node', str(FRONTEND / 'node_modules' / '@playwright' / 'test' / 'cli.js'), 'test', *arguments]


def dist_is_stale() -> bool:
    built = FRONTEND / 'dist' / 'index.html'
    if not built.exists():
        return True
    inputs = ['index.html', 'package.json', 'vite.config.ts', 'tailwind.config.ts', 'tsconfig.json']
    files = [FRONTEND / name for name in inputs] + list((FRONTEND / 'src').rglob('*'))
    return max((p.stat().st_mtime for p in files if p.is_file()), default=0) > built.stat().st_mtime


def step(name: str, command: list[str], cwd: Path = ROOT, env: dict | None = None, quiet: bool = True) -> dict:
    started = time.perf_counter()
    print(f'{paint("[start]", "info")} {name}', flush=True)
    try:
        done = subprocess.run(command, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=quiet, text=True, encoding='utf-8', errors='replace')
    except OSError as error:                                           # the tool itself is missing or cannot start: infrastructure, not a finding
        print(f'[done] {name}: {paint("could not start", "fail")} ({error})', flush=True)
        return {'name': name, 'seconds': time.perf_counter() - started, 'ok': False, 'tests': None, 'infrastructure': [f'{name}: could not start ({error})']}
    if quiet and done.returncode:
        emit(f'--- {name}: stdout ---\n' + (done.stdout or '')[-4000:] + f'\n--- {name}: stderr ---\n' + (done.stderr or '')[-2000:] + '\n')
    seconds = time.perf_counter() - started
    print(f"[done] {name}: {paint('PASS', 'pass') if done.returncode == 0 else paint(f'FAIL (exit code {done.returncode})', 'fail')} ({seconds:.1f}s)", flush=True)
    return {'name': name, 'seconds': seconds, 'ok': done.returncode == 0, 'tests': None}


def build_frontend(force: bool = False) -> dict | None:
    if not (FRONTEND / 'node_modules').exists():
        raise SystemExit('Frontend dependencies are missing: run `npm --prefix frontend ci` first.')
    if not force and not dist_is_stale():
        return None
    return step('build (includes TypeScript check)', [npm(), '--prefix', str(FRONTEND), 'run', 'build'])


def busy_ports_at(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(('127.0.0.1', port)) == 0


def busy_ports(jobs: int) -> list[int]:
    """Ports of this run that another process already listens on. The runner reports them; it never stops a process."""
    busy = []
    for port in range(BASE_PORT, BASE_PORT + jobs):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                busy.append(port)
    return busy


BROWSER_JOBS_MAX = 3  # measured on 4 vCPUs: 3 processes were the fastest, 4 were slower (Chromium saturates the host)
DEFAULT_SPEC_SECONDS = 35.0
OWNED: list[subprocess.Popen] = []  # only processes this runner started; they are the only ones it ever signals


def split_specs(files: list[str], jobs: int) -> list[list[str]]:
    """Deterministic longest-first assignment of spec files to `jobs` independent processes, from measured per-spec seconds."""
    hints = load_map().get('browser_seconds_hint', {})
    weight = lambda f: hints.get(Path(f).name[:-len('.spec.ts')], DEFAULT_SPEC_SECONDS)
    groups: list[list[str]] = [[] for _ in range(max(1, jobs))]
    loads = [0.0] * len(groups)
    for file in sorted(files, key=lambda f: (-weight(f), f)):
        index = loads.index(min(loads))
        groups[index].append(file)
        loads[index] += weight(file)
    return [sorted(group) for group in groups if group]


def _terminate_tree(process: subprocess.Popen, force: bool) -> None:
    """Stop a child and everything it started. POSIX: its process group. Windows: Ctrl+Break to its group first (graceful), then
    `taskkill /T /F` by process id, because terminating npm.cmd alone leaves node, Chromium and the test server running and holding files."""
    try:
        if os.name == 'nt':
            if force:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=30)
            else:
                process.send_signal(signal.CTRL_BREAK_EVENT)
        elif hasattr(os, 'killpg'):
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        else:
            process.kill() if force else process.terminate()
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError, ValueError):
        pass


def stop_owned(grace: float = 20.0) -> None:
    """Terminate the process trees this runner started (graceful first so servers clean up, then forced); nothing else is touched."""
    for process in OWNED:
        if process.poll() is None:
            _terminate_tree(process, force=False)
    deadline = time.monotonic() + grace
    for process in OWNED:
        try:
            process.wait(max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _terminate_tree(process, force=True)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                pass
        if os.name == 'nt':
            _terminate_tree(process, force=True)          # the npm.cmd shell may be gone while its node and Chromium children remain
    OWNED.clear()


def remove_tree(path: Path, attempts: int = 6, delay: float = 0.5) -> str | None:
    """Delete a scratch directory, retrying transient Windows locks (WinError 32/5) a bounded number of times. Never raises: a cleanup
    problem is reported as a note and can never replace the result of the tests."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return None
        except FileNotFoundError:
            return None
        except OSError as error:
            last = error
            time.sleep(delay * (attempt + 1))
    return f'Could not remove {path} after {attempts} attempts ({last}); it was left in place.'


def preserve_artifacts(scratch: Path, label: str) -> str:
    """Move a failed run's reports, logs and traces to build/test-artifacts/ (ignored by Git); fall back to leaving them where they are."""
    target = ROOT / 'build' / 'test-artifacts' / f"{re.sub(r'[^A-Za-z0-9_.-]+', '-', label).strip('-')}-{time.strftime('%Y%m%dT%H%M%S')}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(scratch), str(target))
        return str(target)
    except OSError:
        return str(scratch)


@contextmanager
def cleanup_on_signals():
    """SIGTERM and SIGHUP end the runner like Ctrl+C: the `finally` blocks run, so the test servers and browsers this runner started are stopped.
    Without this a plain `kill` bypasses stop_owned() and leaves servers listening on their test ports."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    names = [name for name in ('SIGTERM', 'SIGHUP') if hasattr(signal, name)]
    def leave(number, _frame):
        raise SystemExit(128 + number)
    previous = {name: signal.signal(getattr(signal, name), leave) for name in names}
    try:
        yield
    finally:
        for name, handler in previous.items():
            signal.signal(getattr(signal, name), handler)


def playwright_tests(report: dict) -> list[tuple[float, str, str, str]]:
    """(seconds, spec file, title, status) for every test of a Playwright JSON report."""
    found: list[tuple[float, str, str, str]] = []
    def walk(suite: dict) -> None:
        for spec in suite.get('specs', []):
            for test in spec.get('tests', []):
                found.append((sum(r.get('duration', 0) for r in test.get('results', [])) / 1000, spec.get('file', suite.get('file', '')), spec.get('title', ''), test.get('status', '')))
        for child in suite.get('suites', []):
            walk(child)
    for suite in report.get('suites', []):
        walk(suite)
    return found


def playwright_failures(report: dict) -> list[str]:
    """The error of every failed test, from the JSON report: a shard log tail can miss it, the report cannot."""
    messages: list[str] = []
    def walk(suite: dict) -> None:
        for spec in suite.get('specs', []):
            for test in spec.get('tests', []):
                if test.get('status') not in {'unexpected', 'flaky'}:
                    continue
                for result in test.get('results', []):
                    error = result.get('error') or {}
                    text = re.sub(r'\x1b\[[0-9;]*m', '', error.get('message') or error.get('stack') or result.get('status', ''))
                    location = error.get('location') or {}
                    where = f" ({Path(location.get('file', '')).name}:{location.get('line')})" if location.get('file') else ''
                    messages.append(f"{spec.get('file', '')} :: {spec.get('title', '')}{where}\n    " + '\n    '.join(text.strip().splitlines()[:20]))
        for child in suite.get('suites', []):
            walk(child)
    for suite in report.get('suites', []):
        walk(suite)
    return messages


REPORTERS = 'line,json,./tests/progress-reporter.ts'   # line: the per-process log; json: the merged report; progress-reporter: live console events
BROWSER_TIMEOUT = int(os.environ.get('SAP_LENS_BROWSER_TIMEOUT', '5400'))   # seconds per Playwright process before it is stopped and diagnosed


def _progress(path: Path) -> str:
    """The last `[n/m]` position Playwright's line reporter wrote to a shard log, or '' before the first test."""
    try:
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 8192))
            found = re.findall(rb'\[(\d+)/(\d+)\]', stream.read())
        return f'test {int(found[-1][0])}/{int(found[-1][1])}' if found else ''
    except OSError:
        return ''


def _tail(path: Path, characters: int) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')[-characters:] if path.exists() else ''
    except OSError:
        return ''


def clock(seconds: float) -> str:
    seconds = int(seconds)
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600 else f'{seconds // 60:02d}:{seconds % 60:02d}'


class LiveProgress:
    """Renders the events of frontend/tests/progress-reporter.ts while the Playwright processes run: a line per finished test (or only
    failures with SAP_LENS_TEST_PROGRESS=summary), each failure with its first error lines as soon as it happens, and a periodic summary
    with completed/total, passed, failed and skipped counts per process. Shards without events fall back to the line reporter's position."""
    def __init__(self, label: str, files: list[Path], logs: list[Path], started: float):
        self.label, self.files, self.logs, self.started = label, files, logs, started
        self.offsets = [0] * len(files)
        self.partial = [b''] * len(files)
        self.total: list[int | None] = [None] * len(files)
        self.done = [0] * len(files)
        self.counts = {'passed': 0, 'failed': 0, 'skipped': 0, 'flaky': 0}
        self.failures: list[str] = []
        self.announced = False
        self.mode = os.environ.get('SAP_LENS_TEST_PROGRESS', 'tests')

    def _events(self, index: int) -> list[dict]:
        path = self.files[index]
        try:
            with path.open('rb') as stream:
                stream.seek(self.offsets[index])
                chunk = stream.read()
        except OSError:
            return []
        self.offsets[index] += len(chunk)
        data = self.partial[index] + chunk
        lines = data.split(b'\n')
        self.partial[index] = lines.pop()                              # an incomplete last line is completed by the next read
        events = []
        for line in lines:
            try:
                events.append(json.loads(line.decode('utf-8')))
            except ValueError:
                continue
        return events

    def where(self, index: int) -> str:
        return f'[shard {index + 1}] ' if len(self.files) > 1 else ''

    def poll(self) -> None:
        for index in range(len(self.files)):
            for event in self._events(index):
                kind = event.get('type')
                if kind == 'begin':
                    self.total[index] = int(event.get('total') or 0)
                elif kind == 'test-end' and event.get('outcome') != 'retrying':
                    self.done[index] += 1
                    outcome, result = event.get('outcome'), event.get('status')
                    key = 'skipped' if outcome == 'skipped' else 'flaky' if outcome == 'flaky' else 'passed' if outcome == 'expected' else 'failed'
                    self.counts[key] += 1
                    name = f"{event.get('file')}:{event.get('line')} > {event.get('title')}"
                    elapsed = clock(time.perf_counter() - self.started)
                    if key in {'failed', 'flaky'}:
                        word = 'FLAKY' if key == 'flaky' else 'TIMEOUT' if result == 'timedOut' else 'FAIL'
                        self.failures.append(name)
                        detail = '\n'.join('         ' + line for line in str(event.get('error') or '').splitlines()[:4])
                        emit(f'[{elapsed}] {status(word, "warn" if key == "flaky" else "fail", 7)} {self.where(index)}{name} ({event.get("duration", 0) / 1000:.1f}s)\n' + (detail + '\n' if detail else ''))
                    elif self.mode == 'tests':
                        word = 'SKIP' if key == 'skipped' else 'PASS'
                        emit(f'[{elapsed}] {status(word, "skip" if key == "skipped" else "pass", 7)} {self.where(index)}{name} ({event.get("duration", 0) / 1000:.1f}s)\n')
                elif kind == 'error':
                    emit(f'[{clock(time.perf_counter() - self.started)}] {status("ERROR", "fail", 7)} {self.where(index)}{str(event.get("error"))[:600]}\n')
        if not self.announced and all(total is not None for total in self.total):
            self.announced = True
            emit(f'[{self.label}] {sum(t or 0 for t in self.total)} tests in {len(self.files)} Playwright process(es)\n')

    def summary(self, finished: set[int]) -> str:
        known = all(total is not None for total in self.total)
        total = sum(t or 0 for t in self.total)
        head = (f"[{clock(time.perf_counter() - self.started)}] {sum(self.done)}/{total if known else '?'} completed | passed {count(self.counts['passed'], 'pass')}"
                f" | failed {count(self.counts['failed'], 'fail')}" + (f" | flaky {paint(self.counts['flaky'], 'warn')}" if self.counts['flaky'] else '')
                + f" | skipped {count(self.counts['skipped'], 'skip')}")
        if len(self.files) == 1:
            return head
        shards = []
        for index in range(len(self.files)):
            if self.total[index] is not None:
                state = f'{self.done[index]}/{self.total[index]}' + (f' {paint("done", "info")}' if index in finished else '')
            else:
                state = 'done' if index in finished else (_progress(self.logs[index]) or 'starting')
            shards.append(f'shard {index + 1}: {state}')
        return head + '\n         ' + ' | '.join(shards)


def _wait_for_shards(launched: list, label: str, timeout: int, live: 'LiveProgress | None' = None) -> dict[int, tuple[int, float, bool]]:
    """Wait for every Playwright process with a heartbeat, a completion line per shard and a per-process timeout.
    Returns {index: (exit code, seconds, timed out)}."""
    heartbeat = float(os.environ.get('SAP_LENS_TEST_HEARTBEAT', '30'))
    started, last_beat, done = time.perf_counter(), time.perf_counter(), {}
    total = len(launched)
    while len(done) < total:
        now = time.perf_counter()
        if live:
            live.poll()
        for index, _, process, _, out, _, _ in launched:
            if index in done:
                continue
            code = process.poll()
            if code is not None:
                if live:
                    live.poll()                                       # the process has exited: render its last events before its completion line
                done[index] = (code, now - started, False)
                print(f'[done] {label} shard {index + 1}/{total}: {paint(f"exit code {code}", "pass" if code == 0 else "fail")} after {clock(now - started)}', flush=True)
            elif now - started > timeout:
                done[index] = (124, now - started, True)
                print(f'{paint("[timeout]", "fail")} {label} shard {index + 1}/{total} exceeded {timeout}s at {_progress(out) or "startup"}; stopping it.', flush=True)
                _terminate_tree(process, force=True)
        if heartbeat and now - last_beat >= heartbeat and len(done) < total:
            last_beat = now
            if live:
                emit(live.summary(set(done)) + '\n')
            else:
                states = [f"shard {index + 1}: {'done' if index in done else (_progress(out) or 'starting')}" for index, _, _, _, out, _, _ in launched]
                print(f"[{label}] {clock(now - started)}; " + '; '.join(states), flush=True)
        time.sleep(0.5)
    return done


def run_browser(specs: list[str] | None, grep: str | None, jobs: int, label: str, extra: list[str], grep_invert: str | None = None) -> dict:
    """Run the browser tests in `jobs` independent Playwright processes, each with its own server, port and storage.

    Failures are classified: `failures` are tests that failed; `infrastructure` lists problems that stopped tests from running or reporting
    (a busy port, a server that did not start, a process without a report, a timeout). Cleanup never raises and never hides either."""
    started = time.perf_counter()
    names = specs if specs is not None else browser_specs()
    files = [f'tests/{name}.spec.ts' for name in names]
    empty = {'name': label, 'tests': 0, 'passed': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'seconds': 0.0, 'ok': True, 'infrastructure': []}
    if specs is not None and not files:
        return empty
    jobs = max(1, min(jobs, len(files) or 1, BROWSER_JOBS_MAX))
    if (busy := busy_ports(jobs)):
        problem = (f"Browser test port(s) {', '.join(map(str, busy))} already in use by another process (a stale test server?). Stop that process "
                   "yourself (find it with `ss -ltnp`, or `Get-NetTCPConnection -LocalPort 18745` in PowerShell); the runner never signals processes it did not start.")
        emit(paint('infrastructure:', 'fail') + ' ' + problem + '\n')
        return {**empty, 'errors': 1, 'ok': False, 'infrastructure': [problem]}
    groups = split_specs(files, jobs) if jobs > 1 else [files if specs is not None else []]
    kept = Path(os.environ['SAP_LENS_TEST_ARTIFACTS']) / label.replace(' ', '-') if os.environ.get('SAP_LENS_TEST_ARTIFACTS') else None
    if kept:
        kept.mkdir(parents=True, exist_ok=True)
    scratch = kept or Path(tempfile.mkdtemp(prefix='sap-lens-browser-'))
    print(f"{paint('[start]', 'info')} {label}: {len(groups)} Playwright process(es), {len(files) if specs is not None else 'all'} spec files", flush=True)
    launched: list = []
    handles: list = []
    outcome: dict[int, tuple[int, float, bool]] = {}
    try:
        with cleanup_on_signals():
            for index, group in enumerate(groups):
                report, out, err = scratch / f'report-{index}.json', scratch / f'log-{index}.out.txt', scratch / f'log-{index}.err.txt'
                command = playwright_command([*group, f'--reporter={REPORTERS}', f'--output={scratch / f"results-{index}"}'])
                if os.environ.get('SAP_LENS_TEST_REPORTERS') == 'html,junit':
                    command = [arg.replace(f'--reporter={REPORTERS}', f'--reporter={REPORTERS},html,junit') for arg in command]
                if grep:
                    command += ['--grep', grep]
                if grep_invert:
                    command += ['--grep-invert', grep_invert]
                # SAP_LENS_TEST_PYTHON: the test server and every Python subprocess of a spec use this runner's Python 3.12, not PATH's first python.
                env = {**os.environ, 'SAP_LENS_BROWSER_TEST_PORT': str(BASE_PORT + index), 'PLAYWRIGHT_JSON_OUTPUT_NAME': str(report),
                       'SAP_LENS_TEST_PYTHON': python_exe(), 'PLAYWRIGHT_HTML_OPEN': 'never', 'PLAYWRIGHT_HTML_REPORT': str(scratch / f'html-{index}'),
                       'PLAYWRIGHT_JUNIT_OUTPUT_NAME': str(scratch / f'junit-{index}.xml'), 'SAP_LENS_PROGRESS_FILE': str(scratch / f'progress-{index}.jsonl'),
                       'FORCE_COLOR': '0', 'PYTHONIOENCODING': 'utf-8'}
                # Every process writes to its own UTF-8 log; the console shows the runner's rendering of the progress events instead of raw
                # Playwright output (its terminal glyphs and the test server's stderr made PowerShell 5.1 show mojibake and NativeCommandError).
                stdout, stderr = out.open('w', encoding='utf-8', errors='replace'), err.open('w', encoding='utf-8', errors='replace')
                handles += [stdout, stderr]
                group_options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
                process = subprocess.Popen(command + extra, cwd=FRONTEND, env=env, stdout=stdout, stderr=stderr, text=True, encoding='utf-8', errors='replace', **group_options)
                OWNED.append(process)
                launched.append((index, BASE_PORT + index, process, report, out, err, group))
                print(f"{paint('[start]', 'info')} {label} shard {index + 1}/{len(groups)}: port {BASE_PORT + index}, {len(group) or 'all'} spec files, pid {process.pid}", flush=True)
            live = LiveProgress(label, [scratch / f'progress-{item[0]}.jsonl' for item in launched], [item[4] for item in launched], started)
            outcome = _wait_for_shards(launched, label, BROWSER_TIMEOUT, live)
    finally:
        stop_owned()          # an interrupt, a signal, a timeout or an error must not leave our own Chromium or test servers behind
        for handle in handles:
            handle.close()    # before anything reads or deletes the logs: an open handle is what made Windows refuse the cleanup (WinError 32)
    merged = {'tests': 0, 'passed': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'shards': [], 'shard_detail': [], 'slowest': [], 'failed': [], 'infrastructure': []}
    every = []
    for index, port, _, report, out, err, group in launched:
        code, seconds, timed_out = outcome.get(index, (1, 0.0, False))
        where = f'shard {index + 1}/{len(groups)} (port {port}, {len(group) or "all"} spec files)'
        detail = {'shard': index + 1, 'port': port, 'spec_files': len(group), 'seconds': round(seconds, 1), 'exit_code': code, 'tests': 0}
        merged['shard_detail'].append(detail)
        data = None
        if report.exists():
            try:
                data = json.loads(report.read_text(encoding='utf-8'))
            except (OSError, ValueError) as error:
                merged['infrastructure'].append(f'{where}: unreadable report ({error})')
        if timed_out:
            merged['infrastructure'].append(f'{where}: stopped after {BROWSER_TIMEOUT}s at {_progress(out) or "startup"} (SAP_LENS_BROWSER_TIMEOUT)')
        if data is None:
            merged['errors'] += 1
            if not timed_out:
                merged['infrastructure'].append(f'{where}: exit code {code} without a test report (the server or Playwright did not start)')
            emit(f'{where} produced no report.\n' + _tail(err, 3000) + _tail(out, 3000))
            continue
        stats, tests = data['stats'], playwright_tests(data)
        every += tests
        ran = stats['expected'] + stats['unexpected'] + stats['flaky']
        detail['tests'] = ran
        merged['shards'].append(round(stats['duration'] / 1000, 1))
        merged['tests'] += ran
        merged['passed'] += stats['expected']
        merged['failures'] += stats['unexpected'] + stats['flaky']
        merged['skipped'] += [['browser test', 'skipped']] * stats['skipped']
        failed = [(file, title) for _, file, title, status in tests if status in {'unexpected', 'flaky'}]
        merged['failed'] += [f'{file} :: {title} [{where}]' for file, title in failed]
        top_errors = [re.sub(r'\x1b\[[0-9;]*m', '', (item.get('message') or '')).strip() for item in data.get('errors', [])]
        if code and not failed:
            merged['errors'] += 1
            merged['infrastructure'].append(f'{where}: exit code {code} with no failed test' + (f": {top_errors[0].splitlines()[0][:300]}" if top_errors and top_errors[0] else ''))
        if code:
            emit(f'{where} {paint("failed", "fail")}' + (':\n  ' + '\n  '.join(f'{file} :: {title}' for file, title in failed) if failed else '') + '\n')
            for message in playwright_failures(data):
                emit(f'  {paint("ERROR", "fail")} {message}\n')
            emit(f'  Playwright and test-server output of {where} (last lines; complete in log-{index}.out.txt and log-{index}.err.txt):\n'
                 + _tail(err, 4000) + _tail(out, 2000) + '\n')
    merged['slowest'] = [[round(seconds, 1), file, title] for seconds, file, title, _ in sorted(every, reverse=True)[:max(SLOWEST, 10)]]
    ok = not merged['failures'] and not merged['infrastructure'] and all(outcome.get(item[0], (1,))[0] == 0 for item in launched)
    if not kept and ok:
        note = remove_tree(scratch)
        if note:
            merged.setdefault('notes', []).append(note)
    elif not kept:
        merged['artifacts'] = preserve_artifacts(scratch, label)
        print(f"Artifacts of the failed run (reports, logs, traces): {merged['artifacts']}", flush=True)
    merged.update(name=label, seconds=time.perf_counter() - started, ok=ok)
    # Keep the established `N passed (Ns)` line: scripts/testing/ci.py reads the test count from it.
    print(f"\n{merged['passed']} passed ({merged['seconds']:.0f}s)" + (f", {merged['failures']} failed" if merged['failures'] else ''), flush=True)
    print(f"[done] {label}: {count(merged['passed'], 'pass')} passed, {count(merged['failures'], 'fail')} failed, {count(len(merged['skipped']), 'skip')} skipped"
          + (f", {paint(len(merged['infrastructure']), 'fail')} infrastructure problem(s)" if merged['infrastructure'] else '') + f" ({merged['seconds']:.0f}s)", flush=True)
    return merged


def regression_browser(jobs: int, extra: list[str]) -> list[dict]:
    """REGRESSION browser set in two disjoint runs: the non-matrix tests of the critical specs, then every test tagged as critical elsewhere."""
    profile = load_map()['profiles']
    tags = profile['regression_browser_tags']
    specs = profile['regression_browser_specs']
    full_only = profile.get('full_only_tags', '')
    excluded = '|'.join(item for item in ('@visual', tags, full_only) if item)
    return [run_browser(specs, None, min(jobs, len(specs)), f'browser regression: critical specs ({len(specs)})', extra, grep_invert=excluded),
            run_browser(None, tags, jobs, f'browser regression: tests tagged {tags}', extra)]


# ---------------------------------------------------------------------------- static and release

def fast_static_checks() -> list[dict]:
    """The cheap checks of every phase: whitespace, documentation links, workflow contracts, both linters and the TypeScript check."""
    py = python_exe()
    return [step(name, command) for name, command in (
        ('whitespace (git diff --check)', ['git', 'diff', '--check']),
        ('documentation links', [py, 'scripts/check-docs.py']),
        ('workflow contracts', [py, 'scripts/check-workflows.py']),
        ('Python lint (ruff)', [py, '-m', 'ruff', 'check', 'backend', 'scripts']),
        ('frontend lint (ESLint)', [npm(), '--prefix', str(FRONTEND), 'run', 'lint']),
        ('TypeScript check', [npm(), '--prefix', str(FRONTEND), 'run', 'check:types']))]


def quick_static_checks(frontend: bool) -> list[dict]:
    """QUICK: the checks that take seconds; ESLint and the TypeScript check only when frontend files changed."""
    py = python_exe()
    checks = [('whitespace (git diff --check)', ['git', 'diff', '--check']), ('documentation links', [py, 'scripts/check-docs.py']),
              ('workflow contracts', [py, 'scripts/check-workflows.py']), ('test ownership map', [py, str(Path(__file__).resolve()), 'check']),
              ('Python lint (ruff)', [py, '-m', 'ruff', 'check', 'backend', 'scripts'])]
    if frontend:
        checks += [('frontend lint (ESLint)', [npm(), '--prefix', str(FRONTEND), 'run', 'lint']), ('TypeScript check', [npm(), '--prefix', str(FRONTEND), 'run', 'check:types'])]
    return [step(name, command) for name, command in checks]


def unit_tests() -> dict:
    return step('frontend unit tests (node --test)', [npm(), '--prefix', str(FRONTEND), 'run', 'test:unit'])


def static_checks() -> list[dict]:
    py = python_exe()
    checks = [
        ('documentation links', [py, 'scripts/check-docs.py']),
        ('workflow contracts', [py, 'scripts/check-workflows.py']),
        ('Lucide catalog', ['node', 'scripts/sync-lucide-catalog.mjs', '--check']),
        ('Python lint (ruff)', [py, '-m', 'ruff', 'check', 'backend', 'scripts']),
        ('frontend lint (ESLint)', [npm(), '--prefix', str(FRONTEND), 'run', 'lint']),
        ('whitespace (git diff --check)', ['git', 'diff', '--check']),
        ('pip check', [py, '-m', 'pip', 'check']),
    ]
    return [step(name, command) for name, command in checks]


def release_checks() -> tuple[list[dict], list[str]]:
    py = python_exe()
    results, unavailable = [], []
    results.append(step('npm audit (production)', [npm(), '--prefix', str(FRONTEND), 'audit', '--omit=dev']))
    if subprocess.run([py, '-m', 'pip_audit', '--version'], capture_output=True).returncode == 0:
        results.append(step('pip-audit', [py, '-m', 'pip_audit', '--vulnerability-service', 'pypi', '--progress-spinner', 'off']))
    else:
        unavailable.append('pip-audit is not installed (see docs/development/CI.md); Python advisories were NOT checked')
    if shutil.which('pwsh'):
        results.append(step('PowerShell parse and safety guards', ['pwsh', '-NoProfile', '-File', 'scripts/check-powershell.ps1']))
    else:
        unavailable.append('pwsh is not installed; PowerShell script checks were NOT run')
    if shutil.which('actionlint'):
        results.append(step('workflow lint', [py, 'scripts/testing/ci.py', 'lint']))
    else:
        unavailable.append('actionlint is not installed; workflow schema/expression lint was NOT run (contracts ran in regression)')
    unavailable.append('Docker image build/run, Windows installer/service/WebView2, native Linux package and systemd acceptance need their own environments or the manual build workflows; they were NOT run here (see docs/deployment/README.md)')
    return results, unavailable


# ---------------------------------------------------------------------------- reporting

def jobs_value(value: str, kind: str) -> int:
    """`auto` parallelizes the backend only: browser processes compete for CPUs, so they are opt-in (--browser-jobs)."""
    if value == 'auto':
        return 1 if kind == 'browser' else max(1, min(3, os.cpu_count() or 2))
    return max(1, int(value))


def browser_jobs_value(option: str | None, fallback: int) -> int:
    """`--browser-jobs` (or SAP_LENS_BROWSER_JOBS): a number, or `auto` = one process per spare CPU, at least 1 and at most 3. Never more than 3."""
    value = option or os.environ.get('SAP_LENS_BROWSER_JOBS') or ''
    if not value:
        return min(fallback, BROWSER_JOBS_MAX)
    if value == 'auto':
        return max(1, min(BROWSER_JOBS_MAX, (os.cpu_count() or 2) - 1))
    return max(1, min(int(value), BROWSER_JOBS_MAX))


def fmt(seconds: float) -> str:
    return f'{seconds:6.1f}s'


def report(profile: str, scope: str, stages: list[dict], notes: list[str], output: str | None) -> int:
    """Summary of every stage. Exit code: 0 everything passed; 1 at least one test or check failed; 2 only infrastructure failed
    (a test server, Playwright, a worker or a tool could not run or report), so a red run always says which kind it is."""
    print(f'\nSAP Lens test profile: {profile.upper()} ({scope})')
    ok, test_failure, infrastructure = True, False, []
    totals = {'passed': 0, 'failed': 0, 'skipped': 0}
    for stage in stages:
        counts, failed = '', 0
        problems = stage.get('infrastructure', [])
        if stage.get('tests') is not None:
            failed = stage['failures'] + (0 if problems else stage['errors'])
            passed = stage.get('passed', stage['tests'] - stage['failures'] - stage['errors'])
            totals['passed'] += passed; totals['failed'] += failed; totals['skipped'] += len(stage['skipped'])
            counts = f"{count(passed, 'pass')} passed, {count(failed, 'fail')} failed, {count(len(stage['skipped']), 'skip')} skipped"
            if stage.get('shards') and len(stage['shards']) > 1:
                counts += f"; process seconds {stage['shards']}"
            test_failure |= failed > 0
        elif not stage['ok'] and not problems:
            test_failure = True                                          # a static check that ran and found something
        word = 'PASS' if stage['ok'] else ('FAIL' if (failed or not problems) else 'FAIL (infrastructure)')
        print(f"  {status(word, 'pass' if stage['ok'] else 'fail')}  {fmt(stage['seconds'])}  {stage['name']}  {counts}")
        for problem in problems:
            print(f"          {paint('infrastructure:', 'fail')} {problem}")
        infrastructure += problems
        for test, reason in stage.get('skipped', []):
            if reason != 'skipped':
                print(f'          {paint("skipped:", "skip")} {test.split(" ")[0]} ({reason})')
        for leak in stage.get('resource_warnings', []):
            print(f'          {paint("resource warning:", "warn")} {leak}')
        for seconds, file, title in stage.get('slowest', [])[:SLOWEST] if (profile in ('regression', 'full') or SLOWEST_REQUESTED) else []:
            print(f'          slowest: {seconds:6.1f}s  {file} :: {title[:80]}')
        if stage.get('artifacts'):
            print(f"          artifacts: {stage['artifacts']}")
        for note in stage.get('notes', []):
            print(f'          note: {note}')
        ok &= stage['ok']
    for note in notes:
        print(f'  {paint("NOTE", "warn")}  {note}')
    if profile in ('smoke', 'targeted', 'quick', 'changed'):
        print(f'  {paint("NOTE", "warn")}  {profile} is a partial run; run `regression` before pushing a finished phase and `full` before a merge or release.')
    elif profile == 'regression':
        print(f'  {paint("NOTE", "warn")}  regression is the curated critical set, not the complete collection; `full` runs everything.')
    code = 0 if ok else (1 if test_failure else 2)
    if output:
        try:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps({'profile': profile, 'scope': scope, 'ok': ok, 'exit_code': code, 'infrastructure': infrastructure,
                                               'stages': stages, 'notes': notes}, indent=1, default=str), encoding='utf-8')
        except OSError as error:
            ok = False
            code = 1 if test_failure else 2
            print(f"  {paint('infrastructure:', 'fail')} JSON report could not be saved ({type(error).__name__}); check the report destination and permissions.")
    verdict = 'OK' if ok else ('FAILED (tests)' if test_failure else 'FAILED (infrastructure only: no test failed, but not everything ran)')
    print(f"  tests: {count(totals['passed'], 'pass')} passed, {count(totals['failed'], 'fail')} failed, {count(totals['skipped'], 'skip')} skipped")
    print(f"  total {fmt(sum(s['seconds'] for s in stages))}  ->  {paint(verdict, 'pass' if ok else 'fail')}")
    failed_tests = [name for stage in stages for name in stage.get('failed', [])]
    if failed_tests:
        print(f'  {paint("failed tests:", "fail")}')
        for name in failed_tests[:30]:
            print(f'    {name}')
        if len(failed_tests) > 30:
            print(f'    ... {len(failed_tests) - 30} more in the JSON report')
    code = 0 if ok else (1 if test_failure else 2)
    print(f'Summary: {count(totals["passed"], "pass")} passed | {count(totals["failed"], "fail")} failed | {count(totals["skipped"], "skip")} skipped')
    print(f'Result: {paint("PASSED", "pass") if ok else paint(verdict, "fail")} | Duration: {clock(sum(s["seconds"] for s in stages))} | Exit code: {code}'
          + (f' | Log: {_LOG.name}' if _LOG else '') + (f' | Report: {output}' if output else ''), flush=True)
    return code


def main(argv: list[str]) -> int:
    if len(argv) > 2 and argv[0] == '_backend':
        return run_backend_worker(argv[2:], Path(argv[1]))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('profile', choices=['quick', 'targeted', 'regression', 'full', 'changed', 'smoke', 'fast', 'release', 'list', 'check'],
                        help='quick | targeted | regression | full (see docs/development/TESTING.md#profiles); changed is the CI selection, smoke a sub-check; fast and release are earlier names of quick and full')
    parser.add_argument('features', nargs='*', help='features for the targeted profile (see `list`)')
    side = parser.add_mutually_exclusive_group()
    side.add_argument('--backend', action='store_true', help='backend tests only')
    side.add_argument('--browser', action='store_true', help='browser tests only')
    parser.add_argument('--jobs', default='auto', help='parallel processes (default auto: backend min(3, CPUs), browser 1; 1 disables)')
    parser.add_argument('--browser-jobs', help='browser processes: a number up to 3 or `auto` (one per spare CPU, 1 to 3); default 1 or SAP_LENS_BROWSER_JOBS')
    parser.add_argument('--grep', help='additional Playwright title filter for browser tests')
    parser.add_argument('--base', help='commit to compare with: quick/targeted default HEAD (uncommitted and untracked changes); changed default BASE_SHA or HEAD~1')
    parser.add_argument('--plan', action='store_true', help='print the selection without running anything, for every profile (changed also writes GitHub outputs)')
    parser.add_argument('--stage', choices=['backend', 'browser'], help='changed profile: run only this part of the selection')
    parser.add_argument('--no-build', action='store_true', help='skip the frontend build even if sources changed')
    parser.add_argument('--report', help='write a JSON summary to this file')
    parser.add_argument('--list-tests', action='store_true', help='print the selected files and exit')
    parser.add_argument('--verbose', action='store_true', help='backend: one line per test and unbuffered test output (default: quiet; output of a test is shown only when it fails)')
    parser.add_argument('--slowest', type=int, metavar='N', help='list the N slowest tests in the summary (default 10 for regression/release, 0 otherwise)')
    parser.add_argument('--spec', action='append', metavar='NAME', help='browser: run only this spec file (name without .spec.ts, repeatable); '
                        'with --grep and Playwright options such as --repeat-each 5 this is Level 1 of the progressive validation')
    parser.add_argument('--test', action='append', metavar='NAME', help='backend: run only this unittest name (module, module.Class or module.Class.test); repeatable; use with the targeted profile')
    parser.add_argument('--log', metavar='FILE', help='also write everything this run prints to FILE')
    args, extra = parser.parse_known_args(argv)
    global SLOWEST, SLOWEST_REQUESTED, _LOG
    if args.verbose:
        os.environ['SAP_LENS_TEST_VERBOSE'] = '1'
    if args.slowest is not None:
        SLOWEST, SLOWEST_REQUESTED = max(0, args.slowest), args.slowest > 0
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, errors='replace')   # progress appears as it is printed, also through a pipe
        except (AttributeError, ValueError):
            pass
    # Everything the runner prints goes to stdout. Writing to stderr made Windows PowerShell 5.1 wrap ordinary progress in NativeCommandError
    # records when the output was redirected; the exit code alone says whether the run failed.
    global PAINT
    colors = 'markers' if os.environ.pop('SAP_LENS_TEST_COLOR_MARKERS', '0') == '1' else color_mode(sys.stdout)   # set by validate.py
    PAINT = bool(colors)
    sys.stdout = SafeConsole(sys.stdout, colors)
    sys.stderr = sys.stdout
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        _LOG = open(args.log, 'w', encoding='utf-8')
        sys.stdout = Tee(sys.stdout, _LOG)
        sys.stderr = sys.stdout                 # failure details (step output, shard log tails) must reach the log too
    renamed = {'fast': 'quick', 'release': 'full'}
    if args.profile in renamed:
        print(f'NOTE: `{args.profile}` is now `{renamed[args.profile]}`.', flush=True)
        args.profile = renamed[args.profile]
    base = args.base or (os.environ.get('BASE_SHA', 'HEAD~1') if args.profile == 'changed' else 'HEAD')
    backend_jobs = jobs_value(args.jobs, 'backend')
    browser_jobs = browser_jobs_value(args.browser_jobs, jobs_value(args.jobs, 'browser'))
    want_backend, want_browser = not args.browser, not args.backend
    if args.profile not in ('list', 'check'):
        print(f"{paint('SAP Lens ' + args.profile.upper(), 'info')}: backend processes {backend_jobs}, browser processes {browser_jobs}"
              + (f', log {args.log}' if args.log else '') + ' (live progress below; SAP_LENS_TEST_PROGRESS=summary shows only failures and summaries)', flush=True)

    if args.profile == 'check':
        problems = coverage_problems()
        print('\n'.join(problems) or 'Every backend module and browser spec is mapped to exactly one feature.')
        return 1 if problems else 0
    if args.profile == 'list':
        for name, feature in load_map()['features'].items():
            print(f"{name:20s} backend {len(feature['backend']):2d} modules, browser {len(feature['browser']):2d} specs  {feature['description']}")
        return 0
    problems = coverage_problems()
    if problems:
        raise SystemExit('Test map is out of date:\n' + '\n'.join(problems))

    stages: list[dict] = []
    notes: list[str] = []
    # --plan never executes a test, a build or a check, whatever the profile: it is the listing for every profile except `changed`,
    # which prints its own plan below. An explicit selection is echoed here because those branches run before the profiles.
    if args.plan and args.profile != 'changed':
        args.list_tests = True
        if args.spec or args.test:
            print('backend: ' + ' '.join(args.test or []) + '\nbrowser: ' + ' '.join(args.spec or []) + (f' --grep {args.grep}' if args.grep else ''))
            return 0

    def smoke_stages() -> None:
        smoke = load_map()['smoke']
        if want_backend:
            stages.append(run_backend(smoke['backend'], 1, 'backend smoke', split=False))
        if want_browser:
            built = None if args.no_build else build_frontend()
            if built:
                stages.append(built)
            stages.append(run_browser(None, smoke['browser_tag'], 1, 'browser smoke', extra))

    def targeted_stages(modules: list[str], specs: list[str]) -> None:
        if want_backend and modules:
            stages.append(run_backend(modules, 1, 'backend targeted', split=False))
        if want_browser and specs:
            built = None if args.no_build else build_frontend()
            if built and not any(stage['name'] == built['name'] for stage in stages):
                stages.append(built)
            stages.append(run_browser(specs, args.grep, min(browser_jobs, len(specs)), 'browser targeted', extra))

    if args.spec:
        known = set(browser_specs())
        names = [name[:-len('.spec.ts')] if name.endswith('.spec.ts') else name for name in (Path(item).name for item in args.spec)]
        if args.profile != 'targeted' or args.features or args.backend:
            raise SystemExit('--spec runs browser spec files and is used as: run-tests.py targeted --spec NAME [--spec NAME ...] [--grep TEXT] [--test NAME]')
        if unknown := [name for name in names if name not in known]:
            raise SystemExit(f"Unknown spec file(s): {', '.join(unknown)} (names of frontend/tests/*.spec.ts without .spec.ts)")
        if args.test:
            stages.append(run_backend(args.test, 1, 'backend selected tests', split=False))
        built = None if args.no_build else build_frontend()
        if built:
            stages.append(built)
        stages.append(run_browser(names, args.grep, min(browser_jobs, len(names)), f'browser selected specs ({len(names)})', extra))
        return report('targeted', ', '.join(names) + (f' --grep {args.grep}' if args.grep else ''), stages, notes, args.report)
    if args.test:
        if args.profile != 'targeted' or args.features or args.browser:
            raise SystemExit('--test runs backend unittest names and is used as: run-tests.py targeted --test NAME [--test NAME ...]')
        stages.append(run_backend(args.test, 1, 'backend selected tests', split=False))
        return report('targeted', ', '.join(args.test), stages, notes, args.report)
    if args.profile == 'changed':
        plan = plan_changes(changed_files(base))
        print(json.dumps({key: value for key, value in plan.items() if key != 'files'}, indent=1))
        if args.plan:
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                    stream.write(f"backend={plan['backend']}\nfrontend={'true' if plan['frontend'] else 'false'}\nbrowser={'true' if plan['browser'] else 'false'}\n")
            return 0
        scope = f"changes since {base}: backend {plan['backend']}, frontend {'yes' if plan['frontend'] else 'no'}"
        if args.stage in (None, 'backend'):
            everything = plan['backend'] == 'full'
            stages.append(run_backend(backend_modules() if everything else plan['modules'], backend_jobs, f"backend {'regression' if everything else 'selection'}", split=True))
        if args.stage in (None, 'browser') and plan['browser']:
            smoke = load_map()['smoke']
            if not args.no_build and args.stage is None:
                built = build_frontend()
                if built:
                    stages.append(built)
            stages.append(run_browser(None, smoke['browser_tag'], 1, 'browser smoke', extra))
            if plan['specs']:
                stages.append(run_browser(plan['specs'], args.grep, min(browser_jobs, len(plan['specs'])), 'browser changed specs', extra))
    elif args.profile == 'smoke':
        scope = 'critical backend tests + browser tests tagged @smoke'
        smoke = load_map()['smoke']
        if args.list_tests:
            print('\n'.join(smoke['backend']) + f"\nbrowser: --grep {smoke['browser_tag']}")
            return 0
        smoke_stages()
    elif args.profile in ('quick', 'targeted') and not args.features:
        files = local_changes(base)
        if files is None:
            raise SystemExit(f'Cannot compare with {base}; pass --base COMMIT or name features (targeted FEATURE ...).')
        plan = plan_targeted(files)
        mapping = load_map()
        if args.list_tests or args.plan:
            print(json.dumps({key: plan[key] for key in ('modules', 'specs', 'features', 'broad_backend', 'broad_browser', 'security', 'reasons')}, indent=1))
            return 0
        if args.profile == 'quick':
            scope = f'{len(files)} changed path(s) since {base}: static checks, frontend unit tests, backend modules the change reaches; no browser'
            if want_backend:
                stages += quick_static_checks(plan['frontend'])
                stages.append(unit_tests())
                direct = {m for m in plan['modules'] if any(f'backend/tests/{m}.py' == path for path in files)}
                if plan['broad_backend']:
                    stages.append(run_backend(mapping['smoke']['backend'], 1, 'backend smoke (the change is too broad for QUICK)', split=False))
                    notes.append('The change reaches beyond any mapped area; QUICK ran the backend smoke set. Run TARGETED or REGRESSION next.')
                else:
                    # Release/packaging modules are deferred only when the change reaches them indirectly; a change to packaging itself runs them.
                    direct_release = set(plan['features']) & set(mapping['profiles']['release_features'])
                    deferred = set() if direct_release else release_modules() - direct
                    modules = sorted(set(plan['modules']) - deferred)
                    skipped = sorted(set(plan['modules']) - set(modules))
                    stages.append(run_backend(modules, backend_jobs, f'backend modules reached by the change ({len(modules)})', split=True))
                    if skipped:
                        notes.append(f'Release/packaging modules left to TARGETED/FULL: {len(skipped)} ({", ".join(skipped[:6])}{", ..." if len(skipped) > 6 else ""}).')
            notes.append('QUICK never starts a browser; browser tests the change reaches run in TARGETED.')
        else:
            scope = f'{len(files)} changed path(s) since {base}: backend modules and browser specs the change reaches, browser smoke'
            if want_backend:
                if plan['broad_backend']:
                    stages.append(run_backend(backend_modules(), backend_jobs, 'backend (whole suite: unresolved change)', split=True))
                elif plan['modules']:
                    stages.append(run_backend(plan['modules'], backend_jobs, f"backend modules reached by the change ({len(plan['modules'])})", split=True))
            if want_browser and plan['browser']:
                built = None if args.no_build else build_frontend()
                if built:
                    stages.append(built)
                stages.append(run_browser(None, mapping['smoke']['browser_tag'], 1, 'browser smoke', extra))
                if plan['broad_browser']:
                    stages += regression_browser(browser_jobs, extra)
                    notes.append('A widely shared frontend file or helper changed: the regression browser set ran instead of every consumer; FULL runs all specs.')
                elif plan['specs']:
                    stages.append(run_browser(plan['specs'], args.grep, min(browser_jobs, len(plan['specs'])), f"browser specs reached by the change ({len(plan['specs'])})", extra))
        for reason in plan['reasons'][:12]:
            notes.append(reason)
        if not files or all(classify(path) == 'docs' for path in files):
            notes.append('Only documentation changed (or nothing): the repository integrity modules and static checks cover it.')
    elif args.profile in ('quick', 'targeted'):
        modules, specs = selection(args.features)
        if args.profile == 'quick':
            specs = []
        scope = ', '.join(args.features) + (' (no browser)' if args.profile == 'quick' else '')
        if args.list_tests:
            print('backend: ' + ' '.join(modules) + '\nbrowser: ' + ' '.join(specs))
            return 0
        if args.profile == 'quick' and want_backend:
            stages += quick_static_checks(True)
            stages.append(unit_tests())
        targeted_stages(modules, specs)
        if not stages:
            notes.append('The selected features have no tests for the chosen side.')
    elif args.profile == 'regression':
        mapping = load_map()
        excluded = release_modules()
        modules = [m for m in backend_modules() if m not in excluded]
        scope = 'critical backend contracts (all modules except release/packaging), critical browser workflows, core accessibility, static checks'
        if args.list_tests:
            print(f"backend: {len(modules)} of {len(backend_modules())} modules (excluded: release features {', '.join(mapping['profiles']['release_features'])})\n"
                  f"browser: non-@visual tests of {', '.join(mapping['profiles']['regression_browser_specs'])} + tests tagged {mapping['profiles']['regression_browser_tags']}")
            return 0
        if want_backend:
            stages.append(run_backend(modules, backend_jobs, f'backend regression ({len(modules)} modules, {backend_jobs} process(es))', split=True))
        if want_browser:
            built = None if args.no_build else build_frontend()
            if built:
                stages.append(built)
            stages += regression_browser(browser_jobs, extra)
        if want_backend and want_browser:
            stages += quick_static_checks(True)
            stages.append(unit_tests())
        notes.append(f'Not in REGRESSION (run FULL): release/packaging modules ({len(excluded)}), @visual theme/viewport matrices, '
                     f"full-only integration tests ({mapping['profiles'].get('full_only_tags', 'none')}), the remaining browser specs, npm/pip audits and platform-specific checks.")
    else:
        scope = 'every backend module, browser test and frontend unit test, build, static checks and the release checks this machine can run'
        modules, specs = backend_modules(), browser_specs()
        if args.list_tests:
            print(f'backend: {len(modules)} modules\nbrowser: {len(specs)} specs')
            return 0
        if want_backend:
            stages.append(run_backend(modules, backend_jobs, f'backend full ({backend_jobs} process(es))', split=True))
        if want_browser:
            built = None if args.no_build else build_frontend(force=True)
            if built:
                stages.append(built)
            stages.append(run_browser(None, args.grep, browser_jobs, f'browser full ({browser_jobs} process(es))', extra))
        if want_backend and want_browser:
            stages += static_checks()
            stages.append(unit_tests())
            extra_stages, unavailable = release_checks()
            stages += extra_stages
            notes += unavailable
        if args.backend or args.browser:
            notes.append('Only one side was selected; this is not a complete FULL run.')
    return report(args.profile, scope, stages, notes, args.report)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
