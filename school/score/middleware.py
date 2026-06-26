# score/middleware.py
"""
School Authentication Middleware
Ensures that all requests (except public pages) have a valid school session
"""

from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve
from django.conf import settings
from .models import School


def _session_cookie_name_for_user_type(user_type):
    """Return the session cookie name to use for this user type (teacher/student get isolated cookies)."""
    base = getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid')
    if user_type == 'teacher':
        return f'{base}_teacher'
    if user_type == 'student':
        return f'{base}_student'
    return base


class SessionCookieInjectMiddleware:
    """
    Runs BEFORE SessionMiddleware. Injects the role-specific session cookie into
    request.COOKIES so SessionMiddleware loads the correct session for this path.
    - /student/* -> use schoolsessionid_student
    - All other paths -> use schoolsessionid_teacher (or default schoolsessionid)
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.session_cookie_name = getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid')

    def __call__(self, request):
        path = request.path
        student_cookie = request.COOKIES.get(f'{self.session_cookie_name}_student')
        teacher_cookie = request.COOKIES.get(f'{self.session_cookie_name}_teacher')
        default_cookie = request.COOKIES.get(self.session_cookie_name)
        if path.startswith('/admin/'):
            session_key = default_cookie
        elif path.startswith('/student/'):
            session_key = student_cookie or default_cookie
        else:
            session_key = teacher_cookie or default_cookie
        if session_key is not None:
            request.COOKIES[self.session_cookie_name] = session_key
        return self.get_response(request)


class SessionCookiePathMiddleware:
    """
    Runs AFTER SessionMiddleware. Rewrites the session Set-Cookie to use the
    role-specific name (schoolsessionid_teacher / schoolsessionid_student) so
    each tab keeps its own session and CSRF stays valid.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.session_cookie_name = getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid')

    def __call__(self, request):
        response = self.get_response(request)
        if self.session_cookie_name not in response.cookies:
            return response
        user_type = request.session.get('user_type')
        role_cookie_name = _session_cookie_name_for_user_type(user_type)
        if role_cookie_name == self.session_cookie_name:
            return response
        morsel = response.cookies[self.session_cookie_name]
        response.cookies[role_cookie_name] = morsel
        del response.cookies[self.session_cookie_name]
        return response


class SchoolAuthenticationMiddleware:
    """
    Middleware to ensure school authentication and attach school to request
    """
    def __init__(self, get_response):
        self.get_response = get_response
        
        # URL names that don't require school authentication
        self.exempt_url_names = [
            'login',
            'register',
            'forgot_password',
            'reset_password',
            'index',  # homepage
            'get_states',  # registration form API
            'get_local_governments',  # registration form API

            # ✅ TeachersMatters URLs
            'teacher_register',
            'teacher_list',
            'hire_teacher',
            'unhire_teacher',
            'employer_register',
            'employer_dashboard',
            'logn',
            'logt',
            'password_reset',
            'password_reset_done',
            'password_reset_confirm',
            'password_reset_complete',
        ]
        
        # URL paths that don't require authentication
        self.exempt_url_paths = [
            '/static/',
            '/media/',
            '/admin/',
            '/api/get-states/',  # registration form only
            '/api/get-local-governments/',  # registration form only
            '/teacher/',   # All teachers URLs
            '/employer/',  # All employer URLs
        ]

    def __call__(self, request):
        # Get the current URL path
        path = request.path
        
        # ✅ Skip authentication for exempt paths
        if any(path.startswith(exempt_path) for exempt_path in self.exempt_url_paths):
            return self.get_response(request)
        
        # ✅ Skip authentication for exempt URL names
        try:
            url_name = resolve(path).url_name
            if url_name in self.exempt_url_names:
                return self.get_response(request)
        except:
            pass
        
        # ✅ Get school from session
        school_id = request.session.get("school_id")
        
        if not school_id:
            messages.error(request, "Please log in to continue.")
            return redirect("login")
        
        # ✅ Attach school to request
        try:
            request.school = School.objects.get(id=school_id)
        except School.DoesNotExist:
            request.session.flush()
            messages.error(request, "Invalid session. Please log in again.")
            return redirect("login")

        return self.get_response(request)





class TierDetectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        if host.startswith('www.'):
            host = host[4:]

        tier_config = getattr(settings, 'TIER_CONFIG', {})
        
        # Fall back to settings values in local development if host isn't in TIER_CONFIG
        default_tier = getattr(settings, 'TIER_NAME', 'basic')
        default_price = getattr(settings, 'PIN_PRICE_PER_STUDENT', 200)

        config = tier_config.get(host, {
            'TIER_NAME': default_tier,
            'PIN_PRICE_PER_STUDENT': default_price,
        })

        request.tier_name = config['TIER_NAME']
        request.pin_price = config['PIN_PRICE_PER_STUDENT']

        return self.get_response(request)