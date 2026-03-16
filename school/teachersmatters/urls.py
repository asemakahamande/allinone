from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    # Teacher URLs
    path('teacher/register/', views.teacher_register, name='teacher_register'),

    # Teacher list (shared for teachers and employers)
    path('teacher/list/', views.teacher_list, name='teacher_list'),

    # Hire teacher (employer only - any logged-in employer can hire)
    path('teacher/hire/<int:teacher_id>/', views.hire_teacher, name='hire_teacher'),

    # Unhire teacher (employer only - same employer OR owner password required)
    path('teacher/unhire/<int:teacher_id>/', views.unhire_teacher, name='unhire_teacher'),

    # Employer URLs
    path('employer/register/', views.employer_register, name='employer_register'),
    path('employer/dashboard/', views.employer_dashboard, name='employer_dashboard'),

    # Login / Logout (single login page for both roles)
    path('logn/', views.logn_view, name='logn'),
    path('logt/', views.logt_view, name='logt'),


    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='auth/password_reset.html'
        ),
        name='password_reset'
    ),

    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='auth/password_reset_done.html'
        ),
        name='password_reset_done'
    ),

    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='auth/password_reset_confirm.html'
        ),
        name='password_reset_confirm'
    ),

    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='auth/password_reset_complete.html'
        ),
        name='password_reset_complete'
    ),



]
