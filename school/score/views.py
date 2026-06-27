import uuid
import base64
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse, Http404
from django.template.loader import render_to_string
from datetime import datetime
from io import BytesIO
import os
import logging
import requests
from requests.exceptions import SSLError, RequestException, ConnectionError, Timeout
from django.conf import settings
from .models import ClassGroup, Student, Subject, Score, SchoolSetting, AffectiveTrait, PsychomotorSkill, AcademicSession, Term, Payment, Pin
from .helpers import ScoreHelper
from .decorators import school_required

# Add these to your views.py (BEFORE your existing views)

import random
import string
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# TLS 1.2 adapter to avoid SSLV3_ALERT_BAD_RECORD_MAC on some Windows/Python + Paystack setups
class _PaystackTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        import ssl
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)


def _paystack_session():
    session = requests.Session()
    session.mount("https://", _PaystackTLSAdapter())
    return session


def _paystack_get(url, headers, timeout=30):
    """Call Paystack GET; try TLS adapter first, then plain requests on SSL error."""
    try:
        return _paystack_session().get(url, headers=headers, timeout=timeout)
    except SSLError:
        return requests.get(url, headers=headers, timeout=timeout)


def _paystack_post(url, headers, json_data, timeout=30):
    """Call Paystack POST; try TLS adapter first, then plain requests on SSL error."""
    try:
        return _paystack_session().post(url, json=json_data, headers=headers, timeout=timeout)
    except SSLError:
        return requests.post(url, json=json_data, headers=headers, timeout=timeout)


def get_user_context(request):
    """
    Determine if user is admin or teacher and return appropriate context
    Returns: {
        'is_admin': bool,
        'is_teacher': bool,
        'school': School object,
        'class_group': ClassGroup object (if teacher),
        'classes': QuerySet of classes (filtered based on user type)
    }
    """
    user_type = request.session.get('user_type')
    
    if user_type == 'admin':
        # Admin access - use existing @school_required decorator pattern
        if hasattr(request, 'school'):
            school = request.school
        else:
            return None
            
        return {
            'is_admin': True,
            'is_teacher': False,
            'school': school,
            'class_group': None,
            'classes': ClassGroup.objects.filter(school=school).order_by('name')
        }
    
    elif user_type == 'teacher':
        # Teacher access - get from Django auth
        if not request.user.is_authenticated:
            return None
            
        try:
            class_group = ClassGroup.objects.select_related('school').get(teacher_user=request.user)
            return {
                'is_admin': False,
                'is_teacher': True,
                'school': class_group.school,
                'class_group': class_group,
                'classes': ClassGroup.objects.filter(id=class_group.id)
            }
        except ClassGroup.DoesNotExist:
            return None

    # Fallback: no/invalid user_type in session — if user is a class teacher, treat as teacher
    if request.user.is_authenticated:
        try:
            class_group = ClassGroup.objects.select_related('school').get(teacher_user=request.user)
            request.session['user_type'] = 'teacher'
            request.session['school_id'] = class_group.school_id
            request.session['class_id'] = class_group.id
            return {
                'is_admin': False,
                'is_teacher': True,
                'school': class_group.school,
                'class_group': class_group,
                'classes': ClassGroup.objects.filter(id=class_group.id)
            }
        except ClassGroup.DoesNotExist:
            pass

    return None


def get_teacher_dashboard_context(class_group):
    """Build context dict required by teacher_dashboard.html (for in-dashboard pages)."""
    from django.utils import timezone
    from .models import Attendance, SchoolSetting
    school = class_group.school
    setting = SchoolSetting.objects.filter(school=school).first()
    students = Student.objects.filter(class_group=class_group, is_active=True).order_by("surname", "first_name")
    subjects = Subject.objects.filter(class_group=class_group).order_by("name")
    total_students = students.count()
    male_students = students.filter(gender="Male").count()
    female_students = students.filter(gender="Female").count()
    current_session = AcademicSession.objects.first()
    current_term = Term.objects.first()
    today = timezone.now().date()
    present_today = Attendance.objects.filter(
        student__class_group=class_group, date=today, status="present"
    ).count()
    return {
        "school": school,
        "setting": setting,
        "class_group": class_group,
        "students": students,
        "subjects": subjects,
        "total_students": total_students,
        "male_students": male_students,
        "female_students": female_students,
        "present_today": present_today,
        "current_session": current_session,
        "current_term": current_term,
    }



# ==========================================
# HELPER FUNCTIONS - Credential Generation
# ==========================================

def generate_random_password(length=8):
    """Generate a secure random password"""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def create_teacher_account(class_group):
    """
    Auto-create teacher login account when class is created
    Returns: (user, password) or (None, None) if already exists
    """
    if not class_group.class_teacher or class_group.teacher_user:
        return class_group.teacher_user, class_group.generated_password
    
    # Generate unique username
    school_prefix = class_group.school.name[:3].upper().replace(' ', '')
    teacher_name = class_group.class_teacher.lower().replace(' ', '_')
    username = f"{school_prefix}_{teacher_name}"
    
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{school_prefix}_{teacher_name}{counter}"
        counter += 1
    
    # Generate password
    password = generate_random_password(10)
    
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=class_group.class_teacher.split()[0] if class_group.class_teacher else '',
            last_name=' '.join(class_group.class_teacher.split()[1:]) if len(class_group.class_teacher.split()) > 1 else ''
        )
        
        class_group.teacher_user = user
        class_group.generated_password = password
        class_group.save()
    
    return user, password


def create_student_account(student):
    """
    Auto-create student login account
    Returns: (user, password) or (None, None) if already exists
    """
    if student.user:
        return student.user, student.generated_password
    
    # Use admission number (exam_no) exactly as the username
    if student.exam_no:
        username = student.exam_no
    else:
        # Fallback if somehow there's no admission number
        school_prefix = student.school.name[:2].lower().replace(' ', '')
        base = f"{student.surname}{student.first_name}".lower().replace(' ', '')
        username = f"{school_prefix}_{base}"
    
    counter = 1
    original_username = username
    while User.objects.filter(username=username).exists():
        username = f"{original_username}{counter}"
        counter += 1
    
    # Generate password
    password = generate_random_password(10)
    
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=student.first_name,
            last_name=student.surname
        )
        
        student.user = user
        student.generated_password = password
        student.save()
    
    return user, password


# ==========================================
# UNIFIED LOGIN VIEW
# ==========================================

def unified_login(request):
    """
    Single login page for Admin, Teacher, and Student
    """
    # If Django sent us here because user tried to access /admin/, send them to Django admin login
    # (Django admin requires a staff/superuser User, not the app's School session.)
    next_url = request.GET.get("next", "")
    if next_url.startswith("/admin/"):
        from django.urls import reverse
        admin_login = reverse("admin:login")
        return redirect(f"{admin_login}?next={next_url}")

    if request.method == "POST":
        login_type = request.POST.get("login_type")
        identifier = request.POST.get("identifier")
        password = request.POST.get("password")
        
        # ADMIN LOGIN
        if login_type == "admin":
            try:
                school = School.objects.get(email=identifier)
                if school.check_password(password):
                    request.session["school_id"] = school.id
                    request.session["user_type"] = "admin"
                    messages.success(request, f"Welcome {school.admin_name}!")
                    return redirect("dashboard")
                else:
                    messages.error(request, "Invalid password")
            except School.DoesNotExist:
                messages.error(request, "School account not found")
        
        # TEACHER LOGIN
        elif login_type == "teacher":
            user = authenticate(request, username=identifier, password=password)
            if user is not None:
                try:
                    class_group = ClassGroup.objects.select_related('school').get(teacher_user=user)
                    auth_login(request, user)
                    request.session['school_id'] = class_group.school.id
                    request.session['user_type'] = 'teacher'
                    request.session['class_id'] = class_group.id
                    
                    messages.success(request, f"Welcome {class_group.class_teacher}!")
                    return redirect("teacher_dashboard")
                except ClassGroup.DoesNotExist:
                    messages.error(request, "This account is not assigned as a class teacher")
            else:
                messages.error(request, "Invalid username or password")
        
        # STUDENT LOGIN
        elif login_type == "student":
            user = authenticate(request, username=identifier, password=password)
            if user is not None:
                try:
                    student = Student.objects.select_related('school', 'class_group').get(user=user)
                    auth_login(request, user)
                    request.session['school_id'] = student.school.id
                    request.session['user_type'] = 'student'
                    request.session['student_id'] = student.id
                    
                    messages.success(request, f"Welcome {student.full_name}!")
                    return redirect("student_dashboard")
                except Student.DoesNotExist:
                    messages.error(request, "Student account not found")
            else:
                messages.error(request, "Invalid username or password")
    
    return render(request, "score/unified_login.html")


def unified_logout(request):
    """Logout for all user types"""
    user_type = request.session.get('user_type')
    
    if user_type in ['teacher', 'student']:
        auth_logout(request)
    
    request.session.flush()
    messages.success(request, "You have been logged out successfully")
    return redirect("unified_login")


# ==========================================
# TEACHER DASHBOARD VIEWS
# ==========================================

@login_required
def teacher_dashboard(request):
    """Teacher dashboard - shows only their class data"""
    
    if request.session.get('user_type') != 'teacher':
        messages.error(request, "Access denied. Teachers only.")
        return redirect("unified_login")
    
    try:
        class_group = ClassGroup.objects.select_related('school').get(teacher_user=request.user)
        school = class_group.school
    except ClassGroup.DoesNotExist:
        messages.error(request, "You are not assigned to any class.")
        auth_logout(request)
        return redirect("unified_login")
    
    # Get current term and session
    current_session = AcademicSession.objects.first()
    current_term = Term.objects.first()
    
    # Get students in this class
    students = Student.objects.filter(
        class_group=class_group,
        is_active=True
    ).order_by("surname", "first_name")
    
    # Get subjects for this class
    subjects = Subject.objects.filter(class_group=class_group).order_by("name")
    
    # Statistics
    total_students = students.count()
    male_students = students.filter(gender="Male").count()
    female_students = students.filter(gender="Female").count()
    
    # Today's attendance
    from django.utils import timezone
    today = timezone.now().date()
    present_today = Attendance.objects.filter(
        student__class_group=class_group,
        date=today,
        status="present"
    ).count()
    
    from .models import SchoolSetting
    setting = SchoolSetting.objects.filter(school=school).first()
    context = {
        'school': school,
        'setting': setting,
        'class_group': class_group,
        'students': students,
        'subjects': subjects,
        'total_students': total_students,
        'male_students': male_students,
        'female_students': female_students,
        'present_today': present_today,
        'current_session': current_session,
        'current_term': current_term,
    }
    
    return render(request, "score/teacher_dashboard.html", context)


@login_required
def teacher_students(request):
    """View all students in teacher's class"""
    
    if request.session.get('user_type') != 'teacher':
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    try:
        class_group = ClassGroup.objects.get(teacher_user=request.user)
    except ClassGroup.DoesNotExist:
        messages.error(request, "You are not assigned to any class.")
        return redirect("unified_login")
    
    students = Student.objects.filter(
        class_group=class_group
    ).order_by("surname", "first_name")

    from .models import SchoolSetting
    setting = SchoolSetting.objects.filter(school=class_group.school).first()

    context = {
        'school': class_group.school,
        'setting': setting,
        'class_group': class_group,
        'students': students,
    }

    return render(request, "score/teacher_students.html", context)

@login_required
def student_dashboard(request):
    """Student dashboard - shows only their data"""
    
    if request.session.get('user_type') != 'student':
        messages.error(request, "Access denied. Students only.")
        return redirect("unified_login")
    
    try:
        student = Student.objects.select_related(
            'school', 'class_group', 'session'
        ).get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        auth_logout(request)
        return redirect("unified_login")
    
    # Get current term
    current_term = Term.objects.first()
    
    # Get scores
    scores = Score.objects.filter(
        student=student,
        term=current_term
    ).select_related('subject').order_by('subject__name')
    
    # Calculate statistics
    total_score = sum(s.total for s in scores if s.total)
    num_subjects = scores.count()
    average_score = round(total_score / num_subjects, 2) if num_subjects else 0
    
    # Get attendance
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status="present").count()
    attendance_percentage = round((present_count / total_attendance * 100), 2) if total_attendance else 0
    
    from .models import SchoolSetting
    setting = SchoolSetting.objects.filter(school=student.school).first()
    context = {
        'student': student,
        'setting': setting,
        'scores': scores,
        'total_score': total_score,
        'average_score': average_score,
        'num_subjects': num_subjects,
        'attendance_percentage': attendance_percentage,
        'present_count': present_count,
        'total_attendance': total_attendance,
        'current_term': current_term,
    }
    
    return render(request, "score/student_dashboard.html", context)



@login_required
def student_scores(request):
    """View all scores for student"""
    
    if request.session.get('user_type') != 'student':
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    try:
        student = Student.objects.get(user=request.user)
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect("unified_login")
    
    # Get filters
    term_name = request.GET.get('term')
    
    term = Term.objects.filter(name=term_name).first() if term_name else Term.objects.first()
    
    scores = Score.objects.filter(
        student=student,
        term=term
    ).select_related('subject').order_by('subject__name')
    
    # Calculate totals
    total_score = sum(s.total for s in scores if s.total)
    num_subjects = scores.count()
    average_score = round(total_score / num_subjects, 2) if num_subjects else 0
    
    terms = Term.objects.all()
    
    context = {
        'student': student,
        'scores': scores,
        'total_score': total_score,
        'average_score': average_score,
        'terms': terms,
        'selected_term': term,
    }
    
    return render(request, "score/student_scores.html", context)


# ==========================================
# VIEW CREDENTIALS (Admin Only)
# ==========================================

from django.shortcuts import render, get_object_or_404
from .models import Student, ClassGroup
from .decorators import school_required

@school_required
def view_all_credentials(request):
    school = request.school

    # --- Get user context ---
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")

    is_admin = context['is_admin']

    if is_admin:
        # Admin sees all teachers and students
        teachers = ClassGroup.objects.filter(
            school=school,
            teacher_user__isnull=False
        ).select_related('teacher_user').order_by('name')

        students = Student.objects.filter(
            school=school,
            user__isnull=False
        ).select_related('user', 'class_group').order_by('class_group__name', 'surname', 'first_name')

    else:
        # Teacher sees only students in their class
        class_group = context['class_group']
        teachers = []  # Non-admins don’t see teachers
        students = Student.objects.filter(
            school=school,
            class_group=class_group,
            user__isnull=False
        ).select_related('user', 'class_group').order_by('surname', 'first_name')

    if not is_admin:
        teacher_ctx = get_teacher_dashboard_context(context['class_group'])
        teacher_ctx.update({
            'teachers': teachers,
            'students': students,
            'is_admin': is_admin,
            'class_group': context.get('class_group'),
        })
        return render(request, "score/view_all_credentials_teacher.html", teacher_ctx)

    return render(request, "score/view_all_credentials.html", {
        'school': school,
        'teachers': teachers,
        'students': students,
        'is_admin': is_admin,
        'class_group': context.get('class_group'),
    })

GRADING_SCHEMES = {
    'scheme_1': {
        'ca1': (0, 20),
        'ca2': (0, 20),
        'ca3': (0, 20),
        'exam': (0, 40),
        'max_total': 100  
    },
    'scheme_2': {
        'ca1': (0, 20),
        'ca2': (0, 10),
        'ca3': (0, 10),
        'exam': (0, 60),
        'max_total': 100  
    },
    'scheme_3': {
        'ca1': (0, 20),
        'ca2': (0, 15),
        'ca3': (0, 15),
        'exam': (0, 50),
        'max_total': 100  
    },
    'scheme_4': {
        'ca1': (0, 10),
        'ca2': (0, 10),
        'ca3': (0, 10),
        'exam': (0, 70),
        'max_total': 100 
    },
}


from datetime import datetime
from django.contrib import messages
from django.shortcuts import render, redirect
from .models import SchoolSetting

from django.shortcuts import render, redirect
from django.contrib import messages
from datetime import datetime
from .models import SchoolSetting

@school_required
def settings_view(request):
    school = request.school

    current_year = datetime.now().year
    year_range = range(current_year - 1, current_year + 10) # Adjusted range

    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    terms = ["First Term", "Second Term", "Third Term"]

    # Get the existing settings or create a fresh one for the school
    setting, created = SchoolSetting.objects.get_or_create(
        school=school,
        defaults={
            "exam_year": current_year,
            "exam_month": "January",
            "school_open": 0,
            "name": school.name,
            "email": school.email,
            "phone": school.phone,
            "address": school.address,
            "logo": school.logo,
        }
    )

    # Automatically pull info from the school registration if it's still the default dummy data
    needs_save = False
    if setting.name == "Your School Name":
        setting.name = school.name
        setting.email = school.email
        setting.phone = school.phone
        setting.address = school.address
        needs_save = True
        
    # Also sync logo if the settings has no logo but the school registration does
    if not setting.logo and school.logo:
        setting.logo = school.logo
        needs_save = True
        
    if needs_save:
        setting.save()

    if request.method == "POST":
        # 1. Update text fields from the form 'name' attributes
        setting.name = request.POST.get("name")
        setting.email = request.POST.get("email")
        setting.phone = request.POST.get("phone")
        setting.motto = request.POST.get("motto")
        setting.address = request.POST.get("address")
        
        # Academic info
        setting.session = request.POST.get("session")
        setting.term = request.POST.get("term")
        setting.exam_year = request.POST.get("exam_year")
        setting.exam_month = request.POST.get("exam_month")
        setting.school_open = request.POST.get("school_open")
        
        # Dates (Handle empty strings if not provided)
        term_closes = request.POST.get("term_closes_on")
        next_term = request.POST.get("next_term_begins")
        
        setting.term_closes_on = term_closes if term_closes else None
        setting.next_term_begins = next_term if next_term else None

        # 2. Handle Image Files (Crucial for Cloudinary)
        if "logo" in request.FILES:
            setting.logo = request.FILES["logo"]

        if "stamp_sign" in request.FILES:
            setting.stamp_sign = request.FILES["stamp_sign"]

        # 3. Save triggers the Cloudinary Upload
        setting.save()
        
        messages.success(request, "School settings saved successfully.")
        return redirect("settings_view")

    return render(request, "score/setting.html", {
        "year_range": year_range,
        "months": months,
        "terms": terms,
        "setting": setting,
        "school": school,
    })








# ---------------- INDEX / ENTER SCORES ---------------- #
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from .models import ClassGroup, Student, Subject, Score, SchoolSetting, AffectiveTrait, PsychomotorSkill

def index(request):
  return render(request, 'score/index.html')


from django.shortcuts import render, redirect
from django.contrib import messages
# from .models import School

def login(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        try:
            school = School.objects.get(email=email)
            if school.check_password(password):  # ✅ use model method
                current_tier = getattr(request, 'tier_name', 'basic')
                if school.tier_name != current_tier:
                    messages.error(request, f"This account is registered on the {school.tier_name.title()} plan. Please log in from the correct portal.")
                    return render(request, "score/login.html")
                
                # Save the school ID in session
                request.session["school_id"] = school.id
                messages.success(request, f"Welcome {school.name}!")
                return redirect("dashboard")
            else:
                messages.error(request, "Invalid password")
        except School.DoesNotExist:
            messages.error(request, "No account found with that email")

    return render(request, "score/login.html")

# views.py
from django.shortcuts import redirect
from django.contrib import messages

def logout(request):
    request.session.flush()  # Clears all session data
    messages.success(request, "You have been logged out.")
    return redirect("login")  # Redirect to login page




from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .forms import SchoolRegistrationForm
from .location_data import COUNTRY_DATA


@csrf_exempt
def get_states(request):
    """Return states/provinces for a given country (JSON). Used by registration form."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    country = request.GET.get("country", "").strip()
    if not country:
        return JsonResponse({"states": []})
    if country in COUNTRY_DATA:
        states = sorted(COUNTRY_DATA[country].keys())
        return JsonResponse({"states": states})
    return JsonResponse({"states": []})


@csrf_exempt
def get_local_governments(request):
    """Return local governments for a given country and state (JSON). Used by registration form."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    country = request.GET.get("country", "").strip()
    state = request.GET.get("state", "").strip()
    if not country or not state:
        return JsonResponse({"local_governments": []})
    if country in COUNTRY_DATA and state in COUNTRY_DATA[country]:
        lgs = sorted(COUNTRY_DATA[country][state])
        return JsonResponse({"local_governments": lgs})
    return JsonResponse({"local_governments": []})


def register(request):
    from django.contrib import messages
    from django.db import IntegrityError

    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST, request.FILES)
        # Set state/local_government choices from POST so validation accepts JS-selected values (e.g. FCT, Municipal Area Council)
        country = (request.POST.get("country") or "").strip()
        state = (request.POST.get("state") or "").strip()
        if country in COUNTRY_DATA:
            form.fields["state"].choices = [("", "Select State/Province")] + [
                (s, s) for s in sorted(COUNTRY_DATA[country].keys())
            ]
            if state in COUNTRY_DATA[country]:
                form.fields["local_government"].choices = [("", "Select Local Government")] + [
                    (lg, lg) for lg in sorted(COUNTRY_DATA[country][state])
                ]
        if form.is_valid():
            try:
                school = form.save(commit=False)
                school.tier_name = getattr(request, 'tier_name', 'basic')
                school.save()
            except IntegrityError:
                # Duplicate email or registration number
                messages.error(
                    request,
                    "This email or registration number is already registered. Please use a different one or log in.",
                )
                return render(request, "score/register.html", {"form": form})
            except Exception as e:
                messages.error(
                    request,
                    "Registration could not be completed. Please check your details and try again.",
                )
                return render(request, "score/register.html", {"form": form})

            # Notify site admin of new registration
            try:
                from django.conf import settings
                from django.core.mail import send_mail
                admin_email = getattr(settings, "ADMIN_EMAIL", None)
                if admin_email:
                    subject = "New school registration"
                    message = (
                        f"A new school has registered.\n\n"
                        f"Email: {school.email}\n"
                        f"Admin's full name: {school.admin_name}\n"
                        f"Admin's phone: {school.admin_phone}\n"
                    )
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [admin_email],
                        fail_silently=True,
                    )
            except Exception:
                pass  # don't block registration if email fails
            messages.success(request, "Registration successful. You can now log in.")
            return redirect("login")  # go to login after successful registration
    else:
        form = SchoolRegistrationForm()
    return render(request, "score/register.html", {"form": form})



from django.shortcuts import render, redirect
from .models import School


# score/views.py

from django.shortcuts import render, redirect
from django.db.models import Count
from .models import School, Student, ClassGroup, Subject, SchoolSetting

# ✅ AFTER (with decorator):
@school_required
def dashboard(request):
    school = request.school  # Automatically available!
    setting = SchoolSetting.objects.filter(school=school).first()

    # All classes in this school
    classes = ClassGroup.objects.filter(school=school).select_related('next_class')
    subjects = Subject.objects.filter(
        class_group__school=school
    ).select_related('class_group')
    
    # Filter students by selected class
    selected_class_id = request.GET.get("class")
    if selected_class_id:
        students = Student.objects.filter(
            class_group_id=selected_class_id
        ).select_related('class_group')
    else:
        students = Student.objects.filter(
            class_group__school=school
        ).select_related('class_group')

    # Summary stats (school-wide)
    total_classes = classes.count()
    total_students = Student.objects.filter(class_group__school=school).count()
    male_students = Student.objects.filter(class_group__school=school, gender="Male").count()
    female_students = Student.objects.filter(class_group__school=school, gender="Female").count()
    total_subjects = Subject.objects.filter(class_group__school=school).count()

    # For pie charts: students per class, subjects per class
    students_per_class = list(
        ClassGroup.objects.filter(school=school).annotate(
            student_count=Count("students")
        ).values("name", "student_count").order_by("name")
    )
    subjects_per_class = list(
        ClassGroup.objects.filter(school=school).annotate(
            subject_count=Count("subjects")
        ).values("name", "subject_count").order_by("name")
    )
    
    return render(request, "score/dashboard.html", {
        "school": school,
        "setting": setting,
        "students": students,
        "classes": classes,
        "subjects": subjects,
        "selected_class_id": int(selected_class_id) if selected_class_id else None,
        "total_classes": total_classes,
        "total_students": total_students,
        "male_students": male_students,
        "female_students": female_students,
        "total_subjects": total_subjects,
        "students_per_class": students_per_class,
        "subjects_per_class": subjects_per_class,
    })



from django.core.mail import send_mail
from django.utils import timezone
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email")
        try:
            school = School.objects.get(email=email)
            # generate token
            token = str(uuid.uuid4())
            school.reset_token = token
            school.reset_token_created = timezone.now()
            school.save()

            reset_link = request.build_absolute_uri(f"/reset-password/{token}/")

            # send email
            send_mail(
                "Password Reset Request",
                f"Click the link to reset your password: {reset_link}",
                settings.DEFAULT_FROM_EMAIL,
                [email],
            )

        except School.DoesNotExist:
            # Do not reveal whether the email exists
            pass  

        # ✅ Always show confirmation page
        return render(request, "score/forgot_password_done.html")

    return render(request, "score/forgot_password.html")




from django.shortcuts import get_object_or_404

def reset_password(request, token):
    school = get_object_or_404(School, reset_token=token)
    if request.method == "POST":
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
        else:
            school.set_password(password)
            school.reset_token = None
            school.save()
            messages.success(request, "Password reset successful. Please login.")
            return redirect("login")

    return render(request, "score/reset_password.html", {"token": token})


from django.shortcuts import render, redirect
from .forms import ClassGroupForm, SubjectForm, StudentForm
from django.shortcuts import render, redirect
from django.db import IntegrityError
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import IntegrityError
from .models import Student, ClassGroup, AcademicSession
from .forms import StudentForm
from .decorators import school_required


@school_required
def add_student(request):
    school = request.school

    # --- Get user context ---
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")

    is_admin = context['is_admin']

    # Admin sees all classes, teacher sees only their class
    if is_admin:
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        selected_class = None
        selected_class_id = request.POST.get('class_group') or request.GET.get('class_group')
        if selected_class_id:
            selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)
    else:
        classes = [context['class_group']]  # Only their class
        selected_class = context['class_group']

    if request.method == "POST":
        form = StudentForm(request.POST, school=school)

        if form.is_valid():
            student = form.save(commit=False)
            student.school = school

            # --- Ensure class_group is set correctly ---
            if is_admin and selected_class:
                student.class_group = selected_class
            elif not is_admin:
                student.class_group = selected_class

            try:
                student.save()

                # AUTO-CREATE STUDENT ACCOUNT
                try:
                    user, password = create_student_account(student)
                    messages.success(
                        request,
                        f"✅ Student {student.full_name} added successfully!\n\n"
                        f"📋 Student Login Credentials:\n"
                        f"👤 Username: {user.username}\n"
                        f"🔑 Password: {password}\n"
                        f"📚 Class: {student.class_group.name}\n"
                        f"🏫 School: {school.name}\n\n"
                        f"⚠️ Please provide these to the student/parent!"
                    )
                except Exception as e:
                    messages.warning(request, f"Student added but failed to create login account: {str(e)}")

                if request.POST.get("action") == "save_add":
                    return redirect("add_student")
                if is_admin:
                    return redirect("dashboard")
                return redirect("teacher_dashboard")
            except IntegrityError:
                form.add_error(None, "This student already exists in your school.")
    else:
        form = StudentForm(school=school)

    if not is_admin:
        teacher_ctx = get_teacher_dashboard_context(context["class_group"])
        teacher_ctx.update({
            "form": form,
            "is_admin": is_admin,
            "classes": classes,
            "selected_class": selected_class,
        })
        return render(request, "score/add_student_teacher.html", teacher_ctx)

    return render(request, "score/add_student.html", {
        "form": form,
        "is_admin": is_admin,
        "classes": classes,
        "selected_class": selected_class,
        "school": school,
    })



