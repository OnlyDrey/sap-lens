"""The one authoritative description of where generated build output lives. Standard library only.

Everything distributable goes under the repository-root ``dist/``; temporary work, caches and logs stay in ``backend/build``,
``frontend/dist`` and ``build/``. Docker images stay in Docker (only exportable archives land in ``dist``).
"""
from .runner import ROOT

ARTIFACT_ROOT = ROOT / 'dist'

#: name -> (relative path, what it holds). Changing a path here must be matched by the workflow upload contracts (scripts/check-workflows.py).
OUTPUTS = {
    'local': ('dist/local', 'portable Windows desktop builds, run records and receipts (build-local.ps1)'),
    'deployment': ('dist/deployment', 'verified deployment archives and checksums: Windows desktop/service, Linux native, Docker image archive (CI and local)'),
    'server': ('dist/server', 'Windows service distributions (build-server-windows.ps1)'),
    'publication': ('dist/publication', 'same-run artifacts collected for the guarded release job; never written by local builds'),
}
#: Per-version output of build-deployments.py (dist/<version>-<commit12>/) and the cleanup coordination file.
VERSIONED_PATTERN = 'dist/<version>-<commit12>/'
CLEAN_LOCK = ARTIFACT_ROOT / '.sap-lens-clean.lock'

#: Generated, safe-to-delete locations the clean command may remove (never user data, sources or databases).
GENERATED = ('backend/build', 'backend/dist', 'frontend/dist', *(path for path, _ in OUTPUTS.values() if path != 'dist/publication'))


def is_inside_artifact_root(path):
    try:
        return path.resolve().is_relative_to(ARTIFACT_ROOT.resolve())
    except OSError:
        return False
