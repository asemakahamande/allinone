# settings/pro.py
from .base import *
import os

# 1. Identity of this tier
TIER_NAME = 'pro'
PIN_PRICE_PER_STUDENT = 500

# 2. Domain Security
# This ensures this specific database only works on your Pro URL
ALLOWED_HOSTS = ['pro.duediligence.com', 'www.pro.duediligence.com', '127.0.0.1', 'localhost']

# 3. Enable DEBUG for development
DEBUG = True

# 4. Database for Pro (SQLite for local dev)
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'db_pro.sqlite3',
}

# 5. (Optional) Separate Media Folder for Pro uploads
MEDIA_ROOT = BASE_DIR / 'media_pro'