@school_required
def update_student(request, student_id):
    school = request.school
    
    # ✅ CRITICAL: Verify student belongs to this school
    student = get_object_or_404(Student, id=student_id, school=school)
    
    if request.method == "POST":
        form = StudentForm(request.POST, instance=student, school=school)
        if form.is_valid():
            form.save()
            messages.success(request, "Student updated successfully!")
            return redirect("class_view")
    else:
        form = StudentForm(instance=student, school=school)
    
    return render(request, "score/update_student.html", {"form": form, "school": school})


@school_required
def delete_student(request, student_id):
    school = request.school
    
    # ✅ CRITICAL: Verify student belongs to this school
    student = get_object_or_404(Student, id=student_id, school=school)
    
    if request.method == "POST":
        student.delete()
        messages.success(request, "Student deleted successfully!")
        return redirect("class_view")
    
    return render(request, "score/confirm_delete.html", {
        "object": student, 
        "type": "Student",
        "school": school,
    })


@school_required
def toggle_student_status(request, student_id):
    school = request.school
    
    # ✅ CRITICAL: Verify student belongs to this school
    student = get_object_or_404(Student, id=student_id, school=school)
    
    active_param = request.GET.get("active")
    
    if active_param is not None:
        student.is_active = active_param.lower() == "true"
    else:
        student.is_active = not student.is_active
    
    student.save()
    
    return JsonResponse({
        "status": "ok",
        "is_active": student.is_active
    })


# views.py

from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from .models import ClassGroup, Student, Subject, School
from .forms import StudentForm, SubjectForm

# Class view with students + subjects
from django.shortcuts import render, redirect, get_object_or_404
from .models import ClassGroup, Student, Subject, School


# @school_required
# def add_class(request):
#     school = request.school
    
#     if request.method == "POST":
#         form = ClassGroupForm(request.POST)
#         if form.is_valid():
#             name = form.cleaned_data["name"]
#             teacher_name = form.cleaned_data.get("class_teacher")
            
#             if ClassGroup.objects.filter(school=school, name=name).exists():
#                 messages.error(request, f"Class '{name}' already exists for {school.name}.")
#                 return render(request, "score/add_class.html", {"form": form})
            
#             class_group = form.save(commit=False)
#             class_group.school = school
#             class_group.save()
            
#             # ✅ AUTO-CREATE TEACHER ACCOUNT
#             if teacher_name:
#                 try:
#                     user, password = create_teacher_account(class_group)
#                     if user:
#                         messages.success(
#                             request,
#                             f"✅ Class '{name}' added successfully!\n\n"
#                             f"📋 Teacher Login Credentials:\n"
#                             f"👤 Username: {user.username}\n"
#                             f"🔑 Password: {password}\n"
#                             f"🏫 School: {school.name}\n\n"
#                             f"⚠️ Please save these credentials and provide to the teacher!"
#                         )
#                     else:
#                         messages.success(request, f"Class '{name}' added successfully!")
#                 except Exception as e:
#                     messages.warning(request, f"Class added but failed to create teacher account: {str(e)}")
#             else:
#                 messages.success(request, f"Class '{name}' added successfully!")
            
#             scoring_system = form.cleaned_data["scoring_system"]
#             action = request.POST.get("action")
            
#             if action == "save_add":
#                 return redirect("add_class")
#             elif scoring_system == "custom":
#                 return redirect("setup_custom_grading", class_id=class_group.id)
#             else:
#                 return redirect("dashboard")
#     else:
#         form = ClassGroupForm()
    
#     return render(request, "score/add_class.html", {"form": form})



# from django.shortcuts import render, get_object_or_404
# from .models import ClassGroup, Student, Subject
# from .decorators import school_required
# # from .utils import get_user_context

# @school_required
# def class_view(request):
#     school = request.school

#     # --- Get user context ---
#     context = get_user_context(request)
#     if not context:
#         messages.error(request, "Access denied.")
#         return redirect("unified_login")
    
#     is_admin = context['is_admin']

#     # Admin sees all classes, teacher sees only their class
#     if is_admin:
#         classes = ClassGroup.objects.filter(school=school).order_by("name")
#         selected_class_id = request.GET.get("class_id")
#         if selected_class_id:
#             selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)
#         else:
#             selected_class = None
#     else:
#         classes = [context['class_group']]  # Teacher sees only their class
#         selected_class = context['class_group']
#         selected_class_id = selected_class.id

#     students = []
#     subjects = []

#     if selected_class:
#         students = Student.objects.filter(
#             class_group=selected_class
#         ).order_by("surname", "first_name", "middle_name")
        
#         subjects = Subject.objects.filter(
#             class_group=selected_class
#         ).order_by("name")

#     return render(request, "score/class_view.html", {
#         "classes": classes,
#         "selected_class": selected_class,
#         "selected_class_id": selected_class_id,
#         "students": students,
#         "subjects": subjects,
#         "is_admin": is_admin,
#         "is_teacher": not is_admin,
#     })


@school_required
def class_view(request):
    """
    Single comprehensive view for all class management
    Handles: viewing classes, subjects, students with role-based access
    """
    school = request.school
    
    # Get user context for role-based access
    user_ctx = get_user_context(request)
    if not user_ctx:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = user_ctx['is_admin']
    is_teacher = user_ctx['is_teacher']
    classes = user_ctx['classes']
    
    # Get selected class
    class_id = request.GET.get('class_id')
    selected_class = None
    subjects = []
    students = []
    
    if is_teacher and user_ctx['class_group']:
        # Teacher: auto-select their class
        selected_class = user_ctx['class_group']
    elif class_id:
        # Admin: use selected class from dropdown
        if is_admin:
            selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
        elif is_teacher:
            # Verify teacher has access to this class
            if int(class_id) == user_ctx['class_group'].id:
                selected_class = user_ctx['class_group']
    
    # Get subjects and students for selected class
    if selected_class:
        subjects = Subject.objects.filter(class_group=selected_class).order_by('name')
        students = Student.objects.filter(class_group=selected_class).order_by('surname', 'first_name')
    
    context = {
        'is_admin': is_admin,
        'is_teacher': is_teacher,
        'classes': classes,
        'selected_class': selected_class,
        'subjects': subjects,
        'students': students,
        'school': school,
    }

    if not is_admin and user_ctx.get('class_group'):
        teacher_ctx = get_teacher_dashboard_context(user_ctx['class_group'])
        teacher_ctx.update(context)
        return render(request, "score/class_view_teacher.html", teacher_ctx)

    return render(request, "score/class_view.html", context)


@school_required
def add_class(request):
    """Add a new class"""
    school = request.school
    
    if request.method == "POST":
        form = ClassGroupForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            teacher_name = form.cleaned_data.get("class_teacher")
            
            if ClassGroup.objects.filter(school=school, name=name).exists():
                messages.error(request, f"Class '{name}' already exists for {school.name}.")
                return render(request, "score/add_class.html", {"form": form, "school": school})
            
            class_group = form.save(commit=False)
            class_group.school = school
            class_group.save()
            
            # AUTO-CREATE TEACHER ACCOUNT
            if teacher_name:
                try:
                    user, password = create_teacher_account(class_group)
                    if user:
                        messages.success(
                            request,
                            f"✅ Class '{name}' added successfully!\n\n"
                            f"📋 Teacher Login Credentials:\n"
                            f"👤 Username: {user.username}\n"
                            f"🔑 Password: {password}\n"
                            f"🏫 School: {school.name}\n\n"
                            f"⚠️ Please save these credentials and provide to the teacher!"
                        )
                    else:
                        messages.success(request, f"Class '{name}' added successfully!")
                except Exception as e:
                    messages.warning(request, f"Class added but failed to create teacher account: {str(e)}")
            else:
                messages.success(request, f"Class '{name}' added successfully!")
            
            scoring_system = form.cleaned_data["scoring_system"]
            action = request.POST.get("action")
            
            if action == "save_add":
                return redirect("add_class")
            elif scoring_system == "custom":
                return redirect("setup_custom_grading", class_id=class_group.id)
            else:
                # Redirect to class_view with new class selected
                return redirect(f"{reverse('class_view')}?class_id={class_group.id}")
    else:
        form = ClassGroupForm()
    
    return render(request, "score/add_class.html", {"form": form, "school": school})


@school_required
def edit_class(request, class_id):
    """Edit/update an existing class"""
    school = request.school
    class_group = get_object_or_404(ClassGroup, id=class_id, school=school)
    
    if request.method == "POST":
        form = ClassGroupForm(request.POST, instance=class_group)
        if form.is_valid():
            name = form.cleaned_data["name"]
            
            # Check if name exists for another class
            if ClassGroup.objects.filter(
                school=school, 
                name=name
            ).exclude(id=class_id).exists():
                messages.error(request, f"Class '{name}' already exists for {school.name}.")
                return render(request, "score/add_class.html", {
                    "form": form, 
                    "class_group": class_group,
                    "is_edit": True,
                    "school": school,
                })
            
            # Save the updated class
            updated_class = form.save(commit=False)
            updated_class.school = school
            updated_class.save()
            
            # Handle teacher account creation if teacher_name is newly added
            teacher_name = form.cleaned_data.get("class_teacher")
            if teacher_name and not class_group.teacher_user:
                try:
                    user, password = create_teacher_account(updated_class)
                    if user:
                        messages.success(
                            request,
                            f"✅ Class '{name}' updated successfully!\n\n"
                            f"📋 New Teacher Login Credentials:\n"
                            f"👤 Username: {user.username}\n"
                            f"🔑 Password: {password}\n"
                            f"🏫 School: {school.name}\n\n"
                            f"⚠️ Please save these credentials and provide to the teacher!"
                        )
                    else:
                        messages.success(request, f"Class '{name}' updated successfully!")
                except Exception as e:
                    messages.warning(request, f"Class updated but failed to create teacher account: {str(e)}")
            else:
                messages.success(request, f"Class '{name}' updated successfully!")
            
            # If custom grading was selected, send user to set it up
            scoring_system = form.cleaned_data.get("scoring_system")
            if scoring_system == "custom":
                messages.info(request, "Class updated. Set up your custom grading system below, then save.")
                return redirect("setup_custom_grading", class_id=updated_class.id)
            # Otherwise redirect back to class_view with the updated class selected
            return redirect(f"{reverse('class_view')}?class_id={class_group.id}")
    else:
        form = ClassGroupForm(instance=class_group)
    
    context = {
        "form": form,
        "class_group": class_group,
        "is_edit": True,
        "school": school,
    }
    return render(request, "score/add_class.html", context)


@school_required
def delete_class(request, class_id):
    """Delete a class with confirmation"""
    school = request.school
    class_group = get_object_or_404(ClassGroup, id=class_id, school=school)
    
    if request.method == "POST":
        class_name = class_group.name
        
        # Get counts for confirmation message
        student_count = Student.objects.filter(class_group=class_group).count()
        subject_count = Subject.objects.filter(class_group=class_group).count()
        
        # Delete the class (CASCADE will handle related objects)
        class_group.delete()
        
        messages.success(
            request,
            f"Class '{class_name}' has been deleted successfully. "
            f"({student_count} students and {subject_count} subjects were also removed)"
        )
        return redirect("class_view")
    
    # GET request - show confirmation page
    students = Student.objects.filter(class_group=class_group)
    subjects = Subject.objects.filter(class_group=class_group)
    scores = Score.objects.filter(student__class_group=class_group)
    
    context = {
        "class_group": class_group,
        "student_count": students.count(),
        "subject_count": subjects.count(),
        "score_count": scores.count(),
        "students": students[:10],  # Show first 10 students as preview
        "school": school,
    }
    return render(request, "score/delete_class.html", context)



from django.db import IntegrityError
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from .models import Subject, School, ClassGroup
from .forms import SubjectForm

from django.db import IntegrityError
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from .models import Subject, ClassGroup, School
from .forms import SubjectForm

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import IntegrityError
from .models import ClassGroup, Subject
from .forms import SubjectForm
# from .utils import get_user_context
from .decorators import school_required

@school_required
def add_subject(request):
    school = request.school
    
    # --- Get user context ---
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    
    # Admin sees all classes, teacher sees only their class
    if is_admin:
        classes = ClassGroup.objects.filter(school=school).order_by("name")
        selected_class = None
        selected_class_id = request.GET.get("class_group")
        if selected_class_id:
            selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)
    else:
        classes = [context['class_group']]
        selected_class = context['class_group']
    
    if request.method == "POST":
        form = SubjectForm(request.POST)
        
        # Get class from POST or fallback to teacher's class
        class_id = request.POST.get("class_group") or (selected_class.id if selected_class else None)
        
        if class_id:
            selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
            
            if form.is_valid():
                subject = form.save(commit=False)
                subject.class_group = selected_class
                
                try:
                    subject.save()
                    messages.success(request, f"✅ Subject '{subject.name}' added successfully to {selected_class.name}!")
                    
                    if request.POST.get("action") == "save_add":
                        return redirect("add_subject")
                    if is_admin:
                        return redirect("dashboard")
                    return redirect("teacher_dashboard")
                except IntegrityError:
                    form.add_error(None, f"The subject '{subject.name}' already exists in {selected_class.name}.")
        else:
            messages.error(request, "Please select a class.")
    else:
        form = SubjectForm()

    # Teachers: render inside teacher_dashboard layout (same URL, different template)
    if not is_admin:
        teacher_ctx = get_teacher_dashboard_context(context["class_group"])
        teacher_ctx.update({
            "form": form,
            "is_admin": is_admin,
            "classes": classes,
            "selected_class": selected_class,
        })
        return render(request, "score/add_subject_teacher.html", teacher_ctx)

    return render(request, "score/add_subject.html", {
        "form": form,
        "is_admin": is_admin,
        "classes": classes,
        "selected_class": selected_class,
        "school": school,
    })





@school_required
def update_subject(request, subject_id):
    school = request.school
    
    # ✅ CRITICAL: Verify subject's class belongs to this school
    subject = get_object_or_404(Subject, id=subject_id, class_group__school=school)
    
    if request.method == "POST":
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            messages.success(request, "Subject updated successfully!")
            return redirect("class_view")
    else:
        form = SubjectForm(instance=subject)
    
    return render(request, "score/update_subject.html", {"form": form, "school": school})


@school_required
def delete_subject(request, subject_id):
    school = request.school
    
    # ✅ CRITICAL: Verify subject's class belongs to this school
    subject = get_object_or_404(Subject, id=subject_id, class_group__school=school)
    
    if request.method == "POST":
        subject.delete()
        messages.success(request, "Subject deleted successfully!")
        return redirect("class_view")
    
    return render(request, "score/confirm_delete.html", {
        "object": subject,
        "type": "Subject",
        "school": school,
    })








from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from .models import Staff, School
from .forms import StaffForm



@school_required
def staff_list(request):
    school = request.school
    staff_members = Staff.objects.filter(school=school)
    
    return render(request, "score/staff_list.html", {"staff_members": staff_members, "school": school})


@school_required
def register_staff(request):
    school = request.school
    
    if request.method == "POST":
        form = StaffForm(request.POST)
        if form.is_valid():
            staff = form.save(commit=False)
            staff.school = school
            staff.save()
            messages.success(request, "Staff registered successfully!")
            return redirect("staff_list")
    else:
        form = StaffForm()
    
    return render(request, "score/register_staff.html", {"form": form, "school": school})


@school_required
def update_staff(request, staff_id):
    school = request.school
    
    # ✅ CRITICAL: Verify staff belongs to this school
    staff = get_object_or_404(Staff, id=staff_id, school=school)
    
    if request.method == "POST":
        form = StaffForm(request.POST, instance=staff)
        if form.is_valid():
            form.save()
            messages.success(request, "Staff updated successfully!")
            return redirect("staff_list")
    else:
        form = StaffForm(instance=staff)
    
    return render(request, "score/register_staff.html", {"form": form, "school": school})


@school_required
def delete_staff(request, staff_id):
    school = request.school
    
    # ✅ CRITICAL: Verify staff belongs to this school
    staff = get_object_or_404(Staff, id=staff_id, school=school)
    staff.delete()
    messages.success(request, "Staff deleted successfully!")
    return redirect("staff_list")






from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from .models import Meeting, School, Staff
from .forms import MeetingForm
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Timetable, School
from .forms import TimetableForm

# List timetable
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Case, When, Value, BooleanField
from .models import Timetable, School

from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import F
from .models import School, Timetable

from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Min
from .models import School, Timetable

from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Min
from .models import School, Timetable


# ==============================================================================
# MEETING VIEWS - COPY AND REPLACE YOUR EXISTING FUNCTIONS
# ==============================================================================

@school_required
def meeting_list(request):
    school = request.school  # ✅ Replaces the 4 lines of manual checking
    
    meetings = Meeting.objects.filter(school=school).order_by("-date")
    return render(request, "score/meeting_list.html", {"meetings": meetings, "school": school})


