"""
Template context processors for the score app.
"""
from django.conf import settings as django_settings
from .models import SchoolSetting


def tier_info(request):
    """Add tier/plan info to template context (e.g. for nav or feature flags)."""
    # Read from request (set by TierDetectionMiddleware) or fall back to settings
    tier_name = getattr(request, 'tier_name', None) or getattr(django_settings, 'TIER_NAME', 'basic')
    display = (tier_name or 'basic').title()
    return {
        'tier_name': tier_name,
        'tier_display': display,
    }


def available_features(request):
    """Return available features based on subscription tier."""
    # Read from request (set by TierDetectionMiddleware) or fall back to settings
    tier_name = getattr(request, 'tier_name', None) or getattr(django_settings, 'TIER_NAME', 'basic')

    features = {
        'basic': {
            'class_setup': True,
            'marks_entry': True,
            'reports': True,
            'attendance': False,
            'routine': False,
            'cbt_exams': False,
            'billing_payment': True,
            'staff_matters': False,
            'register': False,
            'ai_features': False,
        },
        'pro': {
            'class_setup': True,
            'marks_entry': True,
            'reports': True,
            'attendance': False,
            'routine': True,
            'cbt_exams': True,
            'billing_payment': True,
            'staff_matters': False,
            'register': False,
            'ai_features': True,
        },
        'premium': {
            'class_setup': True,
            'marks_entry': True,
            'reports': True,
            'attendance': True,
            'routine': True,
            'cbt_exams': True,
            'billing_payment': True,
            'staff_matters': True,
            'register': True,
            'ai_features': True,
        },
    }

    return {'available_features': features.get(tier_name, features['basic'])}


def school_setting(request):
    """Add school's SchoolSetting to context when request.school is set (admin/teacher)."""
    school = getattr(request, 'school', None)
    if school is None:
        return {}
    setting = SchoolSetting.objects.filter(school=school).first()
    return {'setting': setting}