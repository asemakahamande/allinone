# teachers/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Teacher, Employer, Hire
from .forms import TeacherRegistrationForm, EmployerRegistrationForm
# from .emails import send_hire_notification_emails, send_unhire_notification_emails

OWNER_PASSWORD = "@mandez"

# ---------------------------
# Registration
# ---------------------------
def teacher_register(request):
    if request.method == 'POST':
        form = TeacherRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('logn')
    else:
        form = TeacherRegistrationForm()
    return render(request, 'teachersmatters/teacher_register.html', {'form': form})


def employer_register(request):
    if request.method == 'POST':
        form = EmployerRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('logn')
    else:
        form = EmployerRegistrationForm()
    return render(request, 'teachersmatters/employer_register.html', {'form': form})


# ---------------------------
# Login / Logout
# ---------------------------
def logn_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        employer = Employer.objects.filter(email=email, password=password).first()
        if employer:
            request.session['user_id'] = employer.id
            request.session['user_role'] = 'employer'
            return redirect('teacher_list')

        teacher = Teacher.objects.filter(email=email, password=password).first()
        if teacher:
            request.session['user_id'] = teacher.id
            request.session['user_role'] = 'teacher'
            return redirect('teacher_list')

        messages.error(request, 'Invalid email or password')

    return render(request, 'teachersmatters/logn.html')


def logt_view(request):
    request.session.flush()
    return redirect('logn')


# ---------------------------
# Teacher List
# ---------------------------
def teacher_list(request):
    role = request.session.get('user_role')
    if not role:
        return redirect('logn')

    current_user_id = request.session.get('user_id')
    teachers = Teacher.objects.all().order_by('sname', 'fname')

    for teacher in teachers:
        hire = Hire.objects.filter(teacher=teacher, date_unhired__isnull=True).first()
        teacher.is_hired = bool(hire)
        teacher.hired_by_current_user = hire and hire.employer.id == current_user_id
        teacher.hire_record_id = hire.id if hire else None

    context = {
        'teachers': teachers,
        'role': role,
        'user_name': request.session.get('user_name', ''),
    }
    return render(request, 'teachersmatters/teacher_list.html', context)


# ---------------------------
# Hire / Unhire Teacher
# ---------------------------
@require_POST
def hire_teacher(request, teacher_id):
    if request.session.get('user_role') != 'employer':
        messages.error(request, "Only employers can hire teachers.")
        return redirect('teacher_list')

    employer = get_object_or_404(Employer, id=request.session['user_id'])
    teacher = get_object_or_404(Teacher, id=teacher_id)

    if Hire.objects.filter(teacher=teacher, date_unhired__isnull=True).exists():
        messages.warning(request, f"{teacher} is already hired by another employer.")
        return redirect('teacher_list')

    hire = Hire.objects.create(teacher=teacher, employer=employer)
    send_hire_notification_emails(hire)
    messages.success(request, f"You have successfully hired {teacher}.")
    return redirect('teacher_list')


@require_POST
def unhire_teacher(request, teacher_id):
    if request.session.get('user_role') != 'employer':
        messages.error(request, "Only employers can unhire teachers.")
        return redirect('teacher_list')

    employer = get_object_or_404(Employer, id=request.session['user_id'])
    teacher = get_object_or_404(Teacher, id=teacher_id)

    hire = Hire.objects.filter(teacher=teacher, date_unhired__isnull=True).first()
    if not hire:
        messages.info(request, f"{teacher} is not currently hired.")
        return redirect('teacher_list')

    owner_password = request.POST.get('owner_password', '').strip()
    is_hirer = hire.employer == employer
    is_owner = owner_password == OWNER_PASSWORD

    if not (is_hirer or is_owner):
        messages.error(request, "You can only unhire teachers you hired or enter the owner password.")
        return redirect('teacher_list')

    hire.unhire(by_owner=is_owner)
    send_unhire_notification_emails(hire, by_owner=is_owner)
    messages.success(request, f"{teacher} has been successfully unhired.")
    return redirect('teacher_list')


# ---------------------------
# Employer Dashboard (Owner Password Protected)
# ---------------------------
from django.db.models import Q