@school_required
def schedule_meeting(request):
    school = request.school  # ✅ Replaces the manual checking
    
    if request.method == "POST":
        form = MeetingForm(request.POST)
        # Limit staff choices to current school
        form.fields["invited_staff"].queryset = Staff.objects.filter(school=school)

        if form.is_valid():
            meeting = form.save(commit=False)
            meeting.school = school
            meeting.save()
            form.save_m2m()

            # Send email invitations to staff
            for staff in meeting.invited_staff.all():
                if staff.email:  # only send if staff has email
                    send_mail(
                        subject=f"📢 Meeting Invitation: {meeting.title}",
                        message=(
                            f"Dear {staff.surname} {staff.firstname} {staff.middlename},\n\n"
                            f"You are invited to a meeting.\n\n"
                            f"📌 Title: {meeting.title}\n"
                            f"📝 Agenda: {meeting.agenda}\n"
                            f"📅 Date: {meeting.date}\n\n"
                            f"Regards,\n{school.name}"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[staff.email],
                        fail_silently=False,
                    )

            messages.success(request, "Meeting scheduled and email invitations sent.")
            return redirect("meeting_list")
    else:
        form = MeetingForm()
        form.fields["invited_staff"].queryset = Staff.objects.filter(school=school)

    return render(request, "score/schedule_meeting.html", {"form": form, "school": school})


@school_required
def update_meeting(request, meeting_id):
    school = request.school  # ✅ Replaces the manual checking
    
    meeting = get_object_or_404(Meeting, id=meeting_id, school=school)

    if request.method == "POST":
        form = MeetingForm(request.POST, instance=meeting)
        # Limit staff choices to current school
        form.fields["invited_staff"].queryset = Staff.objects.filter(school=school)

        if form.is_valid():
            meeting = form.save(commit=False)
            meeting.school = school
            meeting.save()
            form.save_m2m()

            # Send email invitations to staff
            for staff in meeting.invited_staff.all():
                if staff.email:
                    send_mail(
                        subject=f"📢 Updated Meeting Invitation: {meeting.title}",
                        message=(
                            f"Dear {staff.surname} {staff.firstname} {staff.middlename},\n\n"
                            f"The meeting details have been updated.\n\n"
                            f"📌 Title: {meeting.title}\n"
                            f"📝 Agenda: {meeting.agenda}\n"
                            f"📅 Date: {meeting.date}\n\n"
                            f"Regards,\n{school.name}"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[staff.email],
                        fail_silently=False,
                    )

            messages.success(request, "Meeting updated and email invitations sent.")
            return redirect("meeting_list")
    else:
        form = MeetingForm(instance=meeting)
        form.fields["invited_staff"].queryset = Staff.objects.filter(school=school)

    return render(request, "score/schedule_meeting.html", {"form": form, "update": True, "meeting": meeting, "school": school})



@school_required
def delete_meeting(request, meeting_id):
    school = request.school  # ✅ Replaces the manual checking
    
    meeting = get_object_or_404(Meeting, id=meeting_id, school=school)
    
    if request.method == "POST":
        meeting.delete()
        messages.success(request, "Meeting deleted successfully.")
        return redirect("meeting_list")
    
    return render(request, "score/confirm_delete.html", {"object": meeting, "type": "Meeting", "school": school})



from django.db.models import Min
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Timetable, ClassGroup
from .decorators import school_required

@school_required
def timetable_list(request):
    school = request.school

    context = get_user_context(request)
    if context is None:
        is_admin = getattr(request.user, "is_superuser", False) or getattr(request.user, "is_staff", False)
        selected_class = None
        classes = ClassGroup.objects.filter(school=school).order_by("name")
    else:
        is_admin = context["is_admin"]
        selected_class = context.get("class_group")
        classes = context.get("classes") or ClassGroup.objects.filter(school=school).order_by("name")

    timetables = Timetable.objects.filter(school=school)

    if not is_admin and selected_class:
        timetables = timetables.filter(class_name=selected_class.name)

    class_query = request.GET.get("q", "")
    day_query = request.GET.get("day", "")

    if class_query and is_admin:
        timetables = timetables.filter(class_name__icontains=class_query)

    if day_query:
        timetables = timetables.filter(day=day_query)

    earliest_times = (
        timetables.values("day")
        .annotate(earliest=Min("start_time"))
    )
    earliest_dict = {i["day"]: i["earliest"] for i in earliest_times}
    for t in timetables:
        t.earliest_start = earliest_dict.get(t.day)
    timetables = timetables.order_by("day", "start_time")

    days = Timetable.DAYS_OF_WEEK
    render_ctx = {
        "timetables": timetables,
        "class_query": class_query,
        "day_query": day_query,
        "is_admin": is_admin,
        "selected_class": selected_class,
        "classes": classes,
        "days": days,
        "school": school,
    }

    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/timetable_list_teacher.html", teacher_ctx)

    return render(request, "score/timetable_list.html", render_ctx)



from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import TimetableForm
from .models import ClassGroup
from .decorators import school_required
# from .utils import get_user_context

@school_required
def add_timetable(request):
    school = request.school

    # --- Get user context ---
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']

    # Admin sees all classes, teacher sees only their class
    if is_admin:
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        selected_class = None
    else:
        classes = []  # Not needed for teacher
        selected_class = context['class_group']

    if request.method == "POST":
        form = TimetableForm(request.POST)
        if form.is_valid():
            timetable = form.save(commit=False)
            if not is_admin and selected_class:
                timetable.class_name = selected_class.name
            timetable.school = school
            timetable.save()
            messages.success(request, "Timetable entry added successfully.")
            return redirect("timetable_list")
    else:
        if not is_admin:
            form = TimetableForm(initial={"class_name": selected_class.name if selected_class else ""})
        else:
            form = TimetableForm()

    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update({
            "form": form,
            "is_update": False,
            "is_admin": is_admin,
            "classes": classes,
            "selected_class": selected_class,
        })
        return render(request, "score/add_timetable_teacher.html", teacher_ctx)

    return render(request, "score/add_timetable.html", {
        "form": form,
        "is_update": False,
        "is_admin": is_admin,
        "classes": classes,
        "selected_class": selected_class,
        "school": school,
    })




@school_required
def update_timetable(request, pk):
    school = request.school  # ✅ Replaces the manual checking
    
    timetable = get_object_or_404(Timetable, id=pk, school=school)

    if request.method == "POST":
        form = TimetableForm(request.POST, instance=timetable)
        if form.is_valid():
            form.save()
            messages.success(request, "Timetable entry updated successfully.")
            return redirect("timetable_list")
    else:
        form = TimetableForm(instance=timetable)

    return render(
        request,
        "score/add_timetable.html",
        {
            "form": form,
            "is_update": True,
            "timetable": timetable,
            "school": school,
        },
    )


@school_required
def delete_timetable(request, timetable_id):
    school = request.school  # ✅ Replaces the manual checking
    
    timetable = get_object_or_404(Timetable, id=timetable_id, school=school)
    
    if request.method == "POST":
        timetable.delete()
        messages.success(request, "Timetable entry deleted successfully.")
        return redirect("timetable_list")
    
    return render(request, "score/confirm_deleted_timetable.html", {"object": timetable, "type": "Timetable", "school": school})











from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.timezone import now
from django.utils.dateparse import parse_date
from .models import ClassGroup, Student, Attendance, School


@school_required
def mark_attendance(request):
    """
    Mark attendance - Admins see all classes, Teachers see only their class
    """
    school = request.school
    from django.utils import timezone
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    classes = context['classes']
    
    # --- Get selected class ---
    if is_admin:
        selected_class_id = request.GET.get("class_id")
        if selected_class_id:
            selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)
        else:
            selected_class = None
    else:
        selected_class = context['class_group']
        selected_class_id = selected_class.id
    
    date_str = request.GET.get("date") or str(timezone.now().date())
    students = []
    attendance_dict = {}
    
    if selected_class:
        students = Student.objects.filter(
            class_group=selected_class
        ).order_by("surname", "first_name", "middle_name")
        
        # Load existing attendance
        attendance_records = Attendance.objects.filter(
            student__in=students,
            date=date_str,
            school=school
        )
        attendance_dict = {att.student_id: att.status for att in attendance_records}
        
        if request.method == "POST":
            for student in students:
                status = request.POST.get(f"status_{student.id}")
                if status:
                    Attendance.objects.update_or_create(
                        student=student,
                        date=date_str,
                        school=school,
                        defaults={"status": status},
                    )
            
            messages.success(request, "Attendance saved successfully!")
            return redirect(f"{request.path}?class_id={selected_class_id}&date={date_str}")

    render_ctx = {
        "classes": classes,
        "students": students,
        "selected_class_id": selected_class_id,
        "selected_class": selected_class,
        "date": date_str,
        "attendance_dict": attendance_dict,
        "is_admin": is_admin,
        "is_teacher": not is_admin,
        "school": school,
    }

    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/mark_attendance_teacher.html", teacher_ctx)

    return render(request, "score/mark_attendance.html", render_ctx)




from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import ClassGroup, Student, Attendance
# from .utils import get_user_context
from .decorators import school_required

@school_required
def attendance_report(request):
    school = request.school

    # 🔑 Get user role + class
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")

    is_admin = context["is_admin"]

    # Admin → choose any class
    # Teacher → only their class, auto-selected
    if is_admin:
        classes = ClassGroup.objects.filter(school=school).order_by("name")
        selected_class_id = request.GET.get("class_id")
        selected_class = None

        if selected_class_id:
            selected_class = get_object_or_404(
                ClassGroup, id=selected_class_id, school=school
            )
    else:
        # ✅ Teacher: force their class
        selected_class = context["class_group"]
        classes = [selected_class]

    report = []

    if selected_class:
        students = Student.objects.filter(
            class_group=selected_class
        ).order_by("surname", "first_name", "middle_name")

        for student in students:
            present_count = Attendance.objects.filter(
                student=student,
                status="present",
                school=school
            ).count()

            absent_count = Attendance.objects.filter(
                student=student,
                status="absent",
                school=school
            ).count()

            report.append({
                "student": student,
                "present": present_count,
                "absent": absent_count,
            })

    render_ctx = {
        "classes": classes,
        "selected_class": selected_class,
        "report": report,
        "is_admin": is_admin,
        "school": school,
    }

    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/attendance_report_teacher.html", teacher_ctx)

    return render(request, "score/attendance_report.html", render_ctx)






@school_required
def delete_attendance(request, student_id, date):
    school = request.school

    # ✅ Verify student belongs to this school
    student = get_object_or_404(
        Student, id=student_id, class_group__school=school
    )

    date_obj = parse_date(date)

    attendance = Attendance.objects.filter(
        student=student,
        date=date_obj,
        school=school
    ).first()

    if attendance:
        attendance.delete()
        messages.success(
            request,
            f"Attendance for {student.full_name} on {date} deleted successfully!"
        )
    else:
        messages.warning(
            request,
            f"No attendance record found for {student.full_name} on {date}."
        )

    return redirect(
        f"/attendance/mark/?class_id={student.class_group.id}&date={date}"
    )

from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.contrib import messages
from django.db.models import Q

@school_required
def enterscore(request):
    """
    Score entry view - Admins see all classes, Teachers see only their class
    """
    school = request.school
    user_type = request.session.get('user_type')
    
    # Get user context
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    is_teacher = context['is_teacher']
    
    # --- Get available classes based on user type ---
    classes = context['classes']
    if not classes.exists():
        return render(request, "score/enterscore.html", {
            "classes": [], 
            "subjects": [], 
            "scores": [],
            "scoring_ranges": {}, 
            "scoring_percentages": {},
            "use_custom": False, 
            "custom_components": None,
            "is_admin": is_admin,
            "is_teacher": is_teacher,
            "school": school,
        })
    
    # --- Selected class ---
    if is_admin:
        selected_class_id = request.GET.get("class", classes.first().id)
        selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)
    else:
        # Teacher - auto-select their class
        selected_class = context['class_group']
    
    # --- Get subjects for selected class ---
    subjects = Subject.objects.filter(class_group=selected_class).order_by("name")
    if not subjects.exists():
        render_ctx = {
            "classes": classes,
            "subjects": [],
            "scores": [],
            "selected_class": selected_class,
            "scoring_ranges": {},
            "scoring_percentages": {},
            "use_custom": False,
            "custom_components": None,
            "is_admin": is_admin,
            "is_teacher": is_teacher,
            "school": school,
        }
        if not is_admin and selected_class:
            teacher_ctx = get_teacher_dashboard_context(selected_class)
            teacher_ctx.update(render_ctx)
            return render(request, "score/enterscore_teacher.html", teacher_ctx)
        return render(request, "score/enterscore.html", render_ctx)
    
    # --- Selected subject ---
    requested_subject_id = request.GET.get("subject")
    if requested_subject_id and subjects.filter(id=requested_subject_id).exists():
        selected_subject = subjects.get(id=requested_subject_id)
    else:
        selected_subject = subjects.first()
    
    # --- Term and Session ---
    term_name = request.GET.get("term")
    session_name = request.GET.get("session")
    
    selected_term = (
        Term.objects.filter(name=term_name).first()
        or Term.objects.filter(name="First Term").first()
        or Term.objects.first()
    )
    if not selected_term:
        selected_term, _ = Term.objects.get_or_create(name="First Term")

    selected_session = (
        AcademicSession.objects.filter(name=session_name).first()
        or AcademicSession.objects.filter(name="2025/2026").first()
        or AcademicSession.objects.first()
    )
    if not selected_session:
        selected_session, _ = AcademicSession.objects.get_or_create(name="2025/2026")
    
    # --- Custom grading detection ---
    use_custom = selected_class.scoring_system == "custom"
    custom_components = None
    
    if use_custom:
        custom_system = getattr(selected_class, "custom_scoring_system", None)
        if custom_system and custom_system.components:
            custom_components = custom_system.components
        else:
            messages.warning(
                request,
                "Custom grading system is selected but not yet configured."
            )
    
    # =========================
    # POST: SAVE SCORES
    # =========================
    if request.method == "POST":
        updated = False
        
        # ---------- CUSTOM GRADING ----------
        if use_custom:
            try:
                custom_system = selected_class.custom_scoring_system
                components = custom_system.components
            except Exception:
                messages.error(request, "Custom grading system not configured.")
                return redirect("enterscore")
            
            student_scores = {}
            
            for key, value in request.POST.items():
                if key.startswith("custom_"):
                    try:
                        _, student_id_str, component_slug = key.split("_", 2)
                        student_id = int(student_id_str)
                        
                        # Verify student belongs to this school
                        student = Student.objects.filter(
                            id=student_id,
                            class_group__school=school
                        ).first()
                        if not student:
                            continue
                        
                        component_name = next(
                            (
                                name for name in components.keys()
                                if name.lower().replace(" ", "_") == component_slug
                            ),
                            None
                        )
                        if not component_name:
                            continue
                        
                        val = float(value or 0)
                        max_val = components[component_name]
                        
                        if not (0 <= val <= max_val):
                            messages.error(
                                request,
                                f"{component_name} must be between 0 and {max_val}"
                            )
                            continue
                        
                        student_scores.setdefault(student.id, {})[component_name] = val
                    
                    except Exception:
                        continue
            
            for student_id, custom_data in student_scores.items():
                student = get_object_or_404(
                    Student,
                    id=student_id,
                    class_group__school=school
                )
                
                score, _ = Score.objects.get_or_create(
                    student=student,
                    subject=selected_subject,
                    term=selected_term,
                    session=selected_session,
                    defaults={"custom_scores": custom_data}
                )
                
                score.custom_scores = custom_data
                score.save()
                updated = True
            
            if updated:
                ScoreHelper.update_custom_totals(
                    selected_subject, selected_term, selected_session
                )
                messages.success(request, "Custom scores saved successfully!")
        
        # ---------- PRESET GRADING ----------
        else:
            scheme = GRADING_SCHEMES.get(selected_class.scoring_system)
            if not scheme:
                messages.error(request, "Invalid grading scheme.")
                return redirect("enterscore")
            
            for key, value in request.POST.items():
                if key.startswith("score_"):
                    _, field, score_id = key.split("_")
                    if field not in scheme or field == "max_total":
                        continue
                    
                    try:
                        score = Score.objects.get(
                            id=score_id,
                            student__class_group__school=school
                        )
                        
                        val = float(value or 0)
                        min_val, max_val = scheme[field]
                        
                        if not (min_val <= val <= max_val):
                            messages.error(
                                request,
                                f"{field.upper()} must be between {min_val} and {max_val}"
                            )
                            continue
                        
                        setattr(score, field, int(val))
                        score.save()
                        updated = True
                    
                    except Exception:
                        continue
                
                elif key.startswith("affective_"):
                    _, trait, student_id = key.split("_")
                    AffectiveTrait.objects.update_or_create(
                        student_id=student_id,
                        student__class_group__school=school,
                        term=selected_term,
                        session=selected_session,
                        defaults={trait: value}
                    )
                
                elif key.startswith("psychomotor_"):
                    _, skill, student_id = key.split("_")
                    PsychomotorSkill.objects.update_or_create(
                        student_id=student_id,
                        student__class_group__school=school,
                        term=selected_term,
                        session=selected_session,
                        defaults={skill: value}
                    )
            
            if updated:
                ScoreHelper.update_scores(
                    selected_subject, selected_term, selected_session
                )
                messages.success(request, "Scores updated successfully!")
        
        return redirect(
            f"{reverse('enterscore')}?class={selected_class.id}"
            f"&subject={selected_subject.id}"
            f"&term={selected_term.name}&session={selected_session.name}"
        )
    
    # =========================
    # GET: PREPARE SCORES
    # =========================
    students = Student.objects.filter(
        class_group=selected_class,
        session=selected_session
    ).order_by("surname", "first_name")
    
    scores = []
    for student in students:
        score, _ = Score.objects.get_or_create(
            student=student,
            subject=selected_subject,
            term=selected_term,
            session=selected_session,
            defaults={"ca1": 0, "ca2": 0, "ca3": 0, "exam": 0, "custom_scores": {}}
        )
        score.ordinal_position = (
            ScoreHelper.ordinal(score.position) if score.position else ""
        )
        scores.append(score)
    
    # =========================
    # FIXED SCORING RANGE + PERCENTAGES
    # =========================
    scoring_ranges = (
        GRADING_SCHEMES.get(selected_class.scoring_system, {})
        if not use_custom else {}
    )
    
    # Initialize dynamically, excluding max_total
    scoring_percentages = {
        k: 0 for k in scoring_ranges if k != "max_total"
    }
    
    if scoring_ranges:
        # Sum only tuple values (skip max_total which is int)
        academic_max = sum(
            v[1] for k, v in scoring_ranges.items() if k != "max_total"
        )
        
        if academic_max:
            for k, v in scoring_ranges.items():
                if k == "max_total":
                    continue
                scoring_percentages[k] = round(v[1] / academic_max * 100)

    render_ctx = {
        "classes": classes,
        "subjects": subjects,
        "scores": scores,
        "selected_class": selected_class,
        "selected_subject": selected_subject,
        "term": selected_term.name,
        "session": selected_session.name,
        "terms": Term.objects.values_list("name", flat=True),
        "sessions": AcademicSession.objects.values_list("name", flat=True),
        "use_custom": use_custom,
        "custom_components": custom_components,
        "scoring_ranges": scoring_ranges,
        "scoring_percentages": scoring_percentages,
        "is_admin": is_admin,
        "is_teacher": is_teacher,
        "school": school,
    }
    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/enterscore_teacher.html", teacher_ctx)
    return render(request, "score/enterscore.html", render_ctx)

from django.shortcuts import render, get_object_or_404
from django.db.models import Count
from .models import AffectiveTrait, ClassGroup, Student, Term, AcademicSession, Attendance


@school_required
def affective_view(request):
    """
    Affective traits view - Admins see all classes, Teachers see only their class
    """
    school = request.school
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    classes = context['classes']
    
    terms = Term.objects.all()
    sessions = AcademicSession.objects.all()
    
    # --- Get selected class ---
    class_id = request.GET.get("class_id") or request.POST.get("class_id")
    
    if is_admin:
        if class_id:
            selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
        else:
            selected_class = None
    else:
        selected_class = context['class_group']
        class_id = selected_class.id
    
    # --- Get term and session ---
    term_id = request.GET.get("term") or request.POST.get("term")
    session_id = request.GET.get("session") or request.POST.get("session")
    
    selected_term = get_object_or_404(Term, id=term_id) if term_id else None
    selected_session = get_object_or_404(AcademicSession, id=session_id) if session_id else None
    
    students = []
    traits = [
        "neatness", "leadership", "punctuality", "cooperation",
        "creativity", "relationship", "hardwork", "work_independently"
    ]
    grades = ["A", "B", "C", "D", "E"]
    
    # --- Get students if class, term, and session are selected ---
    if selected_class and selected_term and selected_session:
        students = Student.objects.filter(
            class_group=selected_class,
            session=selected_session
        ).order_by("surname", "first_name", "middle_name")
        
        # Get attendance counts
        from django.db.models import Count
        present_counts = Attendance.objects.filter(
            student__in=students,
            status="present"
        ).values("student_id").annotate(present_count=Count("student_id"))
        
        present_dict = {item["student_id"]: item["present_count"] for item in present_counts}
        
        # Attach affective data to each student
        for student in students:
            try:
                affective_obj = AffectiveTrait.objects.get(
                    student=student,
                    term=selected_term,
                    session=selected_session
                )
                student.affective_data = {
                    trait: getattr(affective_obj, trait, "")
                    for trait in traits
                }
                student.comment = affective_obj.comment
                student.saved_attendance = affective_obj.attendance
            except AffectiveTrait.DoesNotExist:
                student.affective_data = {trait: "" for trait in traits}
                student.comment = ""
                student.saved_attendance = None
            
            student.display_attendance = present_dict.get(student.id, 0)

    render_ctx = {
        "classes": classes,
        "terms": terms,
        "sessions": sessions,
        "selected_class": selected_class,
        "selected_term": selected_term,
        "selected_session": selected_session,
        "students": students,
        "traits": traits,
        "grades": grades,
        "is_admin": is_admin,
        "is_teacher": not is_admin,
        "school": school,
    }
    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/affective_teacher.html", teacher_ctx)
    return render(request, "score/affective.html", render_ctx)


# Grade points: A=5, B=4, C=3, D=2, E=1. Used for auto teacher comment from affective traits.
AFFECTIVE_GRADE_VALUES = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


def teacher_comment_from_affective_strength(total_points, num_traits=8):
    """
    Return a uniform (gender-neutral) class teacher comment based on average
    affective strength. total_points is sum of grade points; num_traits is 8.
    """
    if num_traits <= 0:
        return ""
    average = total_points / num_traits
    if average >= 4.5:
        return "An excellent student who demonstrates outstanding character and participates positively in all class activities. Keep it up."
    if average >= 3.5:
        return "Demonstrates positive character traits and a good attitude towards school. Keep it up."
    if average >= 2.5:
        return "Shows a willingness to improve. With more effort, greater improvement is expected."
    if average >= 1.5:
        return "Needs to show more commitment to positive behaviour and class activities. You can do better."
    if average >= 1.0:
        return "Requires more effort in character and participation. We encourage you to improve."
    return ""


@school_required
def save_affective_view(request):
    school = request.school

    if request.method != "POST":
        return redirect("affective")

    class_id = request.POST.get("class_id")
    term_id = request.POST.get("term")
    session_id = request.POST.get("session")

    selected_class = get_object_or_404(
        ClassGroup, id=class_id, school=school
    )
    selected_term = get_object_or_404(Term, id=term_id)
    selected_session = get_object_or_404(AcademicSession, id=session_id)

    students = Student.objects.filter(
        class_group=selected_class,
        session=selected_session
    )

    traits = [
        "neatness", "leadership", "punctuality", "cooperation",
        "creativity", "relationship", "hardwork", "work_independently"
    ]
    grade_values = AFFECTIVE_GRADE_VALUES

    for student in students:
        affective_data = {}
        total_score = 0
        count_graded = 0

        for trait in traits:
            grade = request.POST.get(f"{student.id}_{trait}")
            if grade in grade_values:
                affective_data[trait] = grade
                total_score += grade_values[grade]
                count_graded += 1

        affective_data["attendance"] = request.POST.get(
            f"{student.id}_attendance", 0
        )
        comment = request.POST.get(f"{student.id}_comment", "").strip()
        # Auto-fill comment from trait strength if left empty (uniform, not sex-based)
        if not comment and count_graded > 0:
            comment = teacher_comment_from_affective_strength(total_score, len(traits))
        affective_data["comment"] = comment

        AffectiveTrait.objects.update_or_create(
            student=student,
            term=selected_term,
            session=selected_session,
            defaults=affective_data
        )

        for score in Score.objects.filter(
            student=student,
            term=selected_term,
            session=selected_session
        ):
            score.affective = (total_score / len(traits)) * 2
            score.save()

    messages.success(request, "Affective traits saved successfully!")
    return redirect(
        f"/affective/?class_id={class_id}&term={term_id}&session={session_id}"
    )




# core/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from score.models import ClassGroup, Student, PsychomotorSkill, Term, AcademicSession, Score  # adjust path if needed



@school_required
def psychomotor_view(request):
    """
    Psychomotor skills view - Admins see all classes, Teachers see only their class
    """
    school = request.school
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    classes = context['classes']
    
    terms = Term.objects.all()
    sessions = AcademicSession.objects.all()
    
    # --- Get selected class ---
    class_id = request.GET.get("class_id") or request.POST.get("class_id")
    
    if is_admin:
        if class_id:
            selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
        else:
            selected_class = None
    else:
        selected_class = context['class_group']
    
    # --- Get term and session ---
    term_id = request.GET.get("term") or request.POST.get("term")
    session_id = request.GET.get("session") or request.POST.get("session")
    
    selected_term = get_object_or_404(Term, id=term_id) if term_id else None
    selected_session = get_object_or_404(AcademicSession, id=session_id) if session_id else None
    
    students = []
    skills = ["movement", "coordination", "dexterity", "strength", "flexibility", "speed"]
    grades = ["A", "B", "C", "D", "E"]
    
    # --- Get students if class, term, and session are selected ---
    if selected_class and selected_term and selected_session:
        students = Student.objects.filter(
            class_group=selected_class,
            session=selected_session
        )
        
        for student in students:
            try:
                obj = PsychomotorSkill.objects.get(
                    student=student,
                    term=selected_term,
                    session=selected_session
                )
                student.psychomotor_data = {
                    skill: getattr(obj, skill, "")
                    for skill in skills
                }
            except PsychomotorSkill.DoesNotExist:
                student.psychomotor_data = {skill: "" for skill in skills}

    render_ctx = {
        "classes": classes,
        "terms": terms,
        "sessions": sessions,
        "selected_class": selected_class,
        "selected_term": selected_term,
        "selected_session": selected_session,
        "students": students,
        "skills": skills,
        "grades": grades,
        "is_admin": is_admin,
        "is_teacher": not is_admin,
        "school": school,
    }
    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/psychomotor_teacher.html", teacher_ctx)
    return render(request, "score/psychomotor.html", render_ctx)





@school_required
def save_psychomotor_view(request):
    school = request.school

    if request.method != "POST":
        return redirect("psychomotor")

    class_id = request.POST.get("class_id")
    term_id = request.POST.get("term")
    session_id = request.POST.get("session")

    selected_class = get_object_or_404(
        ClassGroup, id=class_id, school=school
    )
    selected_term = get_object_or_404(Term, id=term_id)
    selected_session = get_object_or_404(AcademicSession, id=session_id)

    students = Student.objects.filter(
        class_group=selected_class,
        session=selected_session
    )

    skills = ["movement", "coordination", "dexterity", "strength", "flexibility", "speed"]
    grade_values = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}

    for student in students:
        psychomotor_data = {}
        total_score = 0

        for skill in skills:
            grade = request.POST.get(f"{student.id}_{skill}")
            if grade in grade_values:
                psychomotor_data[skill] = grade
                total_score += grade_values[grade]
            else:
                psychomotor_data[skill] = ""

        PsychomotorSkill.objects.update_or_create(
            student=student,
            term=selected_term,
            session=selected_session,
            defaults=psychomotor_data
        )

        for score in Score.objects.filter(
            student=student,
            term=selected_term,
            session=selected_session
        ):
            score.psychomotor = (total_score / len(skills)) * 2
            score.save()

    messages.success(request, "Psychomotor skills saved successfully!")
    return redirect("psychomotor")



from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.template.loader import render_to_string
from django.http import HttpResponse
from io import BytesIO
from datetime import datetime
import os

from .models import (
    Student, Score, ClassGroup, AffectiveTrait, PsychomotorSkill,
    SchoolSetting
)


# -------------------- REPORT CARD VIEW -------------------- #
from django.shortcuts import render, get_object_or_404
from django.shortcuts import render, get_object_or_404
from .models import Student, Score, AcademicSession, Term, SchoolSetting, AffectiveTrait, PsychomotorSkill  # Add missing imports
from .helpers import ScoreHelper, is_result_published
# -------------------- REPORT CARD HOME -------------------- #
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import ClassGroup, Score, AcademicSession, Term, SchoolSetting  # Adjust imports as needed

from django.shortcuts import render, redirect
from django.contrib import messages
from .models import ClassGroup, AcademicSession, Term, SchoolSetting  # Adjust imports as needed



from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from datetime import datetime
from .models import ClassGroup, Student, AcademicSession, Term, SchoolSetting  # Adjust imports; ensure Student is included

"""
@school_required
def reportcard_home(request):

    # Report card home - Admins see all classes, Teachers see only their class

    school = request.school
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    classes = context['classes']
    
    # Get sessions and terms
    all_sessions = list(AcademicSession.objects.values_list('name', flat=True))
    sessions = sorted(all_sessions, key=lambda x: (x.split('/')[0], x.split('/')[1]), reverse=True) if all_sessions else ["2025/2026"]
    
    all_terms = list(Term.objects.values_list('name', flat=True))
    terms = sorted(all_terms) if all_terms else ["First Term"]
    
    default_session = '2025/2026' if '2025/2026' in sessions else sessions[0]
    default_term = 'First Term' if 'First Term' in terms else terms[0]
    
    if request.method == "POST":
        session = request.POST.get("session") or default_session
        term = request.POST.get("term") or default_term
        class_id = request.POST.get("class_id")
        
        if not (session and term and class_id):
            messages.error(request, "Please select session, term and class.")
        else:
            # Verify class access
            if is_admin:
                valid_class = ClassGroup.objects.filter(id=class_id, school=school).exists()
            else:
                valid_class = (int(class_id) == context['class_group'].id)
            
            if valid_class:
                if AcademicSession.objects.filter(name=session).exists() and Term.objects.filter(name=term).exists():
                    return redirect("reportcard_students", class_id=class_id, session=session, term=term)
                else:
                    messages.error(request, "Invalid session or term selected.")
            else:
                messages.error(request, "Invalid class selected.")
    
    return render(request, "score/reportcard_home.html", {
        "classes": classes,
        "sessions": sessions,
        "terms": terms,
        "default_session": default_session,
        "default_term": default_term,
        "is_admin": is_admin,
        "is_teacher": not is_admin,
    })
"""

@school_required
def reportcard_home(request):
    """
    Report card home - Admins see all classes, Teachers see only their class, Students see only their class
    """
    school = request.school
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    is_teacher = context['is_teacher']
    is_student = context['is_student']
    classes = context['classes']
    user_class_group = context['class_group']
    
    # Get sessions and terms
    all_sessions = list(AcademicSession.objects.values_list('name', flat=True))
    sessions = sorted(all_sessions, key=lambda x: (x.split('/')[0], x.split('/')[1]), reverse=True) if all_sessions else ["2025/2026"]
    
    all_terms = list(Term.objects.values_list('name', flat=True))
    terms = sorted(all_terms) if all_terms else ["First Term"]
    
    default_session = '2025/2026' if '2025/2026' in sessions else sessions[0]
    default_term = 'First Term' if 'First Term' in terms else terms[0]
    
    # Default class for teacher/student
    default_class = user_class_group if (is_teacher or is_student) else None
    
    if request.method == "POST":
        session = request.POST.get("session") or default_session
        term = request.POST.get("term") or default_term
        class_id = request.POST.get("class_id")
        
        if not (session and term and class_id):
            messages.error(request, "Please select session, term and class.")
        else:
            # Verify class access based on user role
            if is_admin:
                valid_class = ClassGroup.objects.filter(id=class_id, school=school).exists()
            elif is_teacher or is_student:
                valid_class = (int(class_id) == user_class_group.id)
            else:
                valid_class = False
            
            if valid_class:
                if AcademicSession.objects.filter(name=session).exists() and Term.objects.filter(name=term).exists():
                    from django.urls import reverse
                    url = reverse("reportcard_students", kwargs={"class_id": class_id, "session": session, "term": term})
                    if request.GET.get("embed"):
                        url += "?embed=1"
                    return redirect(url)
                else:
                    messages.error(request, "Invalid session or term selected.")
            else:
                messages.error(request, "You do not have access to this class.")

    render_ctx = {
        "classes": classes,
        "sessions": sessions,
        "terms": terms,
        "default_session": default_session,
        "default_term": default_term,
        "default_class": default_class,
        "is_admin": is_admin,
        "is_teacher": is_teacher,
        "is_student": is_student,
        "user_class_group": user_class_group,
        "school": school,
    }
    if is_teacher and user_class_group:
        teacher_ctx = get_teacher_dashboard_context(user_class_group)
        teacher_ctx.update(render_ctx)
        return render(request, "score/reportcard_home_teacher.html", teacher_ctx)
    if is_student and request.GET.get("embed"):
        response = render(request, "score/reportcard_home_embed.html", render_ctx)
        response["X-Frame-Options"] = "SAMEORIGIN"
        return response
    return render(request, "score/reportcard_home.html", render_ctx)


# -------------------- DJANGO CORE -------------------- #
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.conf import settings
from django.db.models import Q

# -------------------- PYTHON STANDARD LIBRARY -------------------- #
import os
import zipfile
import logging
from io import BytesIO
from datetime import datetime

# -------------------- PDF / HTML RENDERING -------------------- #

