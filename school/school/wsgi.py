import os
from django.core.wsgi import get_wsgi_application

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school.settings.base')
application = get_wsgi_application()