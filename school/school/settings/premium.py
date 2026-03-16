# settings/premium.py
from .base import *
import os

# 1. Identity of this tier
TIER_NAME = 'premium'
PIN_PRICE_PER_STUDENT = 1000

# 2. Domain Security
# Only allow connections from your $1000 domain
ALLOWED_HOSTS = ['premium.duediligence.com', 'www.premium.duediligence.com', '127.0.0.1', 'localhost']

# 3. Enable DEBUG for development
DEBUG = True

# 4. Database for Premium (SQLite for local dev)
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': BASE_DIR / 'db_premium.sqlite3',
}

# 5. (Optional) Separate Media Folder for Premium uploads
MEDIA_ROOT = BASE_DIR / 'media_premium'