def employer_dashboard(request):
    # Step 1: Handle owner password (POST)
    if request.method == "POST":
        password = request.POST.get("owner_password")
        if password != OWNER_PASSWORD:
            messages.error(request, "Incorrect password. Access denied.")
            return render(request, 'teachersmatters/employer_dashboard_login.html')

        # mark session as authenticated (optional but recommended)
        request.session['owner_authenticated'] = True

    # Step 2: Prevent access if not authenticated
    if not request.session.get('owner_authenticated'):
        return render(request, 'teachersmatters/employer_dashboard_login.html')

    # Step 3: Get search query (GET)
    search = request.GET.get('q', '').strip()

    search_filter = Q()
    if search:
        search_filter = (
            Q(teacher__sname__icontains=search) |
            Q(teacher__fname__icontains=search) |
            Q(teacher__mname__icontains=search) |
            Q(teacher__phone__icontains=search) |
            Q(teacher__email__icontains=search) |
            Q(employer__sname__icontains=search) |
            Q(employer__fname__icontains=search) |
            Q(employer__mname__icontains=search) |
            Q(employer__phone__icontains=search) |
            Q(employer__email__icontains=search)
        )

    # Step 4: Dynamic table (currently hired)
    currently_hired = Hire.objects.filter(
        date_unhired__isnull=True
    ).filter(
        search_filter
    ).select_related('teacher', 'employer')

    # Step 5: Static table (history)
    hire_history = Hire.objects.filter(
        search_filter
    ).select_related('teacher', 'employer')

    return render(request, 'teachersmatters/employer_dashboard.html', {
        'currently_hired': currently_hired,
        'hire_history': hire_history,
        'search': search,
    })



# teachers/views.py

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

def format_full_name(person):
    return f"{person.sname} {person.fname} {person.mname or ''}".strip()

def send_hire_notification_emails(hire):
    teacher = hire.teacher
    employer = hire.employer
    hire_time = hire.date_hired.strftime("%Y-%m-%d %H:%M")

    teacher_name = format_full_name(teacher)
    employer_name = format_full_name(employer)

    # 1. Email to Admin
    send_mail(
        subject="Teacher Hired",
        message=f"""
A new teacher has been hired.

Teacher: {teacher_name}
Phone: {teacher.phone}
Email: {teacher.email}

Hired by:
Employer: {employer_name}
Phone: {employer.phone}
Email: {employer.email}

Date & Time Hired: {hire_time}
        """.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.ADMIN_EMAIL],
    )

    # 2. Email to Employer
    send_mail(
        subject="You Have Hired a Teacher",
        message=f"""
Dear {employer_name},

You have successfully hired a teacher.

Teacher: {teacher_name}
Phone: {teacher.phone}
Email: {teacher.email}

Date & Time: {hire_time}

Thank you for using Teachers Matters.
        """.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[employer.email],
    )

    # 3. Email to Teacher
    send_mail(
        subject="Congratulations! You Have Been Hired",
        message=f"""
Dear {teacher_name},

Great news! You have been hired by an employer.

Employer: {employer_name}
Phone: {employer.phone}
Email: {employer.email}

Date & Time Hired: {hire_time}

Please log in to view more details.

Best wishes,
Teachers Matters Team
        """.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[teacher.email],
    )

def send_unhire_notification_emails(hire, by_owner=False):
    teacher = hire.teacher
    employer = hire.employer  # the original hirer
    unhire_time = hire.date_unhired.strftime("%Y-%m-%d %H:%M")
    hire_time = hire.date_hired.strftime("%Y-%m-%d %H:%M")

    teacher_name = format_full_name(teacher)
    employer_name = format_full_name(employer)

    action_by = "Owner (admin override)" if by_owner else employer_name

    # 1. Admin
    send_mail(
        subject="Teacher Unhired",
        message=f"""
A teacher has been unhired.

Teacher: {teacher_name}
Email: {teacher.email}

Originally hired by: {employer_name}
Hired on: {hire_time}

Unhired on: {unhire_time}
Unhired by: {action_by}
        """.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.ADMIN_EMAIL],
    )

    # 2. Original Employer
    send_mail(
        subject="A Teacher You Hired Has Been Unhired",
        message=f"""
Dear {employer_name},

A teacher you previously hired has been unhired.

Teacher: {teacher_name}
Email: {teacher.email}

Unhired on: {unhire_time}
Unhired by: {action_by}

        """.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[employer.email],
    )

    # 3. Teacher
    send_mail(
        subject="Employment Status Update",
        message=f"""
Dear {teacher_name},

Your employment has ended with the following employer.

Employer: {employer_name}
Email: {employer.email}

Originally hired on: {hire_time}
Employment ended on: {unhire_time}

You are now free to be hired by other employers.

Best regards,
Teachers Matters Team
        """.strip(),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[teacher.email],
    )