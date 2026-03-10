"""Orrbit production entry point for gunicorn."""

from orrbit import create_app

app = create_app()