def fetch_resources(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those resources
    """
    if not uri:
        return uri
        
    import os
    from django.conf import settings
    from django.contrib.staticfiles import finders

    path = None
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ""))
    elif uri.startswith(settings.STATIC_URL):
        path = os.path.join(settings.STATIC_ROOT, uri.replace(settings.STATIC_URL, "")) if settings.STATIC_ROOT else None
        if path is None or not os.path.isfile(path):
            found = finders.find(uri.replace(settings.STATIC_URL, ""))
            if found:
                path = found

    if path and os.path.isfile(path):
        return path
    return uri

class XHTML2PDFWrapper:
    def __init__(self, *args, **kwargs):
        self.string = kwargs.get('string') or (args[0] if args else "")
        self.base_url = kwargs.get('base_url', '')

    def write_pdf(self, target, **kwargs):
        from xhtml2pdf import pisa
        from io import BytesIO
        
        # pisa.CreatePDF handles strings or byte streams. We pass bytes.
        pdf_source = BytesIO(self.string.encode("utf-8"))
        
        if isinstance(target, str):
            with open(target, "wb") as f:
                pisa_status = pisa.CreatePDF(pdf_source, dest=f, link_callback=fetch_resources)
                if pisa_status.err:
                    raise Exception("xhtml2pdf generation error")
        else:
            pisa_status = pisa.CreatePDF(pdf_source, dest=target, link_callback=fetch_resources)
            if pisa_status.err:
                raise Exception("xhtml2pdf generation error")

def get_weasyprint_HTML(*args, **kwargs):
    try:
        import os
        # Windows requires explicit DLL directory additions for GTK3 runtime from python 3.8+
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(r"C:\Program Files\GTK3-Runtime Win64\bin")
            except Exception:
                pass
        from weasyprint import HTML
        return HTML(*args, **kwargs)
    except Exception as exc:
        logger.warning("WeasyPrint import failed (%s), falling back to xhtml2pdf", exc)
        return XHTML2PDFWrapper(*args, **kwargs)

# Expose HTML as a lazy alias so existing call sites still work.
HTML = get_weasyprint_HTML

# -------------------- MODELS -------------------- #
from .models import (
    ClassGroup,
    Student,
    Score,
    AffectiveTrait,
    PsychomotorSkill,
    SchoolSetting,
    AcademicSession,
    Term,
    PublishedResult,
    School,
)

# -------------------- HELPERS -------------------- #
from .helpers import ScoreHelper, is_result_published

# -------------------- LOGGER -------------------- #
logger = logging.getLogger(__name__)


def head_comment_from_percentage(pct: float) -> str:
    if pct >= 70:
        return "Keep up the good work."
    elif pct >= 50:
        return "You are doing well, but there is room for improvement."
    else:
        return "You need to improve in your work."


# -------------------- HELPER: Check if student result is published -------------------- #
def is_student_result_published(student, term, session):
    """
    Check if a specific student's result is published for the given term and session.
    Returns True if there's a PublishedResult record for this student.
    """
    return PublishedResult.objects.filter(
        student=student,
        term=term,
        session=session
    ).exists()


@school_required
def reportcard_view(request, student_id, session, term):
    school = request.school
    
    # Verify student belongs to this school
    student = get_object_or_404(Student, id=student_id, school=school)

    # setting = SchoolSetting.objects.first()
    setting = get_object_or_404(SchoolSetting, school=school)
    session_str = session or "2025/2026"
    term_str = term or "First Term"

    academic_session = get_object_or_404(AcademicSession, name=session_str)
    current_term_obj = get_object_or_404(Term, name=term_str)

    # Check if THIS SPECIFIC STUDENT's result is published
    if not is_student_result_published(student, current_term_obj, academic_session):
        messages.error(
            request,
            f"Result for {student.full_name} in {current_term_obj.name} ({academic_session.name}) is not published yet."
        )
        return redirect(
            "reportcard_students",
            class_id=student.class_group.id,
            session=session_str,
            term=term_str
        )

    scores = Score.objects.filter(
        student=student,
        session=academic_session,
        term=current_term_obj
    ).select_related('subject')

    # Assign per-subject positions
    positions_map = {}
    for subject in {s.subject for s in scores}:
        subject_scores = Score.objects.filter(
            subject=subject,
            student__class_group=student.class_group,
            session=academic_session,
            term=current_term_obj
        ).order_by("-total")
        for idx, sc in enumerate(subject_scores, start=1):
            positions_map[sc.id] = ScoreHelper.ordinal(idx)

    for s in scores:
        s.ordinal_position = positions_map.get(s.id, "—")

    # Dynamic assessment components
    scoring_scheme = student.class_group.scoring_system

    SCHEMES = {
        'scheme_1': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 20, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 20, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 40, 'key': 'exam'},
        ],
        'scheme_2': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 60, 'key': 'exam'},
        ],
        'scheme_3': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 15, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 15, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 50, 'key': 'exam'},
        ],
        'scheme_4': [
            {'name': 'CA1', 'percentage': 10, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 70, 'key': 'exam'},
        ],
    }

    if scoring_scheme == 'custom':
        try:
            custom_system = student.class_group.custom_scoring_system
            if custom_system.is_configured():
                assessment_components = [
                    {'name': name, 'percentage': int(pct), 'key': name.lower().replace(' ', '_')}
                    for name, pct in custom_system.components.items()
                    if pct > 0
                ]
            else:
                assessment_components = SCHEMES['scheme_1']
        except AttributeError:
            assessment_components = SCHEMES['scheme_1']
    else:
        assessment_components = SCHEMES.get(scoring_scheme, SCHEMES['scheme_1'])

    # Attach scores_dict to each Score object
    for s in scores:
        s.scores_dict = {}

        if scoring_scheme == 'custom' and s.custom_scores:
            for name, value in s.custom_scores.items():
                key = name.lower().replace(' ', '_')
                s.scores_dict[key] = value
        else:
            s.scores_dict.update({
                'ca1': s.ca1 or None,
                'ca2': s.ca2 or None,
                'ca3': s.ca3 or None,
                'exam': s.exam or None,
            })

        for comp in assessment_components:
            if comp['key'] not in s.scores_dict:
                s.scores_dict[comp['key']] = None

    # Affective & Psychomotor
    affective_data = {}
    attendance = 0
    teacher_comment = "No comment provided."
    try:
        affective = AffectiveTrait.objects.get(
            student=student,
            session=academic_session,
            term=current_term_obj
        )
        affective_data = {
            "neatness": affective.neatness,
            "leadership": affective.leadership,
            "punctuality": affective.punctuality,
            "cooperation": affective.cooperation,
            "creativity": affective.creativity,
            "relationship": affective.relationship,
            "hardwork": affective.hardwork,
            "work_independently": affective.work_independently,
        }
        attendance = affective.attendance or 0
        if affective.comment:
            teacher_comment = affective.comment
    except AffectiveTrait.DoesNotExist:
        pass

    psychomotor_data = {}
    try:
        psychomotor = PsychomotorSkill.objects.get(
            student=student,
            session=academic_session,
            term=current_term_obj
        )
        psychomotor_data = {
            "movement": psychomotor.movement,
            "coordination": psychomotor.coordination,
            "dexterity": psychomotor.dexterity,
            "strength": psychomotor.strength,
            "flexibility": psychomotor.flexibility,
            "speed": psychomotor.speed,
        }
    except PsychomotorSkill.DoesNotExist:
        pass

    # Current Student Totals
    total_score = sum(s.total for s in scores if s.total)
    num_subjects = len(scores)
    max_total_score = num_subjects * 100
    overall_avg = round(total_score / num_subjects, 2) if num_subjects else 0
    overall_percentage = round((total_score / max_total_score) * 100, 2) if max_total_score else 0

    # Subject highest/lowest score averages: compute from class totals per subject
    class_subjects_for_avg = Subject.objects.filter(class_group=student.class_group)
    subject_max_totals = []
    subject_min_totals = []
    for subj in class_subjects_for_avg:
        subj_scores = Score.objects.filter(
            subject=subj,
            student__class_group=student.class_group,
            session=academic_session,
            term=current_term_obj
        ).values_list("total", flat=True)
        totals = [t for t in subj_scores if t is not None]
        if totals:
            subject_max_totals.append(max(totals))
            subject_min_totals.append(min(totals))
    subject_highest_avg = round(sum(subject_max_totals) / len(subject_max_totals), 2) if subject_max_totals else 0
    subject_lowest_avg = round(sum(subject_min_totals) / len(subject_min_totals), 2) if subject_min_totals else 0

    # ===== CLASS STATISTICS CALCULATION (MATCHING ENTERSCORE LOGIC) =====
    # Get all students in the same class and session (like enterscore does)
    class_students = Student.objects.filter(
        class_group=student.class_group,
        session=academic_session
    ).order_by("surname", "first_name")
    
    # Get all subjects for this class
    class_subjects = Subject.objects.filter(class_group=student.class_group)
    
    # Calculate average for each student in the class
    student_averages = []
    for class_student in class_students:
        # Get all scores for this student across all subjects
        student_all_scores = Score.objects.filter(
            student=class_student,
            subject__in=class_subjects,
            term=current_term_obj,
            session=academic_session
        )
        
        # Calculate total and average (only if scores exist)
        if student_all_scores.exists():
            student_total = sum(s.total for s in student_all_scores if s.total is not None)
            student_num_subjects = student_all_scores.filter(total__isnull=False).count()
            
            if student_num_subjects > 0:
                student_avg = student_total / student_num_subjects
                student_averages.append(student_avg)
    
    # Calculate class statistics
    if student_averages:
        class_average = round(sum(student_averages) / len(student_averages), 2)
        class_highest_avg = round(max(student_averages), 2)
        class_lowest_avg = round(min(student_averages), 2)
    else:
        class_average = 0
        class_highest_avg = 0
        class_lowest_avg = 0

    # Grade
    if overall_percentage >= 91:
        overall_grade = "A+"
    elif overall_percentage >= 81:
        overall_grade = "A"
    elif overall_percentage >= 71:
        overall_grade = "B+"
    elif overall_percentage >= 61:
        overall_grade = "B"
    elif overall_percentage >= 56:
        overall_grade = "C+"
    elif overall_percentage >= 51:
        overall_grade = "C"
    elif overall_percentage >= 33:
        overall_grade = "P"
    else:
        overall_grade = "F"

    head_comment = head_comment_from_percentage(overall_percentage)

    # Chart Data Generation
    chart_labels = [s.subject.name for s in scores]
    chart_data = [round(s.total if s.total else 0, 1) for s in scores]
    
    # Generate colors for chart (use a color palette)
    colors = [
        "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF",
        "#FF9F40", "#FF6384", "#C9CBCF", "#4BC0C0", "#FF6384",
        "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40",
    ]
    chart_colors = [colors[i % len(colors)] for i in range(len(chart_labels))]

    context = {
        "school": setting,
        # "school": school,
        "student": student,
        "scores": scores,
        "assessment_components": assessment_components,
        "affective": affective_data,
        "psychomotor": psychomotor_data,
        "setting": setting,
        # "setting": school,
        "total_score": total_score,
        "max_total_score": max_total_score,
        "overall_avg": overall_avg,
        "overall_percentage": overall_percentage,
        "overall_grade": overall_grade,
        "subject_highest_avg": subject_highest_avg,
        "subject_lowest_avg": subject_lowest_avg,
        "teacher_comment": teacher_comment,
        "head_comment": head_comment,
        "attendance": attendance,
        "session": session_str,
        "term": term_str,
        # Class statistics
        "class_average": class_average,
        "class_highest_avg": class_highest_avg,
        "class_lowest_avg": class_lowest_avg,
        # Chart data
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "chart_colors": chart_colors,
    }

    return render(request, "score/reportcard.html", context)

"""
@school_required
def reportcard_view(request, student_id, session, term):
    school = request.school  # ✅ Add this line
    
    # ✅ Verify student belongs to this school
    student = get_object_or_404(Student, id=student_id, school=school)

    setting = SchoolSetting.objects.first()
    session_str = session or "2025/2026"
    term_str = term or "First Term"

    academic_session = get_object_or_404(AcademicSession, name=session_str)
    current_term_obj = get_object_or_404(Term, name=term_str)

    # ✅ Check if THIS SPECIFIC STUDENT's result is published
    if not is_student_result_published(student, current_term_obj, academic_session):
        messages.error(
            request,
            f"Result for {student.full_name} in {current_term_obj.name} ({academic_session.name}) is not published yet."
        )
        return redirect(
            "reportcard_students",
            class_id=student.class_group.id,
            session=session_str,
            term=term_str
        )

    scores = Score.objects.filter(
        student=student,
        session=academic_session,
        term=current_term_obj
    ).select_related('subject')

    # Assign per-subject positions
    positions_map = {}
    for subject in {s.subject for s in scores}:
        subject_scores = Score.objects.filter(
            subject=subject,
            student__class_group=student.class_group,
            session=academic_session,
            term=current_term_obj
        ).order_by("-total")
        for idx, sc in enumerate(subject_scores, start=1):
            positions_map[sc.id] = ScoreHelper.ordinal(idx)

    for s in scores:
        s.ordinal_position = positions_map.get(s.id, "—")

    # Dynamic assessment components
    scoring_scheme = student.class_group.scoring_system

    SCHEMES = {
        'scheme_1': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 20, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 20, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 40, 'key': 'exam'},
        ],
        'scheme_2': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 60, 'key': 'exam'},
        ],
        'scheme_3': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 15, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 15, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 50, 'key': 'exam'},
        ],
        'scheme_4': [
            {'name': 'CA1', 'percentage': 10, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 70, 'key': 'exam'},
        ],
    }

    if scoring_scheme == 'custom':
        try:
            custom_system = student.class_group.custom_scoring_system
            if custom_system.is_configured():
                assessment_components = [
                    {'name': name, 'percentage': int(pct), 'key': name.lower().replace(' ', '_')}
                    for name, pct in custom_system.components.items()
                    if pct > 0
                ]
            else:
                assessment_components = SCHEMES['scheme_1']
        except AttributeError:
            assessment_components = SCHEMES['scheme_1']
    else:
        assessment_components = SCHEMES.get(scoring_scheme, SCHEMES['scheme_1'])

    # Attach scores_dict to each Score object
    for s in scores:
        s.scores_dict = {}

        if scoring_scheme == 'custom' and s.custom_scores:
            for name, value in s.custom_scores.items():
                key = name.lower().replace(' ', '_')
                s.scores_dict[key] = value
        else:
            s.scores_dict.update({
                'ca1': s.ca1 or None,
                'ca2': s.ca2 or None,
                'ca3': s.ca3 or None,
                'exam': s.exam or None,
            })

        for comp in assessment_components:
            if comp['key'] not in s.scores_dict:
                s.scores_dict[comp['key']] = None

    # Affective & Psychomotor
    affective_data = {}
    attendance = 0
    teacher_comment = "No comment provided."
    try:
        affective = AffectiveTrait.objects.get(
            student=student,
            session=academic_session,
            term=current_term_obj
        )
        affective_data = {
            "neatness": affective.neatness,
            "leadership": affective.leadership,
            "punctuality": affective.punctuality,
            "cooperation": affective.cooperation,
            "creativity": affective.creativity,
            "relationship": affective.relationship,
            "hardwork": affective.hardwork,
            "work_independently": affective.work_independently,
        }
        attendance = affective.attendance or 0
        if affective.comment:
            teacher_comment = affective.comment
    except AffectiveTrait.DoesNotExist:
        pass

    psychomotor_data = {}
    try:
        psychomotor = PsychomotorSkill.objects.get(
            student=student,
            session=academic_session,
            term=current_term_obj
        )
        psychomotor_data = {
            "movement": psychomotor.movement,
            "coordination": psychomotor.coordination,
            "dexterity": psychomotor.dexterity,
            "strength": psychomotor.strength,
            "flexibility": psychomotor.flexibility,
            "speed": psychomotor.speed,
        }
    except PsychomotorSkill.DoesNotExist:
        pass

    # Totals
    total_score = sum(s.total for s in scores if s.total)
    num_subjects = len(scores)
    max_total_score = num_subjects * 100
    overall_avg = round(total_score / num_subjects, 2) if num_subjects else 0
    overall_percentage = round((total_score / max_total_score) * 100, 2) if max_total_score else 0

    # Grade
    if overall_percentage >= 91:
        overall_grade = "A+"
    elif overall_percentage >= 81:
        overall_grade = "A"
    elif overall_percentage >= 71:
        overall_grade = "B+"
    elif overall_percentage >= 61:
        overall_grade = "B"
    elif overall_percentage >= 56:
        overall_grade = "C+"
    elif overall_percentage >= 51:
        overall_grade = "C"
    elif overall_percentage >= 33:
        overall_grade = "P"
    else:
        overall_grade = "F"

    head_comment = head_comment_from_percentage(overall_percentage)

    # Chart Data Generation
    chart_labels = [s.subject.name for s in scores]
    chart_data = [round(s.total if s.total else 0, 1) for s in scores]
    
    # Generate colors for chart (use a color palette)
    colors = [
        "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF",
        "#FF9F40", "#FF6384", "#C9CBCF", "#4BC0C0", "#FF6384",
        "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40",
    ]
    chart_colors = [colors[i % len(colors)] for i in range(len(chart_labels))]

    context = {
        "school": setting,
        "student": student,
        "scores": scores,
        "assessment_components": assessment_components,
        "affective": affective_data,
        "psychomotor": psychomotor_data,
        "setting": setting,
        "total_score": total_score,
        "max_total_score": max_total_score,
        "overall_avg": overall_avg,
        "overall_percentage": overall_percentage,
        "overall_grade": overall_grade,
        "teacher_comment": teacher_comment,
        "head_comment": head_comment,
        "attendance": attendance,
        "session": session_str,
        "term": term_str,
        # Chart data
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "chart_colors": chart_colors,
    }

    return render(request, "score/reportcard.html", context)
