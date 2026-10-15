import os
import sys
from pathlib import Path
from urllib.parse import unquote

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

from dotenv import load_dotenv

load_dotenv(Path.home() / '.config/transcriber-aau/ondemand.env', override=False)
os.environ.setdefault('PROD', 'True')
os.environ.setdefault('DEBUG', 'False')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django-project.settings')

from django.core.wsgi import get_wsgi_application

django_application = get_wsgi_application()


def application(environ, start_response):
	environ['PATH_INFO'] = unquote(environ.get('PATH_INFO', ''), encoding='latin-1')
	return django_application(environ, start_response)