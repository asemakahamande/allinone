# settings/basic.py
from .base import *
import os

# 1. Identity of this tier
TIER_NAME = 'basic'
PIN_PRICE_PER_STUDENT = 200

# 2. Domain Security
ALLOWED_HOSTS = ['basic.duediligence.com', 'www.basic.duediligence.com', '127.0.0.1', 'localhost', os.getenv('RENDER_EXTERNAL_URL', '')]

# 3. Enable DEBUG for development (set to False in production)
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# 4. Database for Basic (PostgreSQL for production)
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.getenv('DB_NAME'),
    'USER': os.getenv('DB_USER'),
    'PASSWORD': os.getenv('DB_PASSWORD'),
    'HOST': os.getenv('DB_HOST'),
    'PORT': os.getenv('DB_PORT'),
}

# Production overrides
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True