"""


@school_required
def reportcard_students(request, class_id, session, term):
    school = request.school
    
    # Get user context for role-based access
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    is_teacher = context['is_teacher']
    is_student = context['is_student']
    user_class_group = context['class_group']
    current_user_student = context.get('student')
    
    # Verify class belongs to this school
    selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
    
    # Role-based access control
    if is_teacher:
        # Teachers can only view their assigned class
        if selected_class.id != user_class_group.id:
            messages.error(request, "You do not have access to this class.")
            return redirect("reportcard_home")
    elif is_student:
        # Students can only view their own class
        if selected_class.id != user_class_group.id:
            messages.error(request, "You do not have access to this class.")
            return redirect("reportcard_home")
    # Admin has access to all classes (already verified by get_object_or_404)

    try:
        start_year, end_year = session.split('/')
        start_year = int(start_year)
        end_year = int(end_year)
        session_start_date = datetime(start_year, 9, 1).date()
    except (ValueError, IndexError):
        session_start_date = datetime.now().date()

    current_date = datetime.now().date()

    # Get term and session objects
    try:
        academic_session = AcademicSession.objects.get(name=session)
        term_obj = Term.objects.get(name=term)
    except (AcademicSession.DoesNotExist, Term.DoesNotExist):
        messages.error(request, "Invalid session or term.")
        return redirect("reportcard_home")

    # Get students with published results for this term/session
    published_student_ids = PublishedResult.objects.filter(
        session=academic_session,
        term=term_obj,
        student__class_group=selected_class
    ).values_list('student_id', flat=True)

    # Filter students based on user role
    if is_student:
        # Students can only see themselves
        students = Student.objects.filter(
            id=current_user_student.id,
            id__in=published_student_ids,
            class_group=selected_class
        ).order_by("surname", "first_name")
    else:
        # Admin and Teacher can see all students with published results
        students = Student.objects.filter(
            id__in=published_student_ids,
            class_group=selected_class
        ).order_by("surname", "first_name")

    # Customize message based on role
    if not students.exists():
        if is_student:
            messages.info(request, f"Your results for {term} ({session}) have not been published yet.")
        else:
            messages.info(request, f"No published results found for '{selected_class.name}' in {term} ({session}).")

    render_ctx = {
        "selected_class": selected_class,
        "students": students,
        "session": session,
        "term": term,
        "is_admin": is_admin,
        "is_teacher": is_teacher,
        "is_student": is_student,
        "user_class_group": user_class_group,
        "current_user_student": current_user_student,
        "school": school,
    }
    if is_teacher and user_class_group:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/reportcard_students_teacher.html", teacher_ctx)
    if is_student and request.GET.get("embed"):
        response = render(request, "score/reportcard_students_embed.html", render_ctx)
        response["X-Frame-Options"] = "SAMEORIGIN"
        return response
    return render(request, "score/reportcard_students.html", render_ctx)

def weasyprint_url_fetcher(url):
    import urllib.parse
    import os
    import pathlib
    from django.conf import settings
    from django.contrib.staticfiles import finders
    try:
        from weasyprint import default_url_fetcher
    except ImportError:
        return url

    parsed = urllib.parse.urlparse(url)
    if not parsed.path:
        return default_url_fetcher(url)

    local_path = None
    if parsed.path.startswith(settings.MEDIA_URL):
        rel_path = parsed.path.replace(settings.MEDIA_URL, "", 1)
        rel_path = urllib.parse.unquote(rel_path)
        local_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    elif parsed.path.startswith(settings.STATIC_URL):
        rel_path = parsed.path.replace(settings.STATIC_URL, "", 1)
        rel_path = urllib.parse.unquote(rel_path)
        if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT:
            local_path = os.path.join(settings.STATIC_ROOT, rel_path)
        if not local_path or not os.path.isfile(local_path):
            found = finders.find(rel_path)
            if found:
                local_path = found

    if local_path and os.path.isfile(local_path):
        file_uri = pathlib.Path(local_path).as_uri()
        import logging
        logging.getLogger(__name__).info(f"weasyprint_url_fetcher: Resolved {url} to {file_uri}")
        return default_url_fetcher(file_uri)
    
    import logging
    logging.getLogger(__name__).warning(f"weasyprint_url_fetcher: Could not resolve {url}, falling back to default")
    return default_url_fetcher(url)

@school_required
def reportcard_download_all(request, class_id, session_str, term_str):
    school = request.school  # ✅ Add this line
    
    # ✅ Verify class belongs to this school
    selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)

    try:
        academic_session = AcademicSession.objects.get(name=session_str)
        term_obj = Term.objects.get(name=term_str)
    except (AcademicSession.DoesNotExist, Term.DoesNotExist):
        messages.error(request, "Invalid session or term for download.")
        return redirect("reportcard_students", class_id=class_id, session=session_str, term=term_str)

    # ✅ Get only students with PUBLISHED results
    published_student_ids = PublishedResult.objects.filter(
        session=academic_session,
        term=term_obj,
        student__class_group=selected_class
    ).values_list('student_id', flat=True)

    students_with_scores = Student.objects.filter(
        id__in=published_student_ids,
        class_group=selected_class
    ).distinct()

    if not students_with_scores.exists():
        messages.info(request, f"No published results to download for '{selected_class.name}' in {term_str} ({session_str}).")
        return redirect("reportcard_students", class_id=class_id, session=session_str, term=term_str)

    # Prepare ZIP in memory
    zip_buffer = BytesIO()
    zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)

    generated_count = 0

    for student in students_with_scores:
        try:
            context = reportcard_view_context(student, academic_session, term_obj)
            html_string = render_to_string("score/reportcard.html", context)

            pdf_buffer = BytesIO()
            HTML(
                string=html_string, 
                base_url=request.build_absolute_uri('/'),
                url_fetcher=weasyprint_url_fetcher
            ).write_pdf(pdf_buffer)

            safe_name = student.full_name.replace(' ', '_')
            pdf_filename = f"{safe_name}_{student.id}_reportcard.pdf"
            zip_file.writestr(pdf_filename, pdf_buffer.getvalue())
            generated_count += 1
        except Exception as e:
            messages.error(request, f"Error generating PDF for {student.full_name}: {str(e)}")

    zip_file.close()

    if generated_count == 0:
        messages.error(request, "No report cards were generated.")
        return redirect("reportcard_students", class_id=class_id, session=session_str, term=term_str)

    safe_class = selected_class.name.replace(' ', '_')
    safe_session = session_str.replace('/', '_')
    safe_term = term_str.replace(' ', '_')
    zip_filename = f"{safe_class}_{safe_session}_{safe_term}_ReportCards.zip"

    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
    response.set_cookie('download_complete', 'true', max_age=60)
    return response



@school_required
def reportcard_print_all(request, class_id, session_str, term_str):
    school = request.school  # ✅ Add this line
    
    # ✅ Verify class belongs to this school
    selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)

    # Decode slugs back to DB format
    decoded_session = session_str.replace('-', '/')
    if '/' not in decoded_session and '-' not in decoded_session and len(decoded_session) == 8 and decoded_session.isdigit():
        decoded_session = f"{decoded_session[:4]}/{decoded_session[4:]}"
    decoded_term = term_str.replace('-', ' ').title()

    logger.info(f"Decoded session: '{decoded_session}', term: '{decoded_term}'")

    try:
        academic_session = AcademicSession.objects.get(name=decoded_session)
        term_obj = Term.objects.get(name=decoded_term)
    except (AcademicSession.DoesNotExist, Term.DoesNotExist):
        messages.error(request, "Invalid session or term for printing.")
        return redirect("reportcard_students", class_id=class_id, session=decoded_session, term=decoded_term)

    # ✅ Get only students with PUBLISHED results
    published_student_ids = PublishedResult.objects.filter(
        session=academic_session,
        term=term_obj,
        student__class_group=selected_class
    ).values_list('student_id', flat=True)

    students_with_scores = Student.objects.filter(
        id__in=published_student_ids,
        class_group=selected_class
    ).distinct()

    if not students_with_scores.exists():
        messages.info(request, f"No published results to print for '{selected_class.name}' in {decoded_term} ({decoded_session}).")
        return redirect("reportcard_students", class_id=class_id, session=decoded_session, term=decoded_term)

    # Build combined HTML for all students
    combined_html = ""
    for index, student in enumerate(students_with_scores):
        try:
            context = reportcard_view_context(student, academic_session, term_obj)
            student_html = render_to_string("score/reportcard.html", context)
            combined_html += student_html
            if index != len(students_with_scores) - 1:
                combined_html += '<div style="page-break-after: always;"></div>'
        except Exception as e:
            logger.error(f"Error rendering report card for {student.full_name}: {str(e)}")
            messages.error(request, f"Error rendering report card for {student.full_name}: {str(e)}")

    # Generate combined PDF
    pdf_buffer = BytesIO()
    HTML(
        string=combined_html, 
        base_url=request.build_absolute_uri('/'),
        url_fetcher=weasyprint_url_fetcher
    ).write_pdf(pdf_buffer)

    safe_class = selected_class.name.replace(' ', '_')
    safe_session = decoded_session.replace('/', '_')
    safe_term = decoded_term.replace(' ', '_')
    pdf_filename = f"{safe_class}_{safe_session}_{safe_term}_ReportCards.pdf"

    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{pdf_filename}"'
    return response


@school_required
def send_reportcards_view(request):
    school = request.school

    # 🔑 Get user context (admin / teacher)
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")

    is_admin = context["is_admin"]

    # 🎯 Class visibility logic
    if is_admin:
        classes = ClassGroup.objects.filter(school=school).order_by("name")
        selected_class = None
    else:
        # Teacher: only their class
        selected_class = context.get("class_group")
        if not selected_class:
            messages.error(request, "You are not assigned to any class.")
            return redirect("teacher_dashboard")
        classes = [selected_class]

    sessions = AcademicSession.objects.all()
    terms = Term.objects.all()

    if request.method == "POST":
        class_id = request.POST.get("class_id")
        session_str = request.POST.get("session")
        term_str = request.POST.get("term")
        selected_student_ids = request.POST.getlist("students")

        if not (class_id and session_str and term_str):
            messages.error(request, "Please select class, session, and term.")
            return redirect("send_reportcards")

        # 🔐 Verify class belongs to this school
        selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)

        academic_session = get_object_or_404(AcademicSession, name=session_str)
        term_obj = get_object_or_404(Term, name=term_str)

        # 🎯 Only students with published results
        published_student_ids = PublishedResult.objects.filter(
            session=academic_session,
            term=term_obj,
            student_id__in=selected_student_ids
        ).values_list("student_id", flat=True)

        students = Student.objects.filter(id__in=published_student_ids)

        if not students.exists():
            messages.warning(request, "No published results found for the selected students.")
            return redirect("send_reportcards")

        sent_count = 0
        failed_count = 0

        for student in students:
            if not student.parent_email:
                failed_count += 1
                continue

            try:
                context = reportcard_view_context(student, academic_session, term_obj)
                html_string = render_to_string("score/reportcard.html", context)

                pdf_buffer = BytesIO()
                HTML(
                    string=html_string, 
                    base_url=request.build_absolute_uri("/"),
                    url_fetcher=weasyprint_url_fetcher
                ).write_pdf(pdf_buffer)

                html_body = render_to_string(
                    "score/email_reportcard_message.html",
                    {"student": student}
                )
                text_body = strip_tags(html_body)

                email = EmailMultiAlternatives(
                    subject=f"{student.full_name} - {term_obj.name} Report Card",
                    body=text_body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[student.parent_email],
                )
                email.attach_alternative(html_body, "text/html")

                pdf_filename = f"{student.full_name.replace(' ', '_')}_ReportCard.pdf"
                email.attach(pdf_filename, pdf_buffer.getvalue(), "application/pdf")
                email.send()

                sent_count += 1

            except Exception as e:
                failed_count += 1
                messages.error(request, f"Failed to send to {student.full_name}: {str(e)}")

        messages.success(request, f"✅ {sent_count} report cards sent, ❌ {failed_count} failed.")
        return redirect("send_reportcards")

    render_ctx = {
        "classes": classes,
        "sessions": sessions,
        "terms": terms,
        "is_admin": is_admin,
        "selected_class": selected_class,
        "school": school,
    }
    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/send_reportcards_teacher.html", teacher_ctx)
    return render(request, "score/send_reportcards.html", render_ctx)



from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Student, Term, AcademicSession, PublishedResult

@school_required
def get_students(request, class_id):
    """API endpoint to get students with published results for the send email form"""
    school = request.school  # ✅ Add this line
    
    # ✅ Verify class belongs to this school
    class_group = get_object_or_404(ClassGroup, id=class_id, school=school)
    
    # ✅ Get term and session NAMES (not IDs) from query parameters
    term_name = request.GET.get('term')
    session_name = request.GET.get('session')
    
    if not (term_name and session_name):
        return JsonResponse({"students": []})
    
    try:
        # ✅ Look up by NAME instead of ID
        term = Term.objects.get(name=term_name)
        session = AcademicSession.objects.get(name=session_name)
    except (Term.DoesNotExist, AcademicSession.DoesNotExist):
        return JsonResponse({"students": [], "error": "Invalid term or session"})
    
    # ✅ Only return students with published results
    published_student_ids = PublishedResult.objects.filter(
        term=term,
        session=session,
        student__class_group_id=class_id
    ).values_list('student_id', flat=True)
    
    students = Student.objects.filter(
        id__in=published_student_ids,
        class_group_id=class_id
    ).order_by('surname', 'first_name')
    
    data = {
        "students": [
            {
                "id": s.id, 
                "name": s.full_name, 
                "email": s.parent_email or ""
            } 
            for s in students
        ]
    }
    return JsonResponse(data)


# ==================== CONTEXT HELPER (USED BY PDF GENERATION) ====================
def reportcard_view_context(student, academic_session, term_obj):
    """Generate report card context for a student - reusable for PDF generation"""
    # setting = SchoolSetting.objects.first()
    setting = SchoolSetting.objects.filter(school=student.school).first()

    scores = Score.objects.filter(
        student=student,
        session=academic_session,
        term=term_obj
    ).select_related("subject")

    # Subject positions
    positions_map = {}
    for subject in {s.subject for s in scores}:
        subject_scores = Score.objects.filter(
            subject=subject,
            student__class_group=student.class_group,
            session=academic_session,
            term=term_obj
        ).order_by("-total")

        for idx, sc in enumerate(subject_scores, start=1):
            positions_map[sc.id] = ScoreHelper.ordinal(idx)

    for s in scores:
        s.ordinal_position = positions_map.get(s.id, "—")

    # Dynamic scoring system
    scoring_scheme = student.class_group.scoring_system

    SCHEMES = {
        'scheme_1': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 20, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 20, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 40, 'key': 'exam'},
        ],
        'scheme_2': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 60, 'key': 'exam'},
        ],
        'scheme_3': [
            {'name': 'CA1', 'percentage': 20, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 15, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 15, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 50, 'key': 'exam'},
        ],
        'scheme_4': [
            {'name': 'CA1', 'percentage': 10, 'key': 'ca1'},
            {'name': 'CA2', 'percentage': 10, 'key': 'ca2'},
            {'name': 'CA3', 'percentage': 10, 'key': 'ca3'},
            {'name': 'Exam', 'percentage': 70, 'key': 'exam'},
        ],
    }

    if scoring_scheme == "custom":
        try:
            custom_system = student.class_group.custom_scoring_system
            if custom_system.is_configured():
                assessment_components = [
                    {
                        "name": name,
                        "percentage": int(pct),
                        "key": name.lower().replace(" ", "_"),
                    }
                    for name, pct in custom_system.components.items()
                    if pct > 0
                ]
            else:
                assessment_components = SCHEMES["scheme_1"]
        except AttributeError:
            assessment_components = SCHEMES["scheme_1"]
    else:
        assessment_components = SCHEMES.get(scoring_scheme, SCHEMES["scheme_1"])

    # Attach scores dict
    for s in scores:
        s.scores_dict = {}

        if scoring_scheme == "custom" and s.custom_scores:
            for name, value in s.custom_scores.items():
                key = name.lower().replace(" ", "_")
                s.scores_dict[key] = value
        else:
            s.scores_dict.update({
                "ca1": s.ca1 or None,
                "ca2": s.ca2 or None,
                "ca3": s.ca3 or None,
                "exam": s.exam or None,
            })

        for comp in assessment_components:
            s.scores_dict.setdefault(comp["key"], None)

    # Affective & Attendance
    affective_data = {}
    teacher_comment = "No comment provided."
    attendance = 0

    try:
        aff = AffectiveTrait.objects.get(
            student=student,
            session=academic_session,
            term=term_obj
        )
        affective_data = {
            "neatness": aff.neatness,
            "leadership": aff.leadership,
            "punctuality": aff.punctuality,
            "cooperation": aff.cooperation,
            "creativity": aff.creativity,
            "relationship": aff.relationship,
            "hardwork": aff.hardwork,
            "work_independently": aff.work_independently,
        }
        attendance = aff.attendance or 0
        if aff.comment:
            teacher_comment = aff.comment
    except AffectiveTrait.DoesNotExist:
        pass

    # Psychomotor
    psychomotor_data = {}
    try:
        psy = PsychomotorSkill.objects.get(
            student=student,
            session=academic_session,
            term=term_obj
        )
        psychomotor_data = {
            "movement": psy.movement,
            "coordination": psy.coordination,
            "dexterity": psy.dexterity,
            "strength": psy.strength,
            "flexibility": psy.flexibility,
            "speed": psy.speed,
        }
    except PsychomotorSkill.DoesNotExist:
        pass

    # Current Student Totals
    total_score = sum(s.total for s in scores if s.total)
    num_subjects = scores.count()
    max_total_score = num_subjects * 100

    overall_avg = round(total_score / num_subjects, 2) if num_subjects else 0

    # Subject highest/lowest score averages: compute from class totals per subject (not stored max/min)
    class_subjects_for_avg = Subject.objects.filter(class_group=student.class_group)
    subject_max_totals = []
    subject_min_totals = []
    for subj in class_subjects_for_avg:
        subj_scores = Score.objects.filter(
            subject=subj,
            student__class_group=student.class_group,
            session=academic_session,
            term=term_obj
        ).values_list("total", flat=True)
        totals = [t for t in subj_scores if t is not None]
        if totals:
            subject_max_totals.append(max(totals))
            subject_min_totals.append(min(totals))
    subject_highest_avg = round(sum(subject_max_totals) / len(subject_max_totals), 2) if subject_max_totals else 0
    subject_lowest_avg = round(sum(subject_min_totals) / len(subject_min_totals), 2) if subject_min_totals else 0

    overall_percentage = (
        round((total_score / max_total_score) * 100, 2)
        if max_total_score else 0
    )

    # ===== CLASS STATISTICS CALCULATION =====
    # Get all students in the same class and session
    class_students = Student.objects.filter(
        class_group=student.class_group,
        session=academic_session
    ).order_by("surname", "first_name")
    
    # Get all subjects for this class
    class_subjects = Subject.objects.filter(class_group=student.class_group)
    
    # Count total students and subjects
    total_students_in_class = class_students.count()
    total_subjects = class_subjects.count()
    
    # Calculate average for each student in the class
    student_averages = []
    for class_student in class_students:
        # Get all scores for this student across all subjects
        student_all_scores = Score.objects.filter(
            student=class_student,
            subject__in=class_subjects,
            term=term_obj,
            session=academic_session
        )
        
        # Calculate total and average (only if scores exist)
        if student_all_scores.exists():
            student_total = sum(s.total for s in student_all_scores if s.total is not None)
            student_num_subjects = student_all_scores.filter(total__isnull=False).count()
            
            if student_num_subjects > 0:
                student_avg = student_total / student_num_subjects
                student_averages.append(student_avg)
    
    # Calculate class statistics
    if student_averages:
        class_average = round(sum(student_averages) / len(student_averages), 2)
        class_highest_avg = round(max(student_averages), 2)
        class_lowest_avg = round(min(student_averages), 2)
    else:
        class_average = 0
        class_highest_avg = 0
        class_lowest_avg = 0

    # Grading
    if overall_percentage >= 91:
        overall_grade = "A+"
    elif overall_percentage >= 81:
        overall_grade = "A"
    elif overall_percentage >= 71:
        overall_grade = "B+"
    elif overall_percentage >= 61:
        overall_grade = "B"
    elif overall_percentage >= 56:
        overall_grade = "C+"
    elif overall_percentage >= 51:
        overall_grade = "C"
    elif overall_percentage >= 33:
        overall_grade = "P"
    else:
        overall_grade = "F"

    head_comment = head_comment_from_percentage(overall_percentage)
    verdict = "Promoted" if overall_avg >= 70 else "Needs Improvement"

    # ===== PIE CHART DATA =====
    # Prepare data for subject performance pie chart
    chart_labels = []
    chart_data = []
    chart_colors = []
    
    # Color palette for the chart
    color_palette = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
        '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384',
        '#36A2EB', '#FFCE56', '#FF9F40', '#9966FF', '#C9CBCF'
    ]
    
    for idx, score in enumerate(scores):
        if score.total:
            chart_labels.append(score.subject.name)
            chart_data.append(float(score.total))
            chart_colors.append(color_palette[idx % len(color_palette)])

    return {
        "school": setting,
        "student": student,
        "scores": scores,
        "assessment_components": assessment_components,
        "affective": affective_data,
        "psychomotor": psychomotor_data,
        "setting": setting,
        "total_score": total_score,
        "max_total_score": max_total_score,
        "overall_avg": overall_avg,
        "overall_percentage": overall_percentage,
        "overall_grade": overall_grade,
        "subject_highest_avg": subject_highest_avg,
        "subject_lowest_avg": subject_lowest_avg,
        "verdict": verdict,
        "teacher_comment": teacher_comment,
        "head_comment": head_comment,
        "attendance": attendance,
        "session": academic_session.name,
        "term": term_obj.name,
        # Class statistics
        "class_average": class_average,
        "class_highest_avg": class_highest_avg,
        "class_lowest_avg": class_lowest_avg,
        "total_students_in_class": total_students_in_class,
        "total_subjects": total_subjects,
        # Chart data
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "chart_colors": chart_colors,
    }
















from django.shortcuts import render, redirect
from django.contrib import messages
from .models import AcademicSession, ClassGroup, Student, StudentPromotion, GraduationRecord
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from .models import AcademicSession, ClassGroup, Student, StudentPromotion, GraduationRecord
import re

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from .models import AcademicSession, ClassGroup, Student, StudentPromotion, GraduationRecord
from .decorators import school_required
# from .utils import get_user_context  # your helper that returns user info

@school_required
def promote_students(request):
    """
    Promote or graduate students.
    Admins see all classes; teachers see only their assigned classes.
    """
    school = request.school
    from django.utils import timezone

    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")

    is_admin = context['is_admin']
    classes = context['classes']

    # --- GET selected class ---
    if is_admin:
        selected_class_id = request.GET.get("class_id")
        if selected_class_id:
            selected_class = get_object_or_404(ClassGroup, id=selected_class_id)
        else:
            selected_class = None
    else:
        selected_class = context['class_group']
        selected_class_id = selected_class.id if selected_class else None

    # --- GET selected session ---
    selected_session_id = request.GET.get("session")
    selected_session = None
    if selected_session_id:
        selected_session = get_object_or_404(AcademicSession, id=selected_session_id)

    sessions = AcademicSession.objects.all().order_by('-name')
    students = []

    if selected_class and selected_session:
        students = Student.objects.filter(
            class_group=selected_class,
            session=selected_session,
            is_graduated=False
        ).order_by("surname", "first_name", "middle_name")

    # Helper: update exam number for promotion (format SA/JSS3/0008 — class name uppercase)
    def update_exam_no(exam_no, old_class_name, new_class_name):
        if not exam_no:
            return None
        parts = exam_no.split("/")
        if len(parts) != 3:
            return exam_no
        prefix, _, serial = parts
        class_upper = (new_class_name or "").strip().upper()
        new_exam_no = f"{prefix}/{class_upper}/{serial}"
        counter = 1
        try:
            serial_int = int(serial)
        except ValueError:
            serial_int = 0
        while Student.objects.filter(exam_no=new_exam_no).exists():
            new_serial = str(serial_int + counter).zfill(max(len(serial), 4))
            new_exam_no = f"{prefix}/{class_upper}/{new_serial}"
            counter += 1
        return new_exam_no

    # ===== POST =====
    if request.method == "POST":
        selected_session_id = request.POST.get("session")
        selected_class_id = request.POST.get("class_group")
        promote_to_session_id = request.POST.get("promote_to_session")
        promote_to_id = request.POST.get("promote_to")
        selected_students = request.POST.getlist("students")
        action_type = request.POST.get("action_type")

        if not selected_session_id or not selected_class_id:
            messages.error(request, "Please select the current session and class.")
            return redirect("promote_students")

        selected_session = get_object_or_404(AcademicSession, id=selected_session_id)
        if is_admin:
            selected_class = get_object_or_404(ClassGroup, id=selected_class_id)
        else:
            selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)

        if not selected_students:
            messages.warning(request, "No students selected.")
            return redirect("promote_students")

        promoted_count = 0
        graduated_count = 0

        # --- Graduation ---
        if action_type == "graduate":
            for student_id in selected_students:
                student = get_object_or_404(Student, id=student_id)
                if not is_admin and student.school != school:
                    continue

                if student.is_graduated:
                    messages.info(request, f"{student.full_name} is already graduated.")
                    continue

                student.is_graduated = True
                student.save()

                GraduationRecord.objects.create(
                    student=student,
                    class_group=selected_class,
                    session=selected_session,
                    remarks=f"Graduated from {selected_class.name} ({selected_session.name})"
                )

                StudentPromotion.objects.create(
                    student=student,
                    from_class=selected_class,
                    to_class=None,
                    status="Graduated",
                    session=selected_session
                )
                graduated_count += 1

            messages.success(request, f"{graduated_count} students graduated successfully.")
            return redirect(f"{request.path}?class_id={selected_class_id}&session={selected_session_id}")

        # --- Promotion ---
        if not promote_to_session_id:
            messages.error(request, "Please select the session to promote to.")
            return redirect("promote_students")

        promote_to_session = get_object_or_404(AcademicSession, id=promote_to_session_id)

        # Auto promotion
        if promote_to_id == "auto":
            for student_id in selected_students:
                student = get_object_or_404(Student, id=student_id)
                if not is_admin and student.school != school:
                    continue

                next_class = student.class_group.next_class
                if not next_class:
                    # Graduate automatically
                    student.is_graduated = True
                    student.save()
                    GraduationRecord.objects.create(
                        student=student,
                        class_group=selected_class,
                        session=promote_to_session,
                        remarks=f"Graduated from {selected_class.name} (auto promotion)."
                    )
                    StudentPromotion.objects.create(
                        student=student,
                        from_class=selected_class,
                        to_class=None,
                        status="Graduated",
                        session=promote_to_session
                    )
                    graduated_count += 1
                else:
                    with transaction.atomic():
                        new_exam_no = update_exam_no(student.exam_no, selected_class.name, next_class.name)
                        Student.objects.create(
                            base_student=student.base_student or student,
                            school=student.school,
                            surname=student.surname,
                            first_name=student.first_name,
                            middle_name=student.middle_name,
                            gender=student.gender,
                            class_group=next_class,
                            session=promote_to_session,
                            exam_no=new_exam_no,
                            parent_surname=student.parent_surname,
                            parent_first_name=student.parent_first_name,
                            parent_middle_name=student.parent_middle_name,
                            parent_email=student.parent_email,
                            parent_phone_number=student.parent_phone_number,
                            location=student.location,
                            address=student.address,
                        )
                        StudentPromotion.objects.create(
                            student=student,
                            from_class=selected_class,
                            to_class=next_class,
                            status="Promoted",
                            session=promote_to_session
                        )
                        promoted_count += 1

        # Manual promotion
        else:
            promote_to_class = get_object_or_404(ClassGroup, id=promote_to_id)
            for student_id in selected_students:
                student = get_object_or_404(Student, id=student_id)
                if not is_admin and student.school != school:
                    continue

                if StudentPromotion.objects.filter(
                    student=student,
                    session=promote_to_session,
                    status__in=["Promoted", "Graduated"]
                ).exists():
                    messages.info(request, f"{student.full_name} already processed for {promote_to_session.name}.")
                    continue

                if promote_to_class.is_graduating_class:
                    student.is_graduated = True
                    student.save()
                    GraduationRecord.objects.create(
                        student=student,
                        class_group=selected_class,
                        session=promote_to_session,
                        remarks=f"Graduated from {selected_class.name} in {promote_to_session.name}."
                    )
                    StudentPromotion.objects.create(
                        student=student,
                        from_class=selected_class,
                        to_class=None,
                        status="Graduated",
                        session=promote_to_session
                    )
                    graduated_count += 1
                else:
                    with transaction.atomic():
                        new_exam_no = update_exam_no(student.exam_no, selected_class.name, promote_to_class.name)
                        Student.objects.create(
                            base_student=student.base_student or student,
                            school=student.school,
                            surname=student.surname,
                            first_name=student.first_name,
                            middle_name=student.middle_name,
                            gender=student.gender,
                            class_group=promote_to_class,
                            session=promote_to_session,
                            exam_no=new_exam_no,
                            parent_surname=student.parent_surname,
                            parent_first_name=student.parent_first_name,
                            parent_middle_name=student.parent_middle_name,
                            parent_email=student.parent_email,
                            parent_phone_number=student.parent_phone_number,
                            location=student.location,
                            address=student.address,
                        )
                        StudentPromotion.objects.create(
                            student=student,
                            from_class=selected_class,
                            to_class=promote_to_class,
                            status="Promoted",
                            session=promote_to_session
                        )
                        promoted_count += 1

        messages.success(
            request,
            f"{promoted_count} students promoted and {graduated_count} graduated to session {promote_to_session.name}."
        )
        return redirect(f"{request.path}?class_id={selected_class_id}&session={selected_session_id}")

    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update({
            "sessions": sessions,
            "classes": classes,
            "students": students,
            "selected_class": selected_class,
            "selected_class_id": selected_class_id,
            "selected_session": selected_session,
            "selected_session_id": selected_session_id,
            "is_admin": is_admin,
            "is_teacher": not is_admin,
        })
        return render(request, "score/promote_students_teacher.html", teacher_ctx)

    return render(request, "score/promote_students.html", {
        "sessions": sessions,
        "classes": classes,
        "students": students,
        "selected_class": selected_class,
        "selected_class_id": selected_class_id,
        "selected_session": selected_session,
        "selected_session_id": selected_session_id,
        "is_admin": is_admin,
        "is_teacher": not is_admin,
        "school": school,
    })





from django.shortcuts import render
from .models import GraduationRecord, AcademicSession


@school_required
def view_graduated_students(request):
    school = request.school  # ✅ Add this line
    
    selected_session_id = request.GET.get('session')
    sessions = AcademicSession.objects.all().order_by('-name')
    
    # ✅ Filter graduates by school
    graduates = GraduationRecord.objects.filter(student__school=school)

    if selected_session_id:
        graduates = graduates.filter(session_id=selected_session_id)

    context = {
        'sessions': sessions,
        'graduates': graduates,
        'school': school,
    }
    return render(request, 'score/graduated_students.html', context)




from django.shortcuts import render, get_object_or_404, redirect
from .models import (
    ClassGroup, Student, Subject, Score,
    School, Term, AcademicSession
)

@school_required
def broadsheet(request):
    """
    Broadsheet view - Admins see all classes, Teachers see only their class
    """
    school = request.school
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    classes = context['classes']
    
    if not classes.exists():
        render_ctx = {
            "classes": [], "students": [], "subjects": [],
            "results_dict": {}, "is_admin": is_admin, "is_teacher": not is_admin,
            "school": school,
        }
        if not is_admin and context.get("class_group"):
            teacher_ctx = get_teacher_dashboard_context(context["class_group"])
            teacher_ctx.update(render_ctx)
            return render(request, "score/broadsheet_teacher.html", teacher_ctx)
        return render(request, "score/broadsheet.html", render_ctx)

    # --- Selected class ---
    if is_admin:
        selected_class_id = request.GET.get("class", classes.first().id)
        selected_class = get_object_or_404(ClassGroup, id=selected_class_id, school=school)
    else:
        selected_class = context['class_group']
    
    # --- Get students and subjects ---
    students = Student.objects.filter(
        class_group=selected_class
    ).order_by("surname", "first_name", "middle_name")
    
    subjects = Subject.objects.filter(
        class_group=selected_class
    ).order_by("name")
    
    # --- Get term and session ---
    term_name = request.GET.get("term")
    session_name = request.GET.get("session")
    
    selected_term = (
        Term.objects.filter(name=term_name).first()
        if term_name else Term.objects.first()
    )
    
    selected_session = (
        AcademicSession.objects.filter(name=session_name).first()
        if session_name else AcademicSession.objects.first()
    )
    
    results_dict = {}
    
    if selected_term and selected_session:
        scores = Score.objects.filter(
            student__in=students,
            subject__in=subjects,
            term=selected_term,
            session=selected_session
        )
        
        for score in scores:
            results_dict.setdefault(score.student_id, {})
            results_dict[score.student_id][score.subject_id] = score
    
    terms = Term.objects.values_list("name", flat=True)
    sessions = AcademicSession.objects.values_list("name", flat=True)

    render_ctx = {
        "classes": classes,
        "students": students,
        "subjects": subjects,
        "results_dict": results_dict,
        "selected_class": selected_class,
        "term": selected_term.name if selected_term else "",
        "session": selected_session.name if selected_session else "",
        "terms": terms,
        "sessions": sessions,
        "is_admin": is_admin,
        "is_teacher": not is_admin,
        "school": school,
    }
    if not is_admin and selected_class:
        teacher_ctx = get_teacher_dashboard_context(selected_class)
        teacher_ctx.update(render_ctx)
        return render(request, "score/broadsheet_teacher.html", teacher_ctx)
    return render(request, "score/broadsheet.html", render_ctx)







from django.http import HttpResponse
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect
from .models import (
    ClassGroup, Student, Subject, Score,
    School, Term, AcademicSession
)
from datetime import datetime


@school_required
def broadsheet_pdf(request):
    school = request.school  # ✅ Replaces manual checking

    # --- Selected values (same as broadsheet) ---
    class_id = request.GET.get("class")
    term_name = request.GET.get("term")
    session_name = request.GET.get("session")

    selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
    selected_term = get_object_or_404(Term, name=term_name)
    selected_session = get_object_or_404(AcademicSession, name=session_name)

    students = Student.objects.filter(
        class_group=selected_class
    ).order_by("surname", "first_name", "middle_name")

    subjects = Subject.objects.filter(
        class_group=selected_class
    ).order_by("name")

    scores = Score.objects.filter(
        student__in=students,
        subject__in=subjects,
        term=selected_term,
        session=selected_session
    )

    # Build dictionary
    results_dict = {}
    for score in scores:
        results_dict.setdefault(score.student_id, {})
        results_dict[score.student_id][score.subject_id] = score

    html_string = render_to_string(
        "score/broadsheet_pdf.html",
        {
            "school": school,
            "class_name": selected_class.name,
            "term": selected_term.name,
            "session": selected_session.name,
            "students": students,
            "subjects": subjects,
            "results_dict": results_dict,
            "date": datetime.now(),
        }
    )

    response = HttpResponse(content_type="application/pdf")
    filename = f"{selected_class.name}_{selected_term.name}_{selected_session.name}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'

    HTML(string=html_string).write_pdf(response)
    return response




# views.py
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from .models import CustomScoringSystem, ClassGroup

# views.py

from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required

@school_required  # ✅ Replace @login_required with this
def setup_custom_grading(request, class_id):
    school = request.school  # ✅ Much cleaner than manual checking

    # ✅ Verify class belongs to this school
    class_group = get_object_or_404(ClassGroup, id=class_id, school=school)

    # Check if it's actually set to custom
    if class_group.scoring_system != 'custom':
        messages.error(request, "This class is not using a Custom Grading System.")
        return redirect("dashboard")

    # Get or create the custom scoring system (empty if new)
    custom_system, created = CustomScoringSystem.objects.get_or_create(
        class_group=class_group,
        defaults={'components': {}}
    )

    SUGGESTED_TEMPLATE = {
        "CA1": 10,
        "Assignment": 10,
        "Attendance": 5,
        "Class Work": 5,
        "Project": 10,
        "Exam": 60
    }

    if request.method == 'POST':
        names = request.POST.getlist('component_name')
        weights = request.POST.getlist('component_weight')

        new_components = {}
        total = 0
        has_data = False

        for name, weight in zip(names, weights):
            name = name.strip()
            if name and weight.strip():
                try:
                    w = int(weight)
                    if w > 0:
                        new_components[name] = w
                        total += w
                        has_data = True
                except ValueError:
                    continue

        if not has_data:
            messages.error(request, "Please add at least one grading component.")
        elif total != 100:
            messages.error(request, f"Total weight must be exactly 100%. Current: {total}%")
        else:
            custom_system.components = new_components
            custom_system.save()
            messages.success(request, "Custom grading system saved successfully!")
            return redirect("dashboard")

    context = {
        'class_group': class_group,
        'custom_system': custom_system,
        'suggested_template': SUGGESTED_TEMPLATE,
        'is_first_time': not custom_system.components,
        'school': school,
    }
    return render(request, 'score/setup_custom.html', context)





import requests, string, random
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from .models import Payment, Pin

# def payments(request):
#     numbers = range(10, 1001)
#     return render(request, "score/payments.html", {"numbers": numbers})

@school_required
def payments(request):
    school = request.school
    numbers = range(10, 1001)
    return render(request, "score/payments.html", {"school": school, "numbers": numbers})



# import logging
# import requests
# import string
# import random
# from requests.exceptions import SSLError, RequestException, ConnectionError, Timeout
# from django.conf import settings

# logger = logging.getLogger(__name__)
# from django.shortcuts import render, redirect
# from django.urls import reverse
# from django.contrib import messages
# from .models import Payment, Pin   # assumes you created models for Payment & Pin

# PAYSTACK_SECRET_KEY = "sk_test_8bcafa845552a939dbb16a248280d9c144c86648"
# PAYSTACK_BASE_URL = "https://api.paystack.co"

# # TLS 1.2 adapter to avoid SSLV3_ALERT_BAD_RECORD_MAC on some Windows/Python + Paystack setups
# class _PaystackTLSAdapter(requests.adapters.HTTPAdapter):
#     def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
#         import ssl
#         ctx = ssl.create_default_context()
#         ctx.minimum_version = ssl.TLSVersion.TLSv1_2
#         kwargs["ssl_context"] = ctx
#         super().init_poolmanager(connections, maxsize, block=block, **kwargs)


# def _paystack_session():
#     session = requests.Session()
#     session.mount("https://", _PaystackTLSAdapter())
#     return session


# def _paystack_get(url, headers, timeout=30):
#     """Call Paystack GET; try TLS adapter first, then plain requests on SSL error."""
#     try:
#         return _paystack_session().get(url, headers=headers, timeout=timeout)
#     except SSLError:
#         return requests.get(url, headers=headers, timeout=timeout)


# def _paystack_post(url, headers, json_data, timeout=30):
#     """Call Paystack POST; try TLS adapter first, then plain requests on SSL error."""
#     try:
#         return _paystack_session().post(url, json=json_data, headers=headers, timeout=timeout)
#     except SSLError:
#         return requests.post(url, json=json_data, headers=headers, timeout=timeout)


@school_required
def process_payment(request):
    school = request.school  # ✅ Replaces manual checking

    if request.method == "POST":
        # Prefer manual input when provided, else use dropdown
        raw_input = (request.POST.get("num_students_input") or "").strip()
        raw_select = (request.POST.get("num_students_select") or "").strip()
        num_students = raw_input if raw_input else raw_select

        if not num_students or not num_students.isdigit():
            messages.error(request, "Please select or enter number of students.")
            return redirect("payments")

        num_students = int(num_students)
        if num_students < 1:
            messages.error(request, "Number of students must be at least 1.")
            return redirect("payments")
        amount = num_students * settings.PIN_PRICE_PER_STUDENT * 100  # Use tier-specific price (Paystack uses Kobo)

        # ✅ Save pending payment
        payment = Payment.objects.create(
            school=school,
            num_students=num_students,
            amount=amount,
            status="pending"
        )

        headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
        data = {
            "email": school.email,
            "amount": amount,
            "reference": str(payment.reference),
            "callback_url": request.build_absolute_uri(reverse("verify_payment")),
        }

        try:
            response = _paystack_post(
                f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
                headers=headers,
                json_data=data,
                timeout=30,
            )
            res_data = response.json()
        except SSLError as e:
            logger.exception("Paystack initialize: SSL error")
            messages.error(
                request,
                "Paystack connection failed (SSL). Try again or use a different network. See server console for details.",
            )
            return redirect("payments")
        except (ConnectionError, Timeout) as e:
            logger.exception("Paystack initialize: connection or timeout")
            messages.error(
                request,
                "Cannot reach Paystack. Check your internet connection and try again.",
            )
            return redirect("payments")
        except RequestException as e:
            logger.exception("Paystack initialize: request failed")
            messages.error(
                request,
                "Paystack request failed. Check your connection and try again.",
            )
            return redirect("payments")

        print("Paystack init response:", res_data)

        if res_data.get("status"):
            return redirect(res_data["data"]["authorization_url"])
        else:
            messages.error(request, "Error connecting to Paystack.")
            return redirect("payments")

    return redirect("payments")


# from django.contrib import messages
# from django.shortcuts import redirect, get_object_or_404



@school_required
def verify_payment(request):
    school = request.school  # ✅ Add this for security
    
    reference = request.GET.get("reference")

    if not reference:
        messages.error(request, "Invalid payment reference.")
        return redirect("payments")

    # ✅ Verify payment belongs to this school (before calling Paystack)
    payment = get_object_or_404(Payment, reference=reference, school=school)

    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    try:
        response = _paystack_get(
            f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=headers,
            timeout=30,
        )
        res_data = response.json()
    except SSLError:
        logger.exception("Paystack verify: SSL error")
        messages.error(
            request,
            "Payment verification failed (SSL). Try again or use a different network.",
        )
        return redirect("payments")
    except (ConnectionError, Timeout):
        logger.exception("Paystack verify: connection or timeout")
        messages.error(
            request,
            "Cannot reach Paystack. Check your internet connection and try again.",
        )
        return redirect("payments")
    except RequestException:
        logger.exception("Paystack verify: request failed")
        messages.error(
            request,
            "Payment verification failed. Check your connection and try again.",
        )
        return redirect("payments")

    if res_data.get("status") and res_data.get("data", {}).get("status") == "success":
        payment.status = "paid"
        payment.save()

        # ✅ Generate pins for this school if not already done
        if not payment.pins.exists():
            for _ in range(payment.num_students):
                pin_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
                Pin.objects.create(
                    school=payment.school,
                    payment=payment,
                    code=pin_code
                )

        messages.success(request, "Payment successful. Pins generated.")
        return redirect("publish_results")

    # ❌ If failed
    payment.status = "failed"
    payment.save()
    messages.error(request, "Payment failed or not verified.")
    return redirect("payments")
# ==================================================
# PAYSTACK HELPERS (TLS & SESSIONS)
# ==================================================

class _PaystackTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        import ssl
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)

def _paystack_session():
    session = requests.Session()
    session.mount("https://", _PaystackTLSAdapter())
    return session

def _paystack_get(url, headers, timeout=30):
    """Call Paystack GET; uses settings-based keys."""
    try:
        return _paystack_session().get(url, headers=headers, timeout=timeout)
    except SSLError:
        return requests.get(url, headers=headers, timeout=timeout)

def _paystack_post(url, headers, json_data, timeout=30):
    """Call Paystack POST; uses settings-based keys."""
    try:
        return _paystack_session().post(url, json=json_data, headers=headers, timeout=timeout)
    except SSLError:
        return requests.post(url, json=json_data, headers=headers, timeout=timeout)


# ==================================================
# CORE VIEWS
# ==================================================

@school_required
def payments(request):
    school = request.school
    numbers = range(10, 1001)
    # Pass current pin price to template for display
    pin_price = getattr(settings, 'PIN_PRICE_PER_STUDENT', 1000)
    
    # Create options with prices
    options = []
    for i in numbers:
        total = i * pin_price
        options.append({
            'value': i,
            'text': f"{i} students - ₦{total:,}",
            'total': total
        })
    
    return render(request, "score/payments.html", {
        "school": school, 
        "options": options, 
        "pin_price": pin_price
    })


@school_required
def process_payment(request):
    school = request.school

    if request.method == "POST":
        raw_input = (request.POST.get("num_students_input") or "").strip()
        raw_select = (request.POST.get("num_students_select") or "").strip()
        num_students = raw_input if raw_input else raw_select

        if not num_students or not num_students.isdigit():
            messages.error(request, "Please select or enter number of students.")
            return redirect("payments")

        num_students = int(num_students)
        if num_students < 1:
            messages.error(request, "Number of students must be at least 1.")
            return redirect("payments")

        # ✅ DYNAMIC PRICING: Pulls from basic.py (200), pro.py (500), or premium.py (1000)
        pin_price = getattr(settings, 'PIN_PRICE_PER_STUDENT', 1000)
        amount = num_students * pin_price * 100  # Amount in Kobo

        # Save pending payment
        payment = Payment.objects.create(
            school=school,
            num_students=num_students,
            amount=amount,
            status="pending"
        )

        # ✅ SETTINGS-BASED KEYS
        headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
        data = {
            "email": school.email,
            "amount": amount,
            "reference": str(payment.reference),
            "callback_url": request.build_absolute_uri(reverse("verify_payment")),
        }

        try:
            response = _paystack_post(
                f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
                headers=headers,
                json_data=data,
                timeout=30,
            )
            res_data = response.json()
        except (SSLError, ConnectionError, Timeout, RequestException):
            logger.exception("Paystack initialize failure")
            messages.error(request, "Payment gateway unreachable. Please check your connection.")
            return redirect("payments")

        if res_data.get("status"):
            return redirect(res_data["data"]["authorization_url"])
        else:
            messages.error(request, "Error connecting to Paystack.")
            return redirect("payments")

    return redirect("payments")


@school_required
def verify_payment(request):
    school = request.school
    reference = request.GET.get("reference")

    if not reference:
        messages.error(request, "Invalid payment reference.")
        return redirect("payments")

    # Verify payment belongs to this school
    payment = get_object_or_404(Payment, reference=reference, school=school)

    # ✅ SETTINGS-BASED KEYS
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    
    try:
        response = _paystack_get(
            f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=headers,
            timeout=30,
        )
        res_data = response.json()
    except (SSLError, ConnectionError, Timeout, RequestException):
        logger.exception("Paystack verification failure")
        messages.error(request, "Could not verify payment due to network error.")
        return redirect("payments")

    if res_data.get("status") and res_data.get("data", {}).get("status") == "success":
        payment.status = "paid"
        payment.save()

        # Generate pins for this school if not already done
        if not payment.pins.exists():
            for _ in range(payment.num_students):
                pin_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
                Pin.objects.create(
                    school=payment.school,
                    payment=payment,
                    code=pin_code
                )

        messages.success(request, f"Payment successful. {payment.num_students} Pins generated.")
        return redirect("publish_results")

    # If failed
    payment.status = "failed"
    payment.save()
    messages.error(request, "Payment failed or not verified.")
    return redirect("payments")

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q

from .models import (
    School,
    Student,
    ClassGroup,
    Term,
    AcademicSession,
    Payment,
    Pin,
    PublishedResult,
)


@school_required
def publish_results(request):
    school = request.school  # ✅ Replaces manual checking
    school.refresh_from_db()  # ensure payment_active is up to date (e.g. after admin change)

    terms = Term.objects.all()
    sessions = AcademicSession.objects.all()
    classes = ClassGroup.objects.filter(school=school)

    # All unused pins for this school (from any payment) — new purchases add to existing
    available_pins = Pin.objects.filter(school=school, used=False).order_by("created_at")
    available_count = available_pins.count()

    if request.method == "POST":
        term_id = request.POST.get("term")
        session_id = request.POST.get("session")
        publish_scope = request.POST.get("scope")
        selected_class_ids = request.POST.getlist("class_ids")
        student_ids = request.POST.getlist("student_ids")

        term = get_object_or_404(Term, id=term_id)
        session = get_object_or_404(AcademicSession, id=session_id)

        students_to_publish = []

        if publish_scope == "school":
            existing_school = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope="school"
            )
            if existing_school.exists():
                messages.error(request, "Results for the entire school are already published for this term/session.")
                return redirect("publish_results")

            published_classes = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope__in=["class", "school"]
            ).values_list("class_group_id", flat=True)

            unpublished_classes = classes.exclude(id__in=published_classes)
            
            if not unpublished_classes.exists():
                messages.error(request, "All classes already have published results for this term/session.")
                return redirect("publish_results")

            published_students = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope="student"
            ).values_list("student_id", flat=True)

            students_to_publish = Student.objects.filter(
                school=school, 
                class_group__in=unpublished_classes
            ).exclude(id__in=published_students)

        elif publish_scope == "class":
            if not selected_class_ids:
                messages.error(request, "Select at least one class.")
                return redirect("publish_results")

            # ✅ Verify all selected classes belong to this school
            selected_classes = ClassGroup.objects.filter(id__in=selected_class_ids, school=school)
            
            already_published_classes = PublishedResult.objects.filter(
                school=school, term=term, session=session, 
                scope__in=["class", "school"],
                class_group__in=selected_classes
            ).values_list("class_group_id", flat=True)

            if already_published_classes:
                published_class_names = selected_classes.filter(id__in=already_published_classes).values_list('name', flat=True)
                messages.error(
                    request,
                    f"Results already published for: {', '.join(published_class_names)}"
                )
                return redirect("publish_results")

            published_students = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope="student"
            ).values_list("student_id", flat=True)

            students_to_publish = Student.objects.filter(
                school=school, 
                class_group__in=selected_classes
            ).exclude(id__in=published_students)

        elif publish_scope == "student":
            if not student_ids:
                messages.error(request, "Select at least one student.")
                return redirect("publish_results")
            
            already_published = PublishedResult.objects.filter(
                school=school,
                term=term,
                session=session,
                student_id__in=student_ids
            ).values_list("student_id", flat=True)

            if already_published:
                already_published_names = Student.objects.filter(
                    id__in=already_published
                ).values_list('full_name', flat=True)
                messages.error(
                    request,
                    f"Results already published for: {', '.join(already_published_names)}"
                )
                return redirect("publish_results")

            # ✅ Verify all selected students belong to this school
            students_to_publish = Student.objects.filter(id__in=student_ids, school=school)

        else:
            messages.error(request, "Invalid publish scope.")
            return redirect("publish_results")

        total_students = students_to_publish.count()

        if total_students == 0:
            messages.warning(request, "No students available to publish (all already published).")
            return redirect("publish_results")

        # When payment is not activated for this school, no pins required
        if school.payment_active and total_students > available_count:
            messages.error(request, f"Not enough unused pins. Need: {total_students}, Available: {available_count}")
            return redirect("publish_results")

        # Bulk publish
        with transaction.atomic():
            if school.payment_active:
                pins_to_use = list(available_pins[:total_students])
                for student_obj, pin in zip(students_to_publish, pins_to_use):
                    pin.used = True
                    pin.used_at = timezone.now()
                    pin.student = student_obj
                    pin.term = term
                    pin.session = session
                    pin.save()

            for student_obj in students_to_publish:
                if publish_scope == "school":
                    PublishedResult.objects.get_or_create(
                        school=school,
                        term=term,
                        session=session,
                        scope="school",
                        class_group=student_obj.class_group,
                        student=student_obj
                    )
                elif publish_scope == "class":
                    PublishedResult.objects.get_or_create(
                        school=school,
                        term=term,
                        session=session,
                        scope="class",
                        class_group=student_obj.class_group,
                        student=student_obj
                    )
                else:
                    PublishedResult.objects.get_or_create(
                        school=school,
                        term=term,
                        session=session,
                        scope="student",
                        class_group=student_obj.class_group,
                        student=student_obj
                    )

        if school.payment_active:
            messages.success(request, f"{total_students} results published successfully using {total_students} pins.")
        else:
            messages.success(request, f"{total_students} results published successfully. (Payment not required for your school.)")
        return redirect("dashboard")

    context = {
        "school": school,
        "terms": terms,
        "sessions": sessions,
        "classes": classes,
        "available_count": available_count,
        "payment_active": school.payment_active,
    }

    return render(request, "score/publish_results.html", context)




from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import School, ClassGroup, Term, AcademicSession, PublishedResult


@school_required
def check_published_students(request):
    """API endpoint to check which students already have published results"""
    school = request.school  # ✅ Replaces manual checking
    
    term_id = request.GET.get("term")
    session_id = request.GET.get("session")
    class_id = request.GET.get("class")
    
    if not all([term_id, session_id, class_id]):
        return JsonResponse({"error": "Missing parameters"}, status=400)
    
    try:
        term = Term.objects.get(id=term_id)
        session = AcademicSession.objects.get(id=session_id)
        # ✅ Verify class belongs to this school
        class_group = ClassGroup.objects.get(id=class_id, school=school)
    except (Term.DoesNotExist, AcademicSession.DoesNotExist, ClassGroup.DoesNotExist):
        return JsonResponse({"error": "Invalid parameters"}, status=400)
    
    student_ids = list(PublishedResult.objects.filter(
        school=school,
        term=term,
        session=session,
        student__class_group=class_group
    ).values_list("student_id", flat=True).distinct())
    
    return JsonResponse({
        "published_student_ids": student_ids
    })





from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.template.loader import render_to_string
from io import BytesIO
from .models import Payment, School

@school_required
def invoices(request):
    school = request.school  # ✅ Replaces manual checking
    
    payments = Payment.objects.filter(school=school).order_by("-created_at")

    return render(request, "score/invoices.html", {"payments": payments, "school": school})





@school_required
def download_receipt(request, reference):
    school = request.school  # ✅ Replaces manual checking
    
    # ✅ Verify payment belongs to this school
    payment = get_object_or_404(Payment, reference=reference, school=school)

    # If user wants to preview in browser (HTML mode)
    if request.GET.get("format") == "html":
        return render(request, "score/receipt.html", {"payment": payment, "school": school})

    # PDF mode
    template_path = "score/receipt.html"
    html = render_to_string(template_path, {"payment": payment, "school": school})

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="receipt_{reference}.pdf"'

    try:
        from xhtml2pdf import pisa
    except Exception as e:
        logger.exception("xhtml2pdf import failed: %s", e)
        return HttpResponse("PDF generation dependency missing on server.", status=500)

    pisa_status = pisa.CreatePDF(BytesIO(html.encode("utf-8")), dest=response, link_callback=fetch_resources)

    if pisa_status.err:
        return HttpResponse("Error generating PDF", status=500)

    return response










# Add these views to your existing score app views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from io import BytesIO
import base64

try:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
except ImportError:
    pass

from .models import (
    Exam, Question, CBTResult, QuestionResponse,
    Student, ClassGroup, AcademicSession, Term, School, Subject
)

from django.utils import timezone
from django.db.models import Q, Avg, Count
from io import BytesIO
import base64
try:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
except ImportError:
    pass



# ------------------------------------------
# STUDENT CBT EXAM LOGIN
# ------------------------------------------
def cbt_login(request):
    """
    Student login for CBT exam using exam number and exam code
    """
    error = None

    if request.method == 'POST':
        exam_code = request.POST.get('exam_code', '').strip().upper()
        exam_no = request.POST.get('exam_no', '').strip()
        session_id = request.POST.get('session')
        term_id = request.POST.get('term')
        class_id = request.POST.get('class_group')

        try:
            # Validate exam exists and is active
            exam = Exam.objects.select_related(
                'school', 'class_group', 'subject', 'session', 'term'
            ).get(exam_code=exam_code, is_active=True)
            
            # Validate student exists with matching details
            student = Student.objects.select_related(
                'school', 'class_group', 'session'
            ).get(
                exam_no=exam_no,
                school=exam.school,
                class_group_id=class_id,
                session_id=session_id,
                is_active=True
            )
            
            # Validate exam matches student's context
            if exam.session_id != int(session_id):
                error = 'This exam is for a different academic session'
            elif exam.term_id != int(term_id):
                error = 'This exam is for a different term'
            elif exam.class_group_id != int(class_id):
                error = 'This exam is not available for your class'
            elif not exam.is_published:
                error = 'This exam has not been published yet'
            else:
                # Check if student already took this exam
                existing_result = CBTResult.objects.filter(
                    student=student,
                    exam=exam
                ).first()
                
                if existing_result:
                    error = 'You have already taken this exam. Check your results below.'
                else:
                    # Store session data
                    request.session['cbt_student_id'] = student.id
                    request.session['cbt_exam_id'] = exam.id
                    request.session['cbt_start_time'] = timezone.now().isoformat()
                    
                    return redirect('take_cbt_exam', exam_id=exam.id)
                    
        except Exam.DoesNotExist:
            error = 'Invalid exam code or exam not available'
        except Student.DoesNotExist:
            error = 'Invalid exam number or student details not found'
        except Exception as e:
            error = f'An error occurred: {str(e)}'
    
    # Get filter options
    sessions = AcademicSession.objects.all().order_by('-name')
    terms = Term.objects.all()
    classes = ClassGroup.objects.all().order_by('name')
    
    context = {
        'error': error,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
    }
    
    return render(request, 'score/cbt_login.html', context)


# ------------------------------------------
# TAKE CBT EXAM
# ------------------------------------------
def take_cbt_exam(request, exam_id):
    """
    Display and process CBT exam
    """
    exam = get_object_or_404(
        Exam.objects.select_related(
            'school', 'class_group', 'subject', 'session', 'term'
        ),
        id=exam_id,
        is_active=True
    )
    
    # Verify student is logged in
    student_id = request.session.get('cbt_student_id')
    if not student_id:
        messages.error(request, 'Please log in to take the exam')
        return redirect('cbt_login')
    
    try:
        student = Student.objects.select_related(
            'school', 'class_group', 'session'
        ).get(id=student_id, is_active=True)
    except Student.DoesNotExist:
        messages.error(request, 'Invalid session. Please log in again.')
        request.session.flush()
        return redirect('cbt_login')
    
    # Verify student hasn't already taken this exam
    existing_result = CBTResult.objects.filter(
        student=student,
        exam=exam
    ).first()
    
    if existing_result:
        messages.warning(request, 'You have already completed this exam')
        return redirect('view_cbt_result', result_id=existing_result.id)
    
    questions = exam.cbt_questions.all()
    
    if not questions.exists():
        messages.error(request, 'This exam has no questions yet')
        return redirect('cbt_login')
    
    duration_seconds = exam.duration_minutes * 60
    
    if request.method != 'POST':
        # Display exam page
        return render(request, 'score/take_cbt_exam_clean.html', {
            'exam': exam,
            'student': student,
            'question_data': [{
                'id': q.id,
                'question': q.question_text,
                'image': q.image,
                'options': [(chr(65+i), opt) for i, opt in enumerate(q.options())],
                'plain_options': q.options(),
                'order': q.order,
            } for q in questions],
            'duration_seconds': duration_seconds,
            'total_questions': questions.count(),
        })
    
    # --------------------------
    # PROCESS EXAM SUBMISSION
    # --------------------------
    score = 0
    total_marks = 0
    detail_rows = []
    
    # Calculate time taken
    start_time_str = request.session.get('cbt_start_time')
    time_taken_minutes = 0
    if start_time_str:
        from django.utils.dateparse import parse_datetime
        start_time = parse_datetime(start_time_str)
        if start_time:
            time_taken = timezone.now() - start_time
            time_taken_minutes = int(time_taken.total_seconds() / 60)
    
    for q in questions:
        user_answer = request.POST.get(str(q.id))
        plain_options = q.options()
        
        # Convert clicked text into A/B/C/D
        user_key = None
        if user_answer in plain_options:
            user_key = chr(65 + plain_options.index(user_answer))
        
        is_correct = (user_key == q.correct_answer)
        
        if is_correct:
            score += q.marks
        
        total_marks += q.marks
        
        # Get correct option text
        correct_index = ord(q.correct_answer) - 65 if q.correct_answer else None
        correct_option_text = ''
        if correct_index is not None and 0 <= correct_index < len(plain_options):
            correct_option_text = f"{q.correct_answer}. {plain_options[correct_index]}"
        
        detail_rows.append({
            'question_id': q.id,
            'question': q.question_text,
            'image': q.image,
            'options': [(chr(65+i), opt) for i, opt in enumerate(plain_options)],
            'plain_options': plain_options,
            'your_answer': user_answer or 'No answer',
            'your_answer_key': user_key,
            'correct_answer': q.correct_answer,
            'correct_option_text': correct_option_text,
            'is_correct': is_correct,
            'explanation': q.explanation,
            'marks': q.marks,
        })
    
    # --------------------------
    # SAVE RESULT
    # --------------------------
    result = CBTResult.objects.create(
        student=student,
        exam=exam,
        score=score,
        total=total_marks,
        time_taken_minutes=time_taken_minutes,
        submitted_at=timezone.now()
    )
    
    # Save individual responses (optional but useful for analysis)
    for detail in detail_rows:
        if detail['your_answer_key']:
            QuestionResponse.objects.create(
                result=result,
                question_id=detail['question_id'],
                selected_answer=detail['your_answer_key'],
                is_correct=detail['is_correct']
            )
    
    # --------------------------
    # GENERATE PIE CHART
    # --------------------------
    correct_percentage = round((score / total_marks) * 100) if total_marks > 0 else 0
    wrong_percentage = 100 - correct_percentage
    
    fig, ax = plt.subplots(figsize=(5, 5))
    colors = ['#10b981', '#ef4444']
    explode = (0.05, 0)
    
    ax.pie(
        [score, total_marks - score],
        labels=[f"{correct_percentage}% Correct ({score}/{total_marks})", 
                f"{wrong_percentage}% Wrong ({total_marks - score}/{total_marks})"],
        colors=colors,
        explode=explode,
        startangle=90,
        autopct='%1.0f%%',
        textprops={'fontsize': 11, 'weight': 'bold'}
    )
    ax.axis('equal')
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', dpi=100)
    buffer.seek(0)
    chart_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    buffer.close()
    plt.close(fig)
    
    # Clear session
    request.session.pop('cbt_student_id', None)
    request.session.pop('cbt_exam_id', None)
    request.session.pop('cbt_start_time', None)
    
    # --------------------------
    # RENDER RESULT PAGE
    # --------------------------
    return render(request, 'score/cbt_result.html', {
        'exam': exam,
        'student': student,
        'score': score,
        'total': total_marks,
        'question_results': detail_rows,
        'chart_base64': chart_base64,
        'correct_percentage': correct_percentage,
        'wrong_percentage': wrong_percentage,
        'result': result,
        'time_taken': time_taken_minutes,
        'passed': result.passed,
    })


# ------------------------------------------
# VIEW CBT RESULT
# ------------------------------------------
def view_cbt_result(request, result_id):
    """
    View individual CBT exam result
    """
    result = get_object_or_404(
        CBTResult.objects.select_related(
            'student', 'exam', 'exam__subject', 'exam__class_group'
        ),
        id=result_id
    )
    
    # Get all questions for the exam and map responses
    questions = Question.objects.filter(exam=result.exam).order_by('order', 'id')
    responses_map = {r.question_id: r for r in result.responses.select_related('question').all()}
    
    responses_data = []
    for q in questions:
        plain_opts = q.options()
        response = responses_map.get(q.id)
        responses_data.append({
            'response': response,
            'question': q,
            'options': [(chr(65+i), opt) for i, opt in enumerate(plain_opts)]
        })
    
    # Generate chart
    correct_percentage = round(result.percentage)
    wrong_percentage = 100 - correct_percentage
    
    fig, ax = plt.subplots(figsize=(5, 5))
    colors = ['#10b981', '#ef4444']
    explode = (0.05, 0)
    
    ax.pie(
        [result.score, result.total - result.score],
        labels=[f"{correct_percentage}% Correct", f"{wrong_percentage}% Wrong"],
        colors=colors,
        explode=explode,
        startangle=90,
        autopct='%1.0f%%',
        textprops={'fontsize': 11, 'weight': 'bold'}
    )
    ax.axis('equal')
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', dpi=100)
    buffer.seek(0)
    chart_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    buffer.close()
    plt.close(fig)
    
    context = {
        'school': result.exam.school,
        'result': result,
        'responses_data': responses_data,
        'chart_base64': chart_base64,
        'correct_percentage': correct_percentage,
        'wrong_percentage': wrong_percentage,
    }
    
    return render(request, 'score/view_cbt_result.html', context)


@school_required  # ✅ CHANGED FROM @login_required
def cbt_dashboard(request):
    """Dashboard for managing CBT exams - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard."""
    school = request.school  # ✅ Available from decorator
    
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        class_group = user_ctx['class_group']
        context = get_teacher_dashboard_context(class_group)
        context['base_template'] = 'score/teacher_dashboard.html'
        exam_qs = Exam.objects.filter(school=school, class_group=class_group)
    else:
        context = {}
        exam_qs = Exam.objects.filter(school=school)
    
    exams = exam_qs.select_related(
        'subject', 'class_group', 'session', 'term'
    ).order_by('-created_at')[:10]
    
    # Statistics (class-scoped for teachers)
    total_exams = exam_qs.count()
    total_attempts = CBTResult.objects.filter(exam__in=exam_qs).count()
    active_exams = exam_qs.filter(is_active=True, is_published=True).count()
    
    context.update({
        'school': school,
        'exams': exams,
        'total_exams': total_exams,
        'total_attempts': total_attempts,
        'active_exams': active_exams,
    })
    return render(request, 'score/cbt_dashboard.html', context)

@school_required  # ✅ CHANGED FROM @login_required
def cbt_exam_list(request):
    """List all CBT exams with filtering - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard."""
    school = request.school  # ✅ Available from decorator
    
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        class_group = user_ctx['class_group']
        context = get_teacher_dashboard_context(class_group)
        context['base_template'] = 'score/teacher_dashboard.html'
        exams = Exam.objects.filter(school=school, class_group=class_group).select_related(
            'subject', 'class_group', 'session', 'term'
        )
        sessions = AcademicSession.objects.all().order_by('-name')
        terms = Term.objects.all()
        classes = ClassGroup.objects.filter(id=class_group.id).order_by('name')
        subjects = Subject.objects.filter(class_group=class_group).order_by('name')
    else:
        context = {}
        exams = Exam.objects.filter(school=school).select_related(
            'subject', 'class_group', 'session', 'term'
        )
        sessions = AcademicSession.objects.all().order_by('-name')
        terms = Term.objects.all()
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        subjects = Subject.objects.filter(class_group__school=school).distinct()
    
    # Apply filters
    session_id = request.GET.get('session')
    term_id = request.GET.get('term')
    class_id = request.GET.get('class')
    subject_id = request.GET.get('subject')
    
    if session_id:
        exams = exams.filter(session_id=session_id)
    if term_id:
        exams = exams.filter(term_id=term_id)
    if class_id:
        exams = exams.filter(class_group_id=class_id)
    if subject_id:
        exams = exams.filter(subject_id=subject_id)
    
    exams = exams.order_by('-created_at')
    
    context.update({
        'exams': exams,
        'school': school,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
        'subjects': subjects,
        'selected_session': session_id,
        'selected_term': term_id,
        'selected_class': class_id,
        'selected_subject': subject_id,
    })
    
    return render(request, 'score/cbt_exam_list.html', context)




@school_required  # ✅ CHANGED FROM @login_required
def cbt_results_list(request):
    """Display all CBT results with filtering - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard."""
    school = request.school  # ✅ Available from decorator
    
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        class_group = user_ctx['class_group']
        context = get_teacher_dashboard_context(class_group)
        context['base_template'] = 'score/teacher_dashboard.html'
        results_base = CBTResult.objects.filter(
            exam__school=school, exam__class_group=class_group
        ).select_related(
            'student', 'exam', 'exam__subject', 'exam__session', 'exam__term'
        )
        sessions = AcademicSession.objects.all().order_by('-name')
        terms = Term.objects.all()
        classes = ClassGroup.objects.filter(id=class_group.id).order_by('name')
        subjects = Subject.objects.filter(class_group=class_group).distinct()
        exams = Exam.objects.filter(school=school, class_group=class_group).order_by('-created_at')
    else:
        context = {}
        results_base = CBTResult.objects.filter(
            exam__school=school
        ).select_related(
            'student', 'exam', 'exam__subject', 'exam__session', 'exam__term'
        )
        sessions = AcademicSession.objects.all().order_by('-name')
        terms = Term.objects.all()
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        subjects = Subject.objects.filter(class_group__school=school).distinct()
        exams = Exam.objects.filter(school=school).order_by('-created_at')
    
    # Get filter parameters
    session_id = request.GET.get('session', '')
    term_id = request.GET.get('term', '')
    class_id = request.GET.get('class', '')
    subject_id = request.GET.get('subject', '')
    exam_id = request.GET.get('exam', '')
    search_name = request.GET.get('search', '').strip()
    
    results = results_base
    if session_id:
        results = results.filter(exam__session_id=session_id)
    if term_id:
        results = results.filter(exam__term_id=term_id)
    if class_id:
        results = results.filter(student__class_group_id=class_id)
    if subject_id:
        results = results.filter(exam__subject_id=subject_id)
    if exam_id:
        results = results.filter(exam_id=exam_id)
    if search_name:
        results = results.filter(
            Q(student__surname__icontains=search_name) |
            Q(student__first_name__icontains=search_name) |
            Q(student__exam_no__icontains=search_name)
        )
    
    results = results.order_by('-submitted_at')
    
    # Calculate stats
    total_results = results.count()
    passed_count = sum(1 for r in results if r.passed)
    failed_count = total_results - passed_count
    average_score = round(sum(r.percentage for r in results) / total_results, 1) if total_results > 0 else 0
    
    context.update({
        'results': results,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
        'subjects': subjects,
        'exams': exams,
        'selected_session': session_id,
        'selected_term': term_id,
        'selected_class': class_id,
        'selected_subject': subject_id,
        'selected_exam': exam_id,
        'search_name': search_name,
        'school': school,
        'total_results': total_results,
        'passed_count': passed_count,
        'failed_count': failed_count,
        'average_score': average_score,
    })
    
    return render(request, 'score/cbt_results_list.html', context)



@school_required  # ✅ CHANGED FROM @login_required
def create_cbt_exam(request):
    """Create new CBT exam - SCHOOL SPECIFIC"""
    school = request.school  # ✅ Available from decorator

    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        class_group_id = request.POST.get('class_group')
        subject_id = request.POST.get('subject')
        session_id = request.POST.get('session')
        term_id = request.POST.get('term')
        duration_minutes = int(request.POST.get('duration_minutes', 60))
        pass_mark = int(request.POST.get('pass_mark', 50))
        is_published = request.POST.get('is_published') == 'on'

        # Check for duplicates
        if Exam.objects.filter(
            school=school,
            class_group_id=class_group_id,
            subject_id=subject_id,
            session_id=session_id,
            term_id=term_id,
            title=title
        ).exists():
            messages.error(
                request,
                'An exam with this title already exists for this class, subject, term and session.'
            )
            return redirect('create_cbt_exam')

        exam = Exam.objects.create(
            school=school,
            class_group_id=class_group_id,
            subject_id=subject_id,
            session_id=session_id,
            term_id=term_id,
            title=title,
            description=description,
            duration_minutes=duration_minutes,
            pass_mark=pass_mark,
            is_published=is_published,
            is_active=True
        )

        messages.success(
            request,
            f'Exam "{exam.title}" created successfully! Code: {exam.exam_code}'
        )
        return redirect('create_cbt_question', exam_id=exam.id)

    # GET request
    sessions = AcademicSession.objects.all().order_by('-name')
    terms = Term.objects.all()
    classes = ClassGroup.objects.filter(school=school).order_by('name')
    subjects = Subject.objects.filter(class_group__school=school).order_by('name')

    return render(request, 'score/create_cbt_exam.html', {
        'school': school,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
        'subjects': subjects,
    })


@school_required
def create_cbt_exam(request):
    """
    Create CBT exam - Teachers create for their class only, Admins can select
    """
    school = request.school
    from .models import Exam
    
    context = get_user_context(request)
    if not context:
        messages.error(request, "Access denied.")
        return redirect("unified_login")
    
    is_admin = context['is_admin']
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        class_group_id = request.POST.get('class_group')
        subject_id = request.POST.get('subject')
        session_id = request.POST.get('session')
        term_id = request.POST.get('term')
        duration_minutes = int(request.POST.get('duration_minutes', 60))
        pass_mark = int(request.POST.get('pass_mark', 50))
        is_published = request.POST.get('is_published') == 'on'
        
        # Verify class access
        if not is_admin:
            if int(class_group_id) != context['class_group'].id:
                messages.error(request, "You can only create exams for your assigned class.")
                return redirect('create_cbt_exam')
        
        # Check for duplicates
        if Exam.objects.filter(
            school=school,
            class_group_id=class_group_id,
            subject_id=subject_id,
            session_id=session_id,
            term_id=term_id,
            title=title
        ).exists():
            messages.error(request, 'An exam with this title already exists for this class, subject, term and session.')
            return redirect('create_cbt_exam')
        
        exam = Exam.objects.create(
            school=school,
            class_group_id=class_group_id,
            subject_id=subject_id,
            session_id=session_id,
            term_id=term_id,
            title=title,
            description=description,
            duration_minutes=duration_minutes,
            pass_mark=pass_mark,
            is_published=is_published,
            is_active=True
        )
        
        messages.success(request, f'Exam "{exam.title}" created successfully! Code: {exam.exam_code}')
        return redirect('create_cbt_question', exam_id=exam.id)
    
    # GET request - prepare form
    sessions = AcademicSession.objects.all().order_by('-name')
    terms = Term.objects.all()
    
    if is_admin:
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        subjects = Subject.objects.filter(class_group__school=school).order_by('name')
    else:
        class_group = context['class_group']
        classes = ClassGroup.objects.filter(id=class_group.id)
        subjects = Subject.objects.filter(class_group=class_group).order_by('name')
    
    render_ctx = {
        'school': school,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
        'subjects': subjects,
        'is_admin': is_admin,
        'is_teacher': not is_admin,
    }
    if not is_admin and context.get('class_group'):
        teacher_ctx = get_teacher_dashboard_context(context['class_group'])
        teacher_ctx.update(render_ctx)
        teacher_ctx['base_template'] = 'score/teacher_dashboard.html'
        return render(request, 'score/create_cbt_exam.html', teacher_ctx)
    return render(request, 'score/create_cbt_exam.html', render_ctx)


@school_required  # ✅ CHANGED FROM @login_required
def create_cbt_question(request, exam_id):
    """Create question for specific exam - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard."""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Exam is not for your class.")
    
    if request.method == 'POST':
        question_text = request.POST.get('question_text')
        option_a = request.POST.get('option_a')
        option_b = request.POST.get('option_b')
        option_c = request.POST.get('option_c')
        option_d = request.POST.get('option_d')
        correct_answer = request.POST.get('correct_answer')
        explanation = request.POST.get('explanation', '')
        marks = request.POST.get('marks', 1)
        order = request.POST.get('order', 0)
        image = request.FILES.get('image')
        
        Question.objects.create(
            exam=exam,
            question_text=question_text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=option_d,
            correct_answer=correct_answer,
            explanation=explanation,
            marks=int(marks),
            order=int(order),
            image=image
        )
        
        if 'save_and_add' in request.POST:
            messages.success(request, 'Question added successfully! You can now add another.')
            return redirect('create_cbt_question', exam_id=exam_id)
        else:
            messages.success(request, 'Question added successfully!')
            return redirect('cbt_question_list', exam_id=exam_id)
    
    if user_ctx and user_ctx.get('is_teacher'):
        context = get_teacher_dashboard_context(user_ctx['class_group'])
        context['base_template'] = 'score/teacher_dashboard.html'
    else:
        context = {}
    context['exam'] = exam
    context['school'] = school
    context['next_order'] = exam.cbt_questions.count() + 1
    
    return render(request, 'score/create_cbt_question.html', context)




@school_required  # ✅ CHANGED FROM @login_required
def cbt_question_list(request, exam_id):
    """List questions for specific exam - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard; exam must be for their class."""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Exam is not for your class.")
        context = get_teacher_dashboard_context(user_ctx['class_group'])
        context['base_template'] = 'score/teacher_dashboard.html'
    else:
        context = {}
    questions = exam.cbt_questions.all().order_by('order', 'id')
    context['exam'] = exam
    context['questions'] = questions
    context['school'] = school
    
    return render(request, 'score/cbt_question_list.html', context)










# Add these optional views to your score app views.py
# These handle edit, delete, and export operations

from django.http import HttpResponse, JsonResponse
from django.db.models import Avg, Count
import csv



@school_required  # ✅ CHANGED FROM @login_required
def edit_cbt_exam(request, exam_id):
    """Edit existing exam - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard; exam must be for their class."""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Exam is not for your class.")
    
    if request.method == 'POST':
        exam.title = request.POST.get('title')
        exam.description = request.POST.get('description')
        if user_ctx and user_ctx.get('is_teacher'):
            # Teachers cannot change class
            pass
        else:
            exam.class_group_id = request.POST.get('class_group')
        exam.subject_id = request.POST.get('subject')
        exam.session_id = request.POST.get('session')
        exam.term_id = request.POST.get('term')
        exam.duration_minutes = int(request.POST.get('duration_minutes', 60))
        exam.pass_mark = int(request.POST.get('pass_mark', 50))
        exam.is_published = request.POST.get('is_published') == 'on'
        exam.save()
        
        messages.success(request, f'Exam "{exam.title}" updated successfully!')
        return redirect('cbt_exam_list')
    
    sessions = AcademicSession.objects.all().order_by('-name')
    terms = Term.objects.all()
    if user_ctx and user_ctx.get('is_teacher'):
        classes = ClassGroup.objects.filter(id=user_ctx['class_group'].id).order_by('name')
        subjects = Subject.objects.filter(class_group=user_ctx['class_group']).order_by('name')
    else:
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        subjects = Subject.objects.filter(class_group__school=school).order_by('name')
    
    if user_ctx and user_ctx.get('is_teacher'):
        context = get_teacher_dashboard_context(user_ctx['class_group'])
        context['base_template'] = 'score/teacher_dashboard.html'
    else:
        context = {}
    context.update({
        'exam': exam,
        'school': school,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
        'subjects': subjects,
    })
    
    return render(request, 'score/edit_cbt_exam.html', context)


@school_required  # ✅ CHANGED FROM @login_required
def delete_cbt_exam(request, exam_id):
    """Delete exam - SCHOOL SPECIFIC. Teachers see confirm page inside teacher_dashboard; exam must be for their class."""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Exam is not for your class.")
    
    if request.method == 'POST':
        exam_title = exam.title
        exam.delete()
        messages.success(request, f'Exam "{exam_title}" deleted successfully!')
        return redirect('cbt_exam_list')
    
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        context = get_teacher_dashboard_context(user_ctx['class_group'])
        context['base_template'] = 'score/teacher_dashboard.html'
    else:
        context = {}
    context['exam'] = exam
    context['school'] = school
    return render(request, 'score/confirm_delete_exam.html', context)


@school_required  # ✅ CHANGED FROM @login_required
def toggle_exam_status(request, exam_id):
    """Toggle exam published/active status - SCHOOL SPECIFIC. Teachers can only toggle exams for their class."""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if exam.class_group_id != user_ctx['class_group'].id:
            return JsonResponse({'error': 'Exam is not for your class.'}, status=403)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle_published':
            exam.is_published = not exam.is_published
        elif action == 'toggle_active':
            exam.is_active = not exam.is_active
        exam.save()
        
        return JsonResponse({
            'success': True,
            'is_published': exam.is_published,
            'is_active': exam.is_active
        })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)


@school_required  # ✅ CHANGED FROM @login_required
def edit_cbt_question(request, question_id):
    """Edit existing question - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard."""
    school = request.school  # ✅ Available from decorator
    
    question = get_object_or_404(
        Question.objects.select_related('exam'),
        id=question_id,
        exam__school=school
    )
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if question.exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Question's exam is not for your class.")
    
    if request.method == 'POST':
        question.question_text = request.POST.get('question_text')
        question.option_a = request.POST.get('option_a')
        question.option_b = request.POST.get('option_b')
        question.option_c = request.POST.get('option_c')
        question.option_d = request.POST.get('option_d')
        question.correct_answer = request.POST.get('correct_answer')
        question.explanation = request.POST.get('explanation', '')
        question.marks = int(request.POST.get('marks', 1))
        question.order = int(request.POST.get('order', 0))
        
        if 'image' in request.FILES:
            question.image = request.FILES['image']
        
        question.save()
        
        messages.success(request, 'Question updated successfully!')
        return redirect('cbt_question_list', exam_id=question.exam.id)
    
    if user_ctx and user_ctx.get('is_teacher'):
        context = get_teacher_dashboard_context(user_ctx['class_group'])
        context['base_template'] = 'score/teacher_dashboard.html'
    else:
        context = {}
    context['question'] = question
    context['exam'] = question.exam
    context['school'] = school
    
    return render(request, 'score/edit_cbt_question.html', context)


@school_required  # ✅ CHANGED FROM @login_required
def delete_cbt_question(request, question_id):
    """Delete question - SCHOOL SPECIFIC. Teachers can only delete questions for their class's exams."""
    school = request.school  # ✅ Available from decorator
    
    question = get_object_or_404(
        Question.objects.select_related('exam'),
        id=question_id,
        exam__school=school
    )
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if question.exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Question's exam is not for your class.")
    
    if request.method == 'POST':
        exam_id = question.exam.id
        question.delete()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        
        messages.success(request, 'Question deleted successfully!')
        return redirect('cbt_question_list', exam_id=exam_id)
    
    return JsonResponse({'error': 'Invalid request'}, status=400)


