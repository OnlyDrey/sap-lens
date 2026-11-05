"""Actionable build failures: what failed, how, where and what to try, without leaking secrets.

`StageFailure` is a `ValueError` so the existing orchestrator handlers keep working; the manifest uses `as_record()`. Windows file-lock
errors are classified from the captured output so that only transient locks are retried and permanent permission errors are explained."""
import os
import re
import shlex

SECRET_NAME = re.compile(r'TOKEN|SECRET|PASSW|KEY|CREDENTIAL|AUTH', re.I)
URL_CREDENTIALS = re.compile(r'(?<=//)[^/\s:@]+:[^@\s/]+@')
KEYED_SECRET = re.compile(r'(?i)\b(authorization|_authtoken|password|passwd|token|secret|api[-_]?key)\b(\s*[=:]\s*)(?:bearer\s+)?\S+')
LOCKED = re.compile(r'\bEBUSY\b|\bENOTEMPTY\b|WinError (?:32|33)\b|used by another process|resource busy or locked|errno -?4082\b', re.I)
PERMISSION = re.compile(r'\bEACCES\b|WinError 5\b|access is denied|errno -?13\b', re.I)
EPERM = re.compile(r'\bEPERM\b|errno -?4048\b', re.I)
PATHS = (re.compile(r"npm error path (.+)"), re.compile(r"path: ?'([^']+)'"), re.compile(r"'([A-Za-z]:\\[^']+|/[^']+)'"),
         re.compile(r'(?:unlink|rename|rmdir|open|scandir|mkdir) (?:\'|")?([A-Za-z]:\\[^\'"\r\n]+|/[^\'"\r\n]+)'))
OPERATION = re.compile(r'(?:npm error )?syscall (\w+)|\b(unlink|rename|rmdir|open|scandir|mkdir|copyfile)\b')


def redact(text, environment=None):
    """Remove credential-looking values: secret environment variable contents, URL credentials and keyed tokens."""
    text = str(text)
    for name, value in (os.environ if environment is None else environment).items():
        if SECRET_NAME.search(name) and len(str(value)) >= 6:
            text = text.replace(str(value), '<redacted>')
    return KEYED_SECRET.sub(lambda m: f'{m.group(1)}{m.group(2)}<redacted>', URL_CREDENTIALS.sub('<redacted>@', text))


def display(command):
    return redact(' '.join(shlex.quote(str(part)) if re.search(r'\s', str(part)) else str(part) for part in command))


def tail(text, lines=20):
    kept = [line.rstrip() for line in str(text).splitlines() if line.strip()]
    return redact('\n'.join(kept[-lines:]))


def classify_lock(text):
    """{'kind': 'locked'|'permission', 'code', 'path', 'operation'} for a Windows-style file access failure, else None.

    `locked` is transient (another process holds the file; on Windows npm reports EPERM for unlink/rename of a busy file) and may be retried a
    few times. `permission` (EACCES, access denied) is not: retrying cannot fix the account's rights."""
    text = str(text)
    if PERMISSION.search(text) and not LOCKED.search(text):
        kind, code = 'permission', (PERMISSION.search(text).group(0))
    elif LOCKED.search(text):
        kind, code = 'locked', LOCKED.search(text).group(0)
    elif EPERM.search(text):
        kind, code = 'locked', 'EPERM'
    else:
        return None
    path = next((m.group(1).strip() for pattern in PATHS if (m := pattern.search(text))), None)
    operation = next((m.group(1) or m.group(2) for m in [OPERATION.search(text)] if m), None)
    return dict(kind=kind, code=code, path=redact(path) if path else None, operation=operation)


def hint(stage, lock):
    if lock and lock['kind'] == 'locked':
        return ('A file or folder was locked by another process (a running dev server, editor, antivirus scan or search indexer). SAP Lens never stops '
                'other processes. Close programs using the repository or exclude the path from real-time scanning where your policy allows, then '
                'run the same command again: the isolated frontend workspace makes a retry safe.')
    if lock:
        return ('The account is not allowed to change that path. Check ownership and permissions of the repository and build folders. '
                'Administrator rights are not required for a normal build and are not requested.')
    return None


class StageFailure(ValueError):
    """A failed build stage with everything needed to diagnose it. The message is the multi-line terminal summary."""

    def __init__(self, stage, command, cwd, exit_code, output='', log=None, failure_class='stage', note=None):
        self.stage, self.command, self.cwd, self.exit_code = stage, display(command), str(cwd), exit_code
        self.output_tail, self.log, self.failure_class = tail(output), str(log) if log else None, failure_class
        self.lock = classify_lock(output)
        self.hint = hint(stage, self.lock) or note
        self.cause = self._cause()
        super().__init__(self.summary())

    def _cause(self):
        if self.lock:
            where = f' on {self.lock["path"]}' if self.lock['path'] else ''
            operation = f' while running {self.lock["operation"]}' if self.lock['operation'] else ''
            return f'{self.lock["code"]}{operation}{where}'
        lines = self.output_tail.splitlines()
        return next((line.strip() for line in reversed(lines) if re.search(r'error|failed|cannot|fatal', line, re.I)), lines[-1].strip() if lines else None)

    def summary(self):
        rows = [f'Build stage failed: {self.stage}', f'Command: {self.command}', f'Working directory: {self.cwd}', f'Exit code: {self.exit_code}']
        if self.cause: rows.append(f'Error: {self.cause}')
        if self.hint: rows.append(f'Possible cause: {self.hint}')
        if self.output_tail: rows.append('Last output:\n' + '\n'.join('  ' + line for line in self.output_tail.splitlines()))
        if self.log: rows.append(f'Detailed log: {self.log}')
        return '\n'.join(rows)

    def as_record(self):
        return dict(failed_stage=self.stage, failure_class=self.failure_class, command=self.command, cwd=self.cwd, exit_code=self.exit_code, error=self.cause or self.stage,
                    hint=self.hint, output_tail=self.output_tail.splitlines(), log=self.log, file_lock=self.lock)


class BlockedByShared(ValueError):
    """A target that was not attempted because shared validation already failed in this run."""

    def __init__(self, original):
        self.original = original
        super().__init__('Shared local validation failed earlier in this run; inspect build.log. No repeated full suite was started.')
