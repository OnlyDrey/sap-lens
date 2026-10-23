"""Optional local employee enrichment. No name guessing, recursive traversal or data copies."""
import csv
import hashlib
import io
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HEADERS = 'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'.split(';')
MAX_BYTES = 50 * 1024 * 1024


def normalized(value):
    return value.strip().casefold()


def parse_directory(path):
    source = Path(path)
    if not source.is_absolute():
        raise ValueError('Choose an absolute Employee Directory CSV path.')
    with source.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
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
    except (UnicodeError, csv.Error):
        raise ValueError('Employee Directory must be valid UTF-8 semicolon CSV with correctly quoted fields.') from None
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
                    missing_emails=sum(not r['Mail'] for r in self.rows), managers=dict(manager_counts),
                    validation='Valid UTF-8 semicolon CSV; all required headers present')
        return dict(self._report)


class DirectoryStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.generation = 0
        self.directory = None
        self.path = ''
        self.attempted_path = None
        self.error = None
        self.import_error = None

    def get(self, path):
        # Slow filesystem I/O never holds the publication lock. Concurrent requests
        # use the last valid snapshot; an in-flight read cannot undo clear/import.
        with self.lock:
            if not path or self.attempted_path == path:
                return self.directory if path else None
            self.attempted_path = path
            self.generation += 1
            generation = self.generation
        try:
            candidate = parse_directory(path)
            error = None
        except (OSError, ValueError):
            candidate = None
            error = 'Directory could not be read or validated. Previous valid data is retained; review Data Sources.'
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