@school_required  # ✅ CHANGED FROM @login_required
def exam_results_detail(request, exam_id):
    """Detailed results for specific exam - SCHOOL SPECIFIC. Teachers see it inside teacher_dashboard; exam must be for their class."""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    user_ctx = get_user_context(request)
    if user_ctx and user_ctx.get('is_teacher'):
        if exam.class_group_id != user_ctx['class_group'].id:
            raise Http404("Exam is not for your class.")
    results = CBTResult.objects.filter(exam=exam).select_related('student')
    
    # Calculate statistics
    stats = {
        'total_attempts': results.count(),
        'average_score': results.aggregate(Avg('percentage'))['percentage__avg'] or 0,
        'pass_rate': (results.filter(percentage__gte=exam.pass_mark).count() / results.count() * 100) if results.count() > 0 else 0,
        'highest_score': results.order_by('-percentage').first(),
        'lowest_score': results.order_by('percentage').first(),
    }
    
    if user_ctx and user_ctx.get('is_teacher'):
        context = get_teacher_dashboard_context(user_ctx['class_group'])
        context['base_template'] = 'score/teacher_dashboard.html'
    else:
        context = {}
    context.update({
        'exam': exam,
        'results': results,
        'stats': stats,
        'school': school,
    })
    
    return render(request, 'score/exam_results_detail.html', context)


