"""
Template context processors for the score app.
"""
from django.conf import settings as django_settings

from .models import SchoolSetting


def tier_info(request):
    """Add tier/plan info to template context (e.g. for nav or feature flags)."""
    tier_name = getattr(django_settings, "TIER_NAME", None)
    display = (tier_name or "basic").title()
    return {
        "tier_name": tier_name,
        "tier_display": display,
    }


def available_features(request):
    """Return available features based on subscription tier."""
    tier_name = getattr(django_settings, "TIER_NAME", "basic")
    
    # Define features for each tier
    features = {
        "basic": {
            "class_setup": True,
            "marks_entry": True,
            "reports": True,
            "attendance": False,
            "routine": False,
            "cbt_exams": False,
            "billing_payment": True,
            "staff_matters": False,
            "register": False,
        },
        "pro": {
            "class_setup": True,
            "marks_entry": True,
            "reports": True,
            "attendance": False,
            "routine": True,
            "cbt_exams": True,
            "billing_payment": True,
            "staff_matters": False,
            "register": False,
        },
        "premium": {
            "class_setup": True,
            "marks_entry": True,
            "reports": True,
            "attendance": True,
            "routine": True,
            "cbt_exams": True,
            "billing_payment": True,
            "staff_matters": True,
            "register": True,
        },
    }
    
    return {"available_features": features.get(tier_name, features["basic"])}


def school_setting(request):
    """Add school's SchoolSetting to context when request.school is set (admin/teacher)."""
    school = getattr(request, "school", None)
    if school is None:
        return {}
    setting = SchoolSetting.objects.filter(school=school).first()
    return {"setting": setting}
