"""Optional local employee enrichment. No name guessing or recursive traversal; confirmed records use a private snapshot."""
import csv
import hashlib
import io
import json
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HEADERS = 'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'.split(';')
MAX_BYTES = 50 * 1024 * 1024


def normalized(value):
    return value.strip().casefold()


def sap_email_owners(users):
    from collections import Counter
    counts = Counter()
    for user in users:
        counts.update({normalized(email) for email in user['emails'] if email.strip()})
    return counts


def match_sap_identity(directory, user, owners):
    # Shared SAP email addresses cannot establish a reliable one-person identity.
    if any(owners.get(normalized(email), 0) > 1 for email in user['emails'] if email.strip()):
        return dict(status='ambiguous_sap_email', employee=None)
    return directory.match(user['emails'])


def parse_directory(path):
    source = Path(path)
    if not source.is_absolute():
        raise ValueError('Choose an absolute Employee Directory CSV path.')
    initial = source.stat()
    with source.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    final = source.stat()
    if (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
        raise ValueError('The Employee Directory CSV changed while being read. Wait for the export to finish and retry.')
    if len(raw) > MAX_BYTES:
        raise ValueError('Employee Directory CSV exceeds the 50 MB limit.')
    try:
        reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), delimiter=';', strict=True)
        header = next(reader, [])
        keys = [normalized(key) for key in header]
        expected = {normalized(key): key for key in HEADERS}
        if len(keys) != len(expected) or set(keys) != set(expected):
            raise ValueError('Employee Directory requires all 16 documented headers, without duplicates, separated by semicolons.')
        rows = []
        for row in reader:
            if not row or not any(value.strip() for value in row):
                continue
            if len(row) != len(keys) or any(len(value) > 4096 or '\x00' in value for value in row):
                raise ValueError('Employee Directory contains malformed rows or oversized fields.')
            if len(rows) >= 100_000:
                raise ValueError('Employee Directory exceeds the 100,000 record limit.')
            record = {expected[key]: value.strip() for key, value in zip(keys, row)}
            record['id'] = str(len(rows))
            rows.append(record)
    except UnicodeError:
        raise ValueError('Employee Directory must be valid UTF-8 semicolon CSV with correctly quoted fields.') from None
    except csv.Error:
        raise ValueError('Employee Directory contains malformed CSV quoting. Correct the export before importing.') from None
    if not rows:
        raise ValueError('Employee Directory contains no employee records.')
    return Directory(rows, source.name, hashlib.sha256(raw).hexdigest())


class Directory:
    def __init__(self, rows, filename, digest):
        self.rows, self.filename, self.digest = rows, filename, digest
        self.imported_at = datetime.now(timezone.utc).isoformat()
        self._report = None
        self.indexes = {}
        for field in ['Mail', 'DistinguishedName', 'SamAccountName']:
            index = defaultdict(list)
            for record in rows:
                if key := normalized(record[field]): index[key].append(record)
            self.indexes[field] = index

    def manager(self, record):
        for source, target in [('ManagerMail', 'Mail'), ('ManagerDN', 'DistinguishedName'), ('ManagerSamAccountName', 'SamAccountName')]:
            if key := normalized(record[source]):
                matches = self.indexes[target].get(key, [])
                if len(matches) == 1:
                    return ('self_reference', None) if matches[0]['id'] == record['id'] else ('resolved', matches[0])
                # Never fall back after an ambiguous preferred relationship.
                if len(matches) > 1: return 'ambiguous', None
                # A present preferred key that conflicts with fallback evidence is not guessed.
                return 'unresolved', None
        return 'missing', None

    def view(self, record):
        status, manager = self.manager(record)
        return dict(id=record['id'], name=record['Name'], email=record['Mail'], department=record['Department'],
                    title=record['Title'], site=record['Site'], username=record['SamAccountName'],
                    account_status={'true': 'Enabled', 'false': 'Disabled', '1': 'Enabled', '0': 'Disabled'}.get(normalized(record['Enabled']), 'Unknown'),
                    manager=dict(name=record['ManagerName'], email=record['ManagerMail'], department=record['ManagerDepartment'],
                                 title=record['ManagerTitle'], username=record['ManagerSamAccountName'],
                                 status=status, employee_id=manager['id'] if manager else None))

    def match(self, emails):
        keys = {normalized(email) for email in emails if email.strip()}
        if not keys: return dict(status='missing_email', employee=None)
        if any(len(self.indexes['Mail'].get(key, [])) > 1 for key in keys):
            return dict(status='duplicate_email', employee=None)
        records = {record['id']: record for key in keys for record in self.indexes['Mail'].get(key, [])}
        if len(keys) > 1 or len(records) > 1: return dict(status='ambiguous_sap_email', employee=None)
        return dict(status='matched' if records else 'unmatched', employee=self.view(next(iter(records.values()))) if records else None)

    def report(self):
        if self._report is not None:
            return dict(self._report)
        manager_counts = defaultdict(int)
        for record in self.rows: manager_counts[self.manager(record)[0]] += 1
        self._report = dict(records=len(self.rows), file_name=self.filename, imported_at=self.imported_at,
                    duplicate_emails=sum(len(v) > 1 for v in self.indexes['Mail'].values()),
                    missing_identifiers=sum(not r['DistinguishedName'] and not r['SamAccountName'] for r in self.rows),
                    duplicate_identifiers=dict(usernames=sum(len(v)>1 for v in self.indexes['SamAccountName'].values()),
                                               distinguished_names=sum(len(v)>1 for v in self.indexes['DistinguishedName'].values())),
                    missing_emails=sum(not r['Mail'] for r in self.rows), managers=dict(manager_counts),
                    validation='Valid UTF-8 semicolon CSV; all required headers present')
        return dict(self._report)