@school_required  # ✅ CHANGED FROM @login_required
def export_cbt_results(request):
    """Export CBT results to CSV with mandatory filters.

    Admin: class + session + term
    Teacher: session + term (class is fixed to teacher class)
    """
    school = request.school  # ✅ Available from decorator
    
    user_ctx = get_user_context(request)
    is_teacher = bool(user_ctx and user_ctx.get('is_teacher'))

    sessions = AcademicSession.objects.all().order_by('-name')
    terms = Term.objects.all()

    selected_session = request.GET.get('session', '').strip()
    selected_term = request.GET.get('term', '').strip()
    selected_class = request.GET.get('class', '').strip()

    if is_teacher:
        class_group = user_ctx['class_group']
        classes = ClassGroup.objects.filter(id=class_group.id)
        base_template = 'score/teacher_dashboard.html'
    else:
        class_group = None
        classes = ClassGroup.objects.filter(school=school).order_by('name')
        base_template = 'score/dashboard.html'

    context = {
        'school': school,
        'sessions': sessions,
        'terms': terms,
        'classes': classes,
        'selected_session': selected_session,
        'selected_term': selected_term,
        'selected_class': selected_class,
        'is_teacher': is_teacher,
        'teacher_class_group': class_group,
        'class_group': class_group,
        'base_template': base_template,
    }

    required_missing = not selected_session or not selected_term or (not is_teacher and not selected_class)
    if required_missing:
        return render(request, 'score/export_cbt_results_form.html', context)

    if user_ctx and user_ctx.get('is_teacher'):
        class_group = user_ctx['class_group']
        results_base = CBTResult.objects.filter(
            exam__school=school, exam__class_group=class_group
        ).select_related(
            'student', 'exam', 'exam__subject', 'exam__session', 'exam__term'
        )
    else:
        results_base = CBTResult.objects.filter(exam__school=school).select_related(
            'student', 'exam', 'exam__subject', 'exam__session', 'exam__term'
        )
    
    results = results_base
    results = results.filter(exam__session_id=selected_session, exam__term_id=selected_term)
    if is_teacher:
        results = results.filter(exam__class_group=class_group)
    else:
        results = results.filter(exam__class_group_id=selected_class)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="cbt_results_{school.name}_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Student Name',
        'Exam Number',
        'Class',
        'Exam Title',
        'Subject',
        'Session',
        'Term',
        'Score',
        'Total',
        'Percentage',
        'Grade',
        'Status',
        'Time Taken (min)',
        'Submitted At'
    ])
    
    for result in results:
        writer.writerow([
            result.student.full_name,
            result.student.exam_no,
            result.student.class_group.name,
            result.exam.title,
            result.exam.subject.name,
            result.exam.session.name,
            result.exam.term.name,
            result.score,
            result.total,
            f"{result.percentage:.2f}",
            result.grade,
            'Passed' if result.passed else 'Failed',
            result.time_taken_minutes,
            result.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    return response


@school_required  # ✅ CHANGED FROM @login_required
def bulk_import_questions(request, exam_id):
    """Bulk import questions from CSV - SCHOOL SPECIFIC"""
    school = request.school  # ✅ Available from decorator
    
    exam = get_object_or_404(Exam, id=exam_id, school=school)
    
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        try:
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            
            questions_created = 0
            for row in reader:
                Question.objects.create(
                    exam=exam,
                    question_text=row['question'],
                    option_a=row['option_a'],
                    option_b=row['option_b'],
                    option_c=row['option_c'],
                    option_d=row['option_d'],
                    correct_answer=row['correct_answer'].upper(),
                    explanation=row.get('explanation', ''),
                    marks=int(row.get('marks', 1)),
                    order=int(row.get('order', 0))
                )
                questions_created += 1
            
            messages.success(request, f'{questions_created} questions imported successfully!')
            return redirect('cbt_question_list', exam_id=exam.id)
            
        except Exception as e:
            messages.error(request, f'Error importing questions: {str(e)}')
    
    context = {'exam': exam, 'school': school}
    return render(request, 'score/bulk_import_questions.html', context)



"""

# score/views/analytics_views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db.models import Avg, Sum, Max, Min, Count
from .models import Student, Score, Subject, Term, AcademicSession, ClassGroup
from .decorators import school_required
import json


@school_required
def select_student_for_analytics(request):
    school = request.school

    sessions = AcademicSession.objects.all().order_by("-name")
    terms = Term.objects.all()
    classes = ClassGroup.objects.filter(school=school)

    selected_session = None
    selected_term = None
    selected_class = None
    students = None

    if request.method == "POST":
        session_id = request.POST.get("session")
        term_id = request.POST.get("term")
        class_id = request.POST.get("class_group")
        student_id = request.POST.get("student")

        # Handle dropdown reloading
        if session_id:
            selected_session = get_object_or_404(AcademicSession, id=session_id)

        if term_id:
            selected_term = get_object_or_404(Term, id=term_id)

        if class_id:
            selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
            students = Student.objects.filter(
                class_group=selected_class,
                school=school
            ).order_by("surname", "first_name")

        # Final submit → redirect to analytics page
        if student_id and selected_session and selected_term:
            url = reverse(
                "student_analytics",
                kwargs={"student_id": student_id}
            )
            return redirect(f"{url}?session={selected_session.id}&term={selected_term.id}")

    context = {
        "sessions": sessions,
        "terms": terms,
        "classes": classes,
        "students": students,
        "selected_session": selected_session,
        "selected_term": selected_term,
        "selected_class": selected_class,
        "school": school,
    }

    return render(request, "score/select_student_analytics.html", context)


@school_required
def student_performance_analytics(request, student_id):
    school = request.school

    # ────────────────────────────────────────────────────────────────
    # SECURITY: student must belong to this school
    # ────────────────────────────────────────────────────────────────
    student = get_object_or_404(Student, id=student_id, school=school)
    current_class = student.class_group

    # ────────────────────────────────────────────────────────────────
    # TERM & SESSION SELECTION (from dropdowns or default)
    # ────────────────────────────────────────────────────────────────
    term_id = request.GET.get("term")
    session_id = request.GET.get("session")

    if session_id:
        current_session = get_object_or_404(AcademicSession, id=session_id)
    else:
        current_session = AcademicSession.objects.order_by("-name").first()

    if term_id:
        latest_term = get_object_or_404(Term, id=term_id)
    else:
        latest_term = (
            Term.objects.filter(
                score__student=student,
                score__session=current_session
            )
            .order_by("-id")
            .first()
            or Term.objects.filter(name="Third Term").first()
        )

    # ===============================================================
    # 1. PERFORMANCE ACROSS SUBJECTS (SELECTED TERM & SESSION)
    # ===============================================================
    subjects_performance = (
        Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        )
        .values("subject__name")
        .annotate(total_score=Sum("total"))
        .order_by("-total_score")
    )

    subjects_chart = {
        "labels": [i["subject__name"] for i in subjects_performance],
        "data": [float(i["total_score"] or 0) for i in subjects_performance],
        "backgroundColor": [
            "#4e73df", "#1cc88a", "#36b9cc", "#f6c23e",
            "#e74a3b", "#858796", "#5a5c69", "#2e59d9", "#17a673", "#2c9faf"
        ]
    }

    # ===============================================================
    # 2. PROGRESS ACROSS TERMS (CURRENT SESSION)
    # ===============================================================
    all_terms = Term.objects.all().order_by("id")

    terms_performance = (
        Score.objects.filter(student=student, session=current_session)
        .values("term__name")
        .annotate(avg_score=Avg("total"))
    )

    term_map = {t["term__name"]: float(t["avg_score"] or 0) for t in terms_performance}

    terms_chart = {
        "labels": [t.name for t in all_terms],
        "data": [term_map.get(t.name, 0) for t in all_terms]
    }

    # ===============================================================
    # 3. PERFORMANCE ACROSS SESSIONS
    # ===============================================================
    sessions_performance = (
        Score.objects.filter(student=student)
        .values("session__name")
        .annotate(avg_score=Avg("total"))
        .order_by("session__name")
    )

    sessions_chart = {
        "labels": [i["session__name"] for i in sessions_performance],
        "data": [float(i["avg_score"] or 0) for i in sessions_performance]
    }

    # Calculate best & worst session with averages
    best_session = max(sessions_performance, key=lambda x: x["avg_score"] or 0, default=None)
    worst_session = min(sessions_performance, key=lambda x: x["avg_score"] or 0, default=None)
    
    best_avg = round(best_session["avg_score"] or 0, 1) if best_session else 0
    worst_avg = round(worst_session["avg_score"] or 0, 1) if worst_session else 0

    # ===============================================================
    # 4. CLASS COMPARISON (TOP 15 STUDENTS)
    # ===============================================================
    class_students = Student.objects.filter(class_group=current_class)

    all_totals = (
        Score.objects.filter(
            student__in=class_students,
            term=latest_term,
            session=current_session
        )
        .values("student")
        .annotate(total=Sum("total"))
        .order_by("-total")
    )

    position = None
    for i, record in enumerate(all_totals, 1):
        if record["student"] == student.id:
            position = i
            break

    class_avg = all_totals.aggregate(avg=Avg("total"))["avg"] or 0

    student_totals = (
        Score.objects.filter(
            student__in=class_students,
            term=latest_term,
            session=current_session
        )
        .values("student", "student__surname", "student__first_name")
        .annotate(total=Sum("total"))
        .order_by("-total")[:15]
    )

    labels, data, colors = [], [], []
    for r in student_totals:
        name = f"{r['student__surname']} {r['student__first_name'][:1]}."
        labels.append(name)
        data.append(float(r["total"] or 0))
        colors.append("#f6c23e" if r["student"] == student.id else "#4e73df")

    comparison_chart = {
        "labels": labels,
        "data": data,
        "backgroundColor": colors
    }

    # ===============================================================
    # 5. SUBJECT COMPARISON (STUDENT vs CLASS AVG vs HIGHEST)
    # ===============================================================
    all_subjects = Subject.objects.filter(class_group=current_class)
    subject_comparison_data = []

    for subject in all_subjects:
        student_score = Score.objects.filter(
            student=student,
            subject=subject,
            term=latest_term,
            session=current_session
        ).first()

        stats = Score.objects.filter(
            student__class_group=current_class,
            subject=subject,
            term=latest_term,
            session=current_session
        ).aggregate(avg=Avg("total"), max=Max("total"))

        subject_comparison_data.append({
            "subject": subject.name,
            "student_score": float(student_score.total if student_score else 0),
            "class_avg": float(stats["avg"] or 0),
            "highest": float(stats["max"] or 0),
        })

    subject_comparison_chart = {
        "labels": [i["subject"] for i in subject_comparison_data],
        "datasets": [
            {
                "label": "Student Score",
                "data": [i["student_score"] for i in subject_comparison_data],
                "backgroundColor": "#1cc88a"
            },
            {
                "label": "Class Average",
                "data": [i["class_avg"] for i in subject_comparison_data],
                "backgroundColor": "#36b9cc"
            },
            {
                "label": "Highest Score",
                "data": [i["highest"] for i in subject_comparison_data],
                "backgroundColor": "#f6c23e"
            },
        ]
    }

    # ===============================================================
    # 6. OVERALL CLASS PERFORMANCE ACROSS ALL SUBJECTS
    # ===============================================================
    overall_performance_data = []
    
    for subject in all_subjects:
        stats = Score.objects.filter(
            student__class_group=current_class,
            subject=subject,
            term=latest_term,
            session=current_session
        ).aggregate(
            avg=Avg("total"),
            max=Max("total"),
            min=Min("total"),
            count=Count("id")
        )
        
        overall_performance_data.append({
            "subject": subject.name,
            "average": float(stats["avg"] or 0),
            "highest": float(stats["max"] or 0),
            "lowest": float(stats["min"] or 0),
            "student_count": stats["count"]
        })
    
    # Sort by average score
    overall_performance_data.sort(key=lambda x: x["average"], reverse=True)
    
    overall_class_chart = {
        "labels": [i["subject"] for i in overall_performance_data],
        "data": [i["average"] for i in overall_performance_data],
        "backgroundColor": [
            "#1cc88a" if i["average"] >= 70
            else "#f6c23e" if i["average"] >= 50
            else "#e74a3b"
            for i in overall_performance_data
        ]
    }

    # ===============================================================
    # 7. STRENGTHS & WEAKNESSES
    # ===============================================================
    student_subjects = (
        Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        )
        .select_related("subject")
        .order_by("-total")
    )

    strengths = list(student_subjects[:3])
    weaknesses = list(student_subjects.order_by("total")[:3])

    # ===============================================================
    # 8. SUMMARY STATISTICS
    # ===============================================================
    student_stats = {
        "total_subjects": all_subjects.count(),
        "average_score": Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        ).aggregate(avg=Avg("total"))["avg"] or 0,
        "highest": Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        ).aggregate(max=Max("total"))["max"] or 0,
        "lowest": Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        ).aggregate(min=Min("total"))["min"] or 0,
    }

    # ===============================================================
    # DEBUG: Print all chart data to console
    # ===============================================================
    print("=" * 80)
    print("DEBUGGING: student_performance_analytics")
    print("=" * 80)
    print(f"Student: {student.full_name}")
    print(f"Current Class: {current_class.name}")
    print(f"Current Session: {current_session.name}")
    print(f"Latest Term: {latest_term.name}")
    print(f"\nSubjects Chart Data:")
    print(f"  Labels: {subjects_chart['labels']}")
    print(f"  Data: {subjects_chart['data']}")
    print(f"  Colors: {subjects_chart['backgroundColor']}")
    print(f"\nTerms Chart Data:")
    print(f"  Labels: {terms_chart['labels']}")
    print(f"  Data: {terms_chart['data']}")
    print(f"\nSessions Chart Data:")
    print(f"  Labels: {sessions_chart['labels']}")
    print(f"  Data: {sessions_chart['data']}")
    print(f"\nComparison Chart Data (Top 15):")
    print(f"  Labels: {comparison_chart['labels']}")
    print(f"  Data: {comparison_chart['data']}")
    print(f"  Colors: {comparison_chart['backgroundColor']}")
    print(f"\nStudent Stats:")
    print(f"  Total Subjects: {student_stats['total_subjects']}")
    print(f"  Average Score: {student_stats['average_score']}")
    print(f"  Position in Class: {position}")
    print("=" * 80)

    # ===============================================================
    # CONTEXT
    # ===============================================================
    context = {
        "student": student,
        "current_class": current_class,
        "current_session": current_session,
        "latest_term": latest_term,

        # Charts (as JSON)
        "subjects_json": json.dumps(subjects_chart),
        "terms_json": json.dumps(terms_chart),
        "sessions_json": json.dumps(sessions_chart),
        "comparison_json": json.dumps(comparison_chart),
        "subject_comparison_json": json.dumps(subject_comparison_chart),
        "overall_class_json": json.dumps(overall_class_chart),

        # Statistics
        "position_in_class": position,
        "class_average": round(class_avg, 1),
        "best_session": best_session["session__name"] if best_session else "N/A",
        "best_avg": best_avg,
        "worst_session": worst_session["session__name"] if worst_session else "N/A",
        "worst_avg": worst_avg,
        
        "student_stats": student_stats,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_performance_data": overall_performance_data,
    }

    return render(request, "score/student_analytics.html", context)

"""

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db.models import Avg, Sum, Max, Min, Count
from .models import Student, Score, Subject, Term, AcademicSession, ClassGroup
from .decorators import school_required
import json


def get_user_context(request):
    """
    Determine if user is admin or teacher and return appropriate context
    Returns: {
        'is_admin': bool,
        'is_teacher': bool,
        'is_student': bool,
        'school': School object,
        'class_group': ClassGroup object (if teacher/student),
        'student': Student object (if student),
        'classes': QuerySet of classes (filtered based on user type)
    }
    """
    user_type = request.session.get('user_type')
    
    if user_type == 'admin':
        # Admin access - use existing @school_required decorator pattern
        if hasattr(request, 'school'):
            school = request.school
        else:
            return None
            
        return {
            'is_admin': True,
            'is_teacher': False,
            'is_student': False,
            'school': school,
            'class_group': None,
            'student': None,
            'classes': ClassGroup.objects.filter(school=school).order_by('name')
        }
    
    elif user_type == 'teacher':
        # Teacher access - get from Django auth
        if not request.user.is_authenticated:
            return None
            
        try:
            class_group = ClassGroup.objects.select_related('school').get(teacher_user=request.user)
            return {
                'is_admin': False,
                'is_teacher': True,
                'is_student': False,
                'school': class_group.school,
                'class_group': class_group,
                'student': None,
                'classes': ClassGroup.objects.filter(id=class_group.id)
            }
        except ClassGroup.DoesNotExist:
            return None
    
    elif user_type == 'student':
        # Student access - get from Django auth
        if not request.user.is_authenticated:
            return None
            
        try:
            student = Student.objects.select_related('class_group', 'school').get(user=request.user)
            return {
                'is_admin': False,
                'is_teacher': False,
                'is_student': True,
                'school': student.school,
                'class_group': student.class_group,
                'student': student,
                'classes': ClassGroup.objects.filter(id=student.class_group.id)
            }
        except Student.DoesNotExist:
            return None
    
    return None


# @school_required
# def select_student_for_analytics(request):
#     # Get user context
#     user_ctx = get_user_context(request)
#     if not user_ctx:
#         return redirect('login')  # or appropriate error page
    
#     school = user_ctx['school']

#     sessions = AcademicSession.objects.all().order_by("-name")
#     terms = Term.objects.all()
#     classes = user_ctx['classes']  # Filtered based on user role

#     selected_session = None
#     selected_term = None
#     selected_class = None
#     students = None

#     # Pre-select class for teacher/student
#     if user_ctx['is_teacher'] or user_ctx['is_student']:
#         selected_class = user_ctx['class_group']

#     if request.method == "POST":
#         session_id = request.POST.get("session")
#         term_id = request.POST.get("term")
#         class_id = request.POST.get("class_group")
#         student_id = request.POST.get("student")

#         # Handle dropdown reloading
#         if session_id:
#             selected_session = get_object_or_404(AcademicSession, id=session_id)

#         if term_id:
#             selected_term = get_object_or_404(Term, id=term_id)

#         if class_id:
#             # Security check: ensure user has access to this class
#             if user_ctx['is_admin']:
#                 selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
#             elif user_ctx['is_teacher']:
#                 if int(class_id) != user_ctx['class_group'].id:
#                     return redirect('select_student_for_analytics')
#                 selected_class = user_ctx['class_group']
#             elif user_ctx['is_student']:
#                 if int(class_id) != user_ctx['class_group'].id:
#                     return redirect('select_student_for_analytics')
#                 selected_class = user_ctx['class_group']
            
#             # Filter students based on user role
#             if user_ctx['is_student']:
#                 # Student can only see themselves
#                 students = Student.objects.filter(
#                     id=user_ctx['student'].id,
#                     school=school
#                 ).order_by("surname", "first_name")
#             else:
#                 # Admin and Teacher can see all students in the class
#                 students = Student.objects.filter(
#                     class_group=selected_class,
#                     school=school
#                 ).order_by("surname", "first_name")

#         # Final submit → redirect to analytics page
#         if student_id and selected_session and selected_term:
#             # Security check: verify student access
#             if user_ctx['is_student']:
#                 if int(student_id) != user_ctx['student'].id:
#                     return redirect('select_student_for_analytics')
#             elif user_ctx['is_teacher']:
#                 # Verify student belongs to teacher's class
#                 student = get_object_or_404(Student, id=student_id, school=school)
#                 if student.class_group.id != user_ctx['class_group'].id:
#                     return redirect('select_student_for_analytics')
            
#             url = reverse(
#                 "student_analytics",
#                 kwargs={"student_id": student_id}
#             )
#             qs = f"session={selected_session.id}&term={selected_term.id}"
#             if request.GET.get("embed") or request.POST.get("embed"):
#                 qs += "&embed=1"
#             return redirect(f"{url}?{qs}")

#     context = {
#         "sessions": sessions,
#         "terms": terms,
#         "classes": classes,
#         "students": students,
#         "selected_session": selected_session,
#         "selected_term": selected_term,
#         "selected_class": selected_class,
#         "is_admin": user_ctx['is_admin'],
#         "is_teacher": user_ctx['is_teacher'],
#         "is_student": user_ctx['is_student'],
#         "user_class_group": user_ctx['class_group'],
#         "school": school,
#     }

#     if user_ctx['is_teacher'] and user_ctx.get('class_group'):
#         teacher_ctx = get_teacher_dashboard_context(user_ctx['class_group'])
#         teacher_ctx.update(context)
#         return render(request, "score/select_student_analytics_teacher.html", teacher_ctx)

#     if user_ctx['is_student'] and (request.GET.get("embed") or request.POST.get("embed")):
#         response = render(request, "score/select_student_analytics_embed.html", context)
#         response["X-Frame-Options"] = "SAMEORIGIN"
#         return response

#     return render(request, "score/select_student_analytics.html", context)

@school_required
def select_student_for_analytics(request):
    # Get user context
    user_ctx = get_user_context(request)
    if not user_ctx:
        return redirect('login')  # or appropriate error page
    
    school = user_ctx['school']

    sessions = AcademicSession.objects.all().order_by("-name")
    terms = Term.objects.all()
    classes = user_ctx['classes']  # Filtered based on user role

    selected_session = None
    selected_term = None
    selected_class = None
    students = None

    # Detect embed mode (from GET or POST)
    is_embed = request.GET.get("embed") == "1" or request.POST.get("embed") == "1"

    # Pre-select class for teacher/student
    if user_ctx['is_teacher'] or user_ctx['is_student']:
        selected_class = user_ctx['class_group']

    if request.method == "POST":
        session_id = request.POST.get("session")
        term_id = request.POST.get("term")
        class_id = request.POST.get("class_group")
        student_id = request.POST.get("student")

        # Handle dropdown reloading
        if session_id:
            selected_session = get_object_or_404(AcademicSession, id=session_id)

        if term_id:
            selected_term = get_object_or_404(Term, id=term_id)

        if class_id:
            # Security check: ensure user has access to this class
            if user_ctx['is_admin']:
                selected_class = get_object_or_404(ClassGroup, id=class_id, school=school)
            elif user_ctx['is_teacher']:
                if int(class_id) != user_ctx['class_group'].id:
                    return redirect('select_student_for_analytics')
                selected_class = user_ctx['class_group']
            elif user_ctx['is_student']:
                if int(class_id) != user_ctx['class_group'].id:
                    return redirect('select_student_for_analytics')
                selected_class = user_ctx['class_group']

            # Filter students based on user role
            if user_ctx['is_student']:
                # Student can only see themselves
                students = Student.objects.filter(
                    id=user_ctx['student'].id,
                    school=school
                ).order_by("surname", "first_name")
            else:
                # Admin and Teacher can see all students in the class
                students = Student.objects.filter(
                    class_group=selected_class,
                    school=school
                ).order_by("surname", "first_name")

        # Final submit → redirect to analytics page
        if student_id and selected_session and selected_term:
            # Security check: verify student access
            if user_ctx['is_student']:
                if int(student_id) != user_ctx['student'].id:
                    return redirect('select_student_for_analytics')
            elif user_ctx['is_teacher']:
                # Verify student belongs to teacher's class
                student = get_object_or_404(Student, id=student_id, school=school)
                if student.class_group.id != user_ctx['class_group'].id:
                    return redirect('select_student_for_analytics')

            url = reverse(
                "student_analytics",
                kwargs={"student_id": student_id}
            )
            qs = f"session={selected_session.id}&term={selected_term.id}"
            if is_embed:
                qs += "&embed=1"
            return redirect(f"{url}?{qs}")

    context = {
        "sessions": sessions,
        "terms": terms,
        "classes": classes,
        "students": students,
        "selected_session": selected_session,
        "selected_term": selected_term,
        "selected_class": selected_class,
        "is_admin": user_ctx['is_admin'],
        "is_teacher": user_ctx['is_teacher'],
        "is_student": user_ctx['is_student'],
        "user_class_group": user_ctx['class_group'],
        "school": school,
    }

    # ----------------------------------------------------------------
    # TEACHER
    # ----------------------------------------------------------------
    if user_ctx['is_teacher'] and user_ctx.get('class_group'):
        if is_embed:
            # Standalone template — no {% extends %}, loads cleanly in iframe
            response = render(request, "score/select_student_analytics_teacher_embed.html", context)
            response["X-Frame-Options"] = "SAMEORIGIN"
            return response
        # Full page — extends teacher_dashboard.html
        teacher_ctx = get_teacher_dashboard_context(user_ctx['class_group'])
        teacher_ctx.update(context)
        return render(request, "score/select_student_analytics_teacher.html", teacher_ctx)

    # ----------------------------------------------------------------
    # STUDENT
    # ----------------------------------------------------------------
    if user_ctx['is_student']:
        if is_embed:
            # Standalone template — loads cleanly in iframe
            response = render(request, "score/select_student_analytics_embed.html", context)
            response["X-Frame-Options"] = "SAMEORIGIN"
            return response
        # Full page — extends student dashboard (or base)
        return render(request, "score/select_student_analytics.html", context)

    # ----------------------------------------------------------------
    # ADMIN
    # ----------------------------------------------------------------
    if is_embed:
        # Standalone template — no {% extends %}, loads cleanly in iframe
        response = render(request, "score/select_student_analytics_admin_embed.html", context)
        response["X-Frame-Options"] = "SAMEORIGIN"
        return response

    # Full page — extends dashboard.html
    return render(request, "score/select_student_analytics.html", context)

@school_required
def student_performance_analytics(request, student_id):
    # Get user context
    user_ctx = get_user_context(request)
    if not user_ctx:
        return redirect('login')
    
    school = user_ctx['school']

    # ────────────────────────────────────────────────────────────────
    # SECURITY: Verify user has access to this student
    # ────────────────────────────────────────────────────────────────
    student = get_object_or_404(Student, id=student_id, school=school)
    
    # Role-based access control
    if user_ctx['is_student']:
        # Students can only view their own analytics
        if student.id != user_ctx['student'].id:
            return redirect('select_student_for_analytics')
    elif user_ctx['is_teacher']:
        # Teachers can only view students in their class
        if student.class_group.id != user_ctx['class_group'].id:
            return redirect('select_student_for_analytics')
    # Admin can view any student in their school (already verified by get_object_or_404)
    
    current_class = student.class_group

    # ────────────────────────────────────────────────────────────────
    # TERM & SESSION SELECTION (from dropdowns or default)
    # ────────────────────────────────────────────────────────────────
    term_id = request.GET.get("term")
    session_id = request.GET.get("session")

    if session_id:
        current_session = get_object_or_404(AcademicSession, id=session_id)
    else:
        current_session = AcademicSession.objects.order_by("-name").first()

    if term_id:
        latest_term = get_object_or_404(Term, id=term_id)
    else:
        latest_term = (
            Term.objects.filter(
                score__student=student,
                score__session=current_session
            )
            .order_by("-id")
            .first()
            or Term.objects.filter(name="Third Term").first()
        )

    # ===============================================================
    # 1. PERFORMANCE ACROSS SUBJECTS (SELECTED TERM & SESSION)
    # ===============================================================
    subjects_performance = (
        Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        )
        .values("subject__name")
        .annotate(total_score=Sum("total"))
        .order_by("-total_score")
    )

    subjects_chart = {
        "labels": [i["subject__name"] for i in subjects_performance],
        "data": [float(i["total_score"] or 0) for i in subjects_performance],
        "backgroundColor": [
            "#4e73df", "#1cc88a", "#36b9cc", "#f6c23e",
            "#e74a3b", "#858796", "#5a5c69", "#2e59d9", "#17a673", "#2c9faf"
        ]
    }

    # ===============================================================
    # 2. PROGRESS ACROSS TERMS (CURRENT SESSION)
    # ===============================================================
    all_terms = Term.objects.all().order_by("id")

    terms_performance = (
        Score.objects.filter(student=student, session=current_session)
        .values("term__name")
        .annotate(avg_score=Avg("total"))
    )

    term_map = {t["term__name"]: float(t["avg_score"] or 0) for t in terms_performance}

    terms_chart = {
        "labels": [t.name for t in all_terms],
        "data": [term_map.get(t.name, 0) for t in all_terms]
    }

    # ===============================================================
    # 3. PERFORMANCE ACROSS SESSIONS
    # ===============================================================
    sessions_performance = (
        Score.objects.filter(student=student)
        .values("session__name")
        .annotate(avg_score=Avg("total"))
        .order_by("session__name")
    )

    sessions_chart = {
        "labels": [i["session__name"] for i in sessions_performance],
        "data": [float(i["avg_score"] or 0) for i in sessions_performance]
    }

    # Calculate best & worst session with averages
    best_session = max(sessions_performance, key=lambda x: x["avg_score"] or 0, default=None)
    worst_session = min(sessions_performance, key=lambda x: x["avg_score"] or 0, default=None)
    
    best_avg = round(best_session["avg_score"] or 0, 1) if best_session else 0
    worst_avg = round(worst_session["avg_score"] or 0, 1) if worst_session else 0

    # ===============================================================
    # 4. CLASS COMPARISON (TOP 15 STUDENTS)
    # ===============================================================
    class_students = Student.objects.filter(class_group=current_class)

    all_totals = (
        Score.objects.filter(
            student__in=class_students,
            term=latest_term,
            session=current_session
        )
        .values("student")
        .annotate(total=Sum("total"))
        .order_by("-total")
    )

    position = None
    for i, record in enumerate(all_totals, 1):
        if record["student"] == student.id:
            position = i
            break

    class_avg = all_totals.aggregate(avg=Avg("total"))["avg"] or 0

    student_totals = (
        Score.objects.filter(
            student__in=class_students,
            term=latest_term,
            session=current_session
        )
        .values("student", "student__surname", "student__first_name")
        .annotate(total=Sum("total"))
        .order_by("-total")[:15]
    )

    labels, data, colors = [], [], []
    for r in student_totals:
        name = f"{r['student__surname']} {r['student__first_name'][:1]}."
        labels.append(name)
        data.append(float(r["total"] or 0))
        colors.append("#f6c23e" if r["student"] == student.id else "#4e73df")

    comparison_chart = {
        "labels": labels,
        "data": data,
        "backgroundColor": colors
    }

    # ===============================================================
    # 5. SUBJECT COMPARISON (STUDENT vs CLASS AVG vs HIGHEST)
    # ===============================================================
    all_subjects = Subject.objects.filter(class_group=current_class)
    subject_comparison_data = []

    for subject in all_subjects:
        student_score = Score.objects.filter(
            student=student,
            subject=subject,
            term=latest_term,
            session=current_session
        ).first()

        stats = Score.objects.filter(
            student__class_group=current_class,
            subject=subject,
            term=latest_term,
            session=current_session
        ).aggregate(avg=Avg("total"), max=Max("total"))

        subject_comparison_data.append({
            "subject": subject.name,
            "student_score": float(student_score.total if student_score else 0),
            "class_avg": float(stats["avg"] or 0),
            "highest": float(stats["max"] or 0),
        })

    subject_comparison_chart = {
        "labels": [i["subject"] for i in subject_comparison_data],
        "datasets": [
            {
                "label": "Student Score",
                "data": [i["student_score"] for i in subject_comparison_data],
                "backgroundColor": "#1cc88a"
            },
            {
                "label": "Class Average",
                "data": [i["class_avg"] for i in subject_comparison_data],
                "backgroundColor": "#36b9cc"
            },
            {
                "label": "Highest Score",
                "data": [i["highest"] for i in subject_comparison_data],
                "backgroundColor": "#f6c23e"
            },
        ]
    }

    # ===============================================================
    # 6. OVERALL CLASS PERFORMANCE ACROSS ALL SUBJECTS
    # ===============================================================
    overall_performance_data = []
    
    for subject in all_subjects:
        stats = Score.objects.filter(
            student__class_group=current_class,
            subject=subject,
            term=latest_term,
            session=current_session
        ).aggregate(
            avg=Avg("total"),
            max=Max("total"),
            min=Min("total"),
            count=Count("id")
        )
        
        overall_performance_data.append({
            "subject": subject.name,
            "average": float(stats["avg"] or 0),
            "highest": float(stats["max"] or 0),
            "lowest": float(stats["min"] or 0),
            "student_count": stats["count"]
        })
    
    # Sort by average score
    overall_performance_data.sort(key=lambda x: x["average"], reverse=True)
    
    overall_class_chart = {
        "labels": [i["subject"] for i in overall_performance_data],
        "data": [i["average"] for i in overall_performance_data],
        "backgroundColor": [
            "#1cc88a" if i["average"] >= 70
            else "#f6c23e" if i["average"] >= 50
            else "#e74a3b"
            for i in overall_performance_data
        ]
    }

    # ===============================================================
    # 7. STRENGTHS & WEAKNESSES
    # ===============================================================
    student_subjects = (
        Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        )
        .select_related("subject")
        .order_by("-total")
    )

    strengths = list(student_subjects[:3])
    weaknesses = list(student_subjects.order_by("total")[:3])

    # ===============================================================
    # 8. SUMMARY STATISTICS
    # ===============================================================
    student_stats = {
        "total_subjects": all_subjects.count(),
        "average_score": Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        ).aggregate(avg=Avg("total"))["avg"] or 0,
        "highest": Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        ).aggregate(max=Max("total"))["max"] or 0,
        "lowest": Score.objects.filter(
            student=student,
            term=latest_term,
            session=current_session
        ).aggregate(min=Min("total"))["min"] or 0,
    }

    # ===============================================================
    # CONTEXT
    # ===============================================================
    context = {
        "student": student,
        "current_class": current_class,
        "current_session": current_session,
        "latest_term": latest_term,

        # Charts (as JSON)
        "subjects_json": json.dumps(subjects_chart),
        "terms_json": json.dumps(terms_chart),
        "sessions_json": json.dumps(sessions_chart),
        "comparison_json": json.dumps(comparison_chart),
        "subject_comparison_json": json.dumps(subject_comparison_chart),
        "overall_class_json": json.dumps(overall_class_chart),

        # Statistics
        "position_in_class": position,
        "class_average": round(class_avg, 1),
        "best_session": best_session["session__name"] if best_session else "N/A",
        "best_avg": best_avg,
        "worst_session": worst_session["session__name"] if worst_session else "N/A",
        "worst_avg": worst_avg,
        
        "student_stats": student_stats,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall_performance_data": overall_performance_data,
        
        # User role context
        "is_admin": user_ctx['is_admin'],
        "is_teacher": user_ctx['is_teacher'],
        "is_student": user_ctx['is_student'],
    }

    response = render(request, "score/student_analytics.html", context)
    if request.GET.get("embed"):
        response["X-Frame-Options"] = "SAMEORIGIN"
    return response