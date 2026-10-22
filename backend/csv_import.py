"""Streaming mapped CSV import with explicit relationship/assignment provenance."""
from analysis_errors import AnalysisValidationError
import csv
import hashlib
from pathlib import Path
from config_models import FIELDS, ImportProfile

MAX_BYTES = 128 * 1024 * 1024
MAX_ROWS = 1_000_000


def normalized(value):
    return ''.join(c for c in value.casefold() if c.isalnum())


class CsvImport:
    fields = FIELDS
    required = 'AGR_NAME'
    identifier_fields = ['AGR_NAME','CHILD_AGR','PARENT_AGR','Effective_Role']

    def __init__(self, path: Path, profile: ImportProfile):
        if not path.is_absolute() or path.suffix.lower() != '.csv' or '://' in str(path):
            raise AnalysisValidationError('Choose an absolute filesystem CSV path.')
        self.path, self.profile = path, profile
        self.headers = []
        self.mapping = {}
        self.warnings = []
        self.samples = []
        self.parsed_rows = self.duplicate_rows = self.blank_rows = 0
        self.unique_records = 0

    def inspect_header(self):
        if self.path.stat().st_size > MAX_BYTES: raise AnalysisValidationError('CSV exceeds its size limit.')
        with self.path.open('rb') as stream: bom = stream.read(3)
        encoding = self.profile.encoding
        if encoding == 'auto':
            if bom.startswith((b'\xff\xfe',b'\xfe\xff')): encoding = 'utf-16'
            else:
                with self.path.open('rb') as probe: sample_bytes = probe.read(65536)
                import codecs
                try: codecs.getincrementaldecoder('utf-8-sig')().decode(sample_bytes, final=False); encoding = 'utf-8-sig'
                except UnicodeDecodeError: encoding = 'cp1252'
        with self.path.open(encoding=encoding,newline='') as stream:
            sample = stream.read(65536)
        delimiter = self.profile.delimiter
        if delimiter == 'auto':
            try: delimiter = csv.Sniffer().sniff(sample,delimiters=',;\t|').delimiter
            except csv.Error: delimiter = ','
        import io
        headers = next(csv.reader(io.StringIO(sample),delimiter=delimiter,strict=True),[])
        keys = [normalized(h) for h in headers]
        issues = []
        if len(set(keys)) != len(keys) or any(not h.strip() for h in headers):
            issues.append('Duplicate, ambiguous or empty headers must be corrected before importing.')
        proposed = {field:headers[keys.index(normalized(field))] for field in self.fields if keys.count(normalized(field)) == 1}
        if self.required not in proposed and self.profile.mapping.get(self.required) not in headers:
            issues.append(f'Required {self.required} was not detected. Choose its column manually.')
        return dict(detected_columns=headers,delimiter=delimiter,encoding=encoding,proposed_mapping=proposed,issues=issues)

    def records(self):
        if self.path.stat().st_size > MAX_BYTES: raise AnalysisValidationError('CSV exceeds the 128 MiB safety limit.')
        with self.path.open('rb') as raw: bom = raw.read(3)
        encoding = self.profile.encoding
        if encoding == 'auto':
            if bom.startswith((b'\xff\xfe',b'\xfe\xff')): encoding = 'utf-16'
            else:
                with self.path.open('rb') as probe: sample_bytes = probe.read(65536)
                import codecs
                try: codecs.getincrementaldecoder('utf-8-sig')().decode(sample_bytes, final=False); encoding = 'utf-8-sig'
                except UnicodeDecodeError: encoding = 'cp1252'
        with self.path.open(encoding=encoding, newline='') as stream:
            sample = stream.read(65536)
            stream.seek(0)
            delimiter = self.profile.delimiter
            if delimiter == 'auto':
                try: delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
                except csv.Error: delimiter = ','
            reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
            self.headers = reader.fieldnames or []
            keys = [normalized(h) for h in self.headers]
            if len(set(keys)) != len(keys) or any(not h.strip() for h in self.headers):
                raise AnalysisValidationError('CSV headers contain duplicate, ambiguous or empty column names.')
            detected = dict(zip(keys, self.headers))
            self.mapping = {field:self.profile.mapping.get(field, detected.get(normalized(field))) for field in self.fields}
            for field, source in self.profile.mapping.items():
                if source not in self.headers: raise AnalysisValidationError('A mapped source column is missing.')
            if not self.mapping[self.required]: raise AnalysisValidationError(f'The required {self.required} field is not mapped.')
            self.warnings = [f'Optional field {field} is not mapped.' for field,source in self.mapping.items() if not source]
            used = set(self.mapping.values())
            if any(h not in used for h in self.headers): self.warnings.append('Unmapped extra columns are not used; map any relationship/assignment fields before importing.')
            seen = set()
            for raw in reader:
                self.parsed_rows += 1
                if self.parsed_rows > MAX_ROWS: raise AnalysisValidationError('CSV exceeds the one-million-record safety limit.')
                if None in raw or any(value is None for value in raw.values()):
                    raise AnalysisValidationError('CSV row width does not match its header; no data was applied.')
                row = {field:(raw.get(source,'').strip() if source else '') for field,source in self.mapping.items()}
                if not any(row.values()): self.blank_rows += 1; continue
                if not row[self.required]: raise AnalysisValidationError(f'A nonempty record has no {self.required}; no data was applied.')
                if any(len(value) > 4096 for value in row.values()): raise AnalysisValidationError('A CSV field exceeds its length limit.')
                if any(len(row[f]) > 512 for f in self.identifier_fields):
                    raise AnalysisValidationError('A role identifier is too long.')
                digest = hashlib.blake2b(repr(tuple(row.items())).encode(), digest_size=16).digest()
                if digest in seen: self.duplicate_rows += 1; continue
                seen.add(digest)
                self.unique_records += 1
                if len(self.samples) < 5: self.samples.append(row.copy())
                yield row
            if self.duplicate_rows: self.warnings.append(f'{self.duplicate_rows} identical duplicate records were deduplicated.')
            if self.blank_rows: self.warnings.append(f'{self.blank_rows} empty records were ignored.')

    def report(self):
        return dict(file_name=self.path.name, import_profile=self.profile.id, import_version=self.profile.version,
                    detected_columns=self.headers, resolved_mapping=self.mapping, parsed_rows=self.parsed_rows,
                    unique_records=self.unique_records, duplicate_rows=self.duplicate_rows,
                    warnings=self.warnings, errors=[], samples=self.samples)
