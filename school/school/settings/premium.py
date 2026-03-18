from .base import *
import os

TIER_NAME = 'premium'
PIN_PRICE_PER_STUDENT = 1000

DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

RENDER_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME', '')
ALLOWED_HOSTS = [
    'premium.duediligence.com',
    'www.premium.duediligence.com',
    '127.0.0.1',
    'localhost',
]
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)

# ✅ Same database as basic and pro
DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.getenv('DB_NAME'),
    'USER': os.getenv('DB_USER'),
    'PASSWORD': os.getenv('DB_PASSWORD'),
    'HOST': os.getenv('DB_HOST'),
    'PORT': os.getenv('DB_PORT', '5432'),
}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True