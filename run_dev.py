#!/usr/bin/env python3
"""Orrbit development server."""

import os
import sys
from pathlib import Path

# Auto-activate venv if running outside it
_venv = Path(__file__).resolve().parent / '.venv'
_venv_python = _venv / 'bin' / 'python3'
if _venv_python.exists() and sys.prefix == sys.base_prefix:
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)

os.environ['FLASK_DEBUG'] = '1'

from orrbit import create_app

app = create_app()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
    )
