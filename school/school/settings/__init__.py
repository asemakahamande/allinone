# Default: use basic tier when DJANGO_SETTINGS_MODULE is "settings".
# For the three plans, set DJANGO_PLAN or use:
#   settings.basic   -> Basic plan (e.g. duediligence1.com)
#   settings.pro     -> Pro plan (e.g. duediligence2.com)
#   settings.premium -> Premium plan (e.g. duediligence3.com)
from .basic import *
