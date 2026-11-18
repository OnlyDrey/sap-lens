"""Location of a SAP Lens 1 backend for the reference tools that regenerate v1 comparison fixtures. SAP Lens 1 is archived outside this
repository, so these tools are historical: the committed fixtures are what the .NET tests read, and nothing in a build or test runs them.
To regenerate a fixture, point SAP_LENS_V1_BACKEND at the backend folder of a SAP Lens 1 checkout, for example a worktree of commit 604f21e:
    git worktree add ../sap-lens-v1 604f21e && export SAP_LENS_V1_BACKEND=$PWD/../sap-lens-v1/backend"""
import os
import sys


def v1_backend() -> str:
    path = os.environ.get('SAP_LENS_V1_BACKEND', '')
    if not path or not os.path.isfile(os.path.join(path, 'main.py')):
        sys.exit('SAP_LENS_V1_BACKEND must name the backend folder of a SAP Lens 1 checkout (see tools/v1_location.py).')
    return path
