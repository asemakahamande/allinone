# score/decorators.py
"""
Decorators for school authentication and authorization
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from .models import School


def school_required(view_func):
    """
    Decorator to ensure user is logged in as a school
    
    Usage:
        @school_required
        def my_view(request):
            school = request.school  # Available here
            # ... rest of code
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        school_id = request.session.get("school_id")
        
        if not school_id:
            messages.error(request, "Please log in to access this page.")
            return redirect("login")
        
        try:
            # Attach school to request for easy access in views
            school = School.objects.get(id=school_id)
            
            # Enforce tier match
            current_tier = getattr(request, 'tier_name', 'basic')
            if school.tier_name != current_tier:
                request.session.flush()
                messages.error(request, f"This account is registered on the {school.tier_name.title()} plan. Please log in from the correct portal.")
                return redirect("login")
                
            request.school = school
        except School.DoesNotExist:
            request.session.flush()
            messages.error(request, "Invalid session. Please log in again.")
            return redirect("login")
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def get_school_from_session(request):
    """
    Helper function to safely get school from session
    
    Returns: 
        tuple: (school_object, error_response)
        If error_response is not None, view should return it immediately
    
    Usage:
        school, error = get_school_from_session(request)
        if error:
            return error
        # ... continue with school object
    """
    school_id = request.session.get("school_id")
    
    if not school_id:
        messages.error(request, "Please log in to continue.")
        return None, redirect("login")
    
    try:
        school = School.objects.get(id=school_id)
        
        # Enforce tier match
        current_tier = getattr(request, 'tier_name', 'basic')
        if school.tier_name != current_tier:
            request.session.flush()
            messages.error(request, f"This account is registered on the {school.tier_name.title()} plan. Please log in from the correct portal.")
            return None, redirect("login")
            
        return school, None
    except School.DoesNotExist:
        request.session.flush()
        messages.error(request, "Invalid session. Please log in again.")
        return None, redirect("login")


def get_school_or_redirect(request):
    """
    Simple helper that returns school or redirects to login
    
    Usage:
        def my_view(request):
            school = get_school_or_redirect(request)
            if not isinstance(school, School):
                return school  # It's a redirect response
            # ... continue with school object
    """
    school_id = request.session.get("school_id")
    
    if not school_id:
        messages.error(request, "Please log in to continue.")
        return redirect("login")
    
    try:
        school = School.objects.get(id=school_id)
        
        # Enforce tier match
        current_tier = getattr(request, 'tier_name', 'basic')
        if school.tier_name != current_tier:
            request.session.flush()
            messages.error(request, f"This account is registered on the {school.tier_name.title()} plan. Please log in from the correct portal.")
            return redirect("login")
            
        return school
    except School.DoesNotExist:
        request.session.flush()
        messages.error(request, "Invalid session. Please log in again.")
        return redirect("login")