def snapshot_path(identity):
    from config import config_dir
    if not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid directory snapshot reference.')
    return config_dir() / 'employee-directory' / f'{identity}.json'


def persist_directory(directory):
    """Stage a content-addressed private snapshot before committing its settings pointer."""
    from config import ensure_content_file
    payload = json.dumps(dict(version=1, records=directory.rows, file_name=directory.filename,
                              imported_at=directory.imported_at, csv_digest=directory.digest),
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(payload) > 128 * 1024 * 1024:
        raise ValueError('Directory snapshot exceeds its storage limit.')
    identity = hashlib.sha256(payload).hexdigest()
    target = snapshot_path(identity)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ensure_content_file(target, payload, identity, 128 * 1024 * 1024)
    return identity


def read_snapshot(identity):
    with snapshot_path(identity).open('rb') as stream:
        raw = stream.read(128 * 1024 * 1024 + 1)
    if len(raw) > 128 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError('Directory snapshot failed its integrity check.')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported directory snapshot.')
    rows = data.get('records')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100_000:
        raise ValueError('Invalid directory snapshot records.')
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {*HEADERS, 'id'} or row['id'] != str(i):
            raise ValueError('Invalid directory snapshot fields.')
        if any(not isinstance(v, str) or len(v) > 4096 or '\x00' in v for v in row.values()):
            raise ValueError('Invalid directory snapshot values.')
    if not isinstance(data.get('file_name'), str) or len(data['file_name']) > 512 or not re.fullmatch(r'[a-f0-9]{64}', data.get('csv_digest', '')):
        raise ValueError('Invalid directory snapshot metadata.')
    datetime.fromisoformat(data['imported_at'])
    directory = Directory(rows, data['file_name'], data['csv_digest'])
    directory.imported_at = data['imported_at']
    return directory


def discard_snapshot(identity):
    if identity:
        snapshot_path(identity).unlink(missing_ok=True)


class DirectoryStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.generation = 0
        self.directory = None
        self.path = ''
        self.attempted_path = None
        self.error = None
        self.import_error = None

    def get(self, path, snapshot_id=None):
        # Slow filesystem I/O never holds the publication lock. Concurrent requests
        # use the last valid snapshot; an in-flight read cannot undo clear/import.
        with self.lock:
            reference = ('snapshot', snapshot_id) if snapshot_id else path
            if not reference or self.attempted_path == reference:
                return self.directory if reference else None
            self.attempted_path = reference
            self.generation += 1
            generation = self.generation
        try:
            candidate = read_snapshot(snapshot_id) if snapshot_id else parse_directory(path)
            error = None
        except (OSError, ValueError, KeyError, TypeError):
            candidate = None
            error = 'Directory data could not be restored. Re-import a readable CSV in Data Sources; SAP lookup is unaffected.'
        with self.lock:
            if generation == self.generation:
                if candidate is not None:
                    self.directory, self.path = candidate, path
                self.error = error
            return self.directory

    def clear(self):
        with self.lock:
            self.generation += 1
            self.directory = None
            self.path = ''
            self.attempted_path = None
            self.error = None
            self.import_error = None


store = DirectoryStore()
