# settings/basic.py
from .base import *
import os

# 1. Identity of this tier
TIER_NAME = 'basic'
PIN_PRICE_PER_STUDENT = 200

# 2. Domain Security
ALLOWED_HOSTS = ['basic.duediligence.com', 'www.basic.duediligence.com', '127.0.0.1', 'localhost']

# 3. Enable DEBUG for development
DEBUG = True

# 4. Database for Basic (SQLite for local dev)
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'db_basic.sqlite3',
}