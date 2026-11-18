"""Vercel entry point. Vercel runs the WSGI object named `app` as a serverless function."""
import os
import sys

# Make the project root importable (config/, apps/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
