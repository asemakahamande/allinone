from django.urls import path
from . import views

# app_name = 'score'

urlpatterns = [
    # ✅ UNIFIED LOGIN (replaces old login/logout)
    path('', views.unified_login, name='unified_login'),
    path('login/', views.unified_login, name='login'),  # Keep this for compatibility
    path('unified_logout/', views.unified_logout, name='unified_logout'),
    
    # Teacher URLs
    path('teacher/dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('teacher/students/', views.teacher_students, name='teacher_students'),
    
    # Student URLs
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
    path('student/scores/', views.student_scores, name='student_scores'),
    
    # Admin - View Credentials
    path('view-credentials/', views.view_all_credentials, name='view_credentials'),
    
    # ... keep all your existing URLs ...





    path("index/", views.index, name="index"),
    # login is handled by unified_login above; logout below
    path('logout/', views.logout, name='logout'),
    path('register/', views.register, name='register'),
    path('api/get-states/', views.get_states, name='get_states'),
    path('api/get-local-governments/', views.get_local_governments, name='get_local_governments'),
    path('dashboard/', views.dashboard, name='dashboard'),

    path("forgot-password/", views.forgot_password, name="forgot_password"),
    path("reset-password/<str:token>/", views.reset_password, name="reset_password"),


    path("add_student/", views.add_student, name="add_student"),
    path("add_class/", views.add_class, name="add_class"),
    path("add_subject/", views.add_subject, name="add_subject"),

    # path("class_view/", views.class_view, name="class_view"),
    path('class_view/', views.class_view, name='class_view'),
    
    # Class CRUD
    path('classes/add/', views.add_class, name='add_class'),
    path('classes/<int:class_id>/edit/', views.edit_class, name='edit_class'),
    path('classes/<int:class_id>/delete/', views.delete_class, name='delete_class'),
    






    path("student/update/<int:student_id>/", views.update_student, name="update_student"),
    path("student/delete/<int:student_id>/", views.delete_student, name="delete_student"),
    path("toggle-student/<int:student_id>/", views.toggle_student_status, name="toggle_student_status"),

    # subject actions
    path("subject/update/<int:subject_id>/", views.update_subject, name="update_subject"),
    path("subject/delete/<int:subject_id>/", views.delete_subject, name="delete_subject"),



    path("staff/", views.staff_list, name="staff_list"),
    path("staff/register/", views.register_staff, name="register_staff"),
    path("staff/update/<int:staff_id>/", views.update_staff, name="update_staff"),
    path("staff/delete/<int:staff_id>/", views.delete_staff, name="delete_staff"),

    path("meetings/", views.meeting_list, name="meeting_list"),
    path("meetings/schedule/", views.schedule_meeting, name="schedule_meeting"),
    path("meetings/update/<int:meeting_id>/", views.update_meeting, name="update_meeting"),
    path("meetings/delete/<int:meeting_id>/", views.delete_meeting, name="delete_meeting"),

    path("timetable/", views.timetable_list, name="timetable_list"),
    path("timetable/add/", views.add_timetable, name="add_timetable"),
     path("timetable/update/<int:pk>/", views.update_timetable, name="update_timetable"),
    path("timetable/delete/<int:timetable_id>/", views.delete_timetable, name="delete_timetable"),



    path("attendance/mark/", views.mark_attendance, name="mark_attendance"),
    path("attendance/report/", views.attendance_report, name="attendance_report"),
    # path("broadsheet/", views.broadsheet, name="broadsheet"),
    path("attendance/delete/<int:student_id>/<str:date>/", views.delete_attendance, name="delete_attendance"),
    




    path("enterscore/", views.enterscore, name="enterscore"),
    path("settings/", views.settings_view, name="settings_view"),

    path("affective/", views.affective_view, name="affective"),
    path("save-affective/", views.save_affective_view, name="save_affective"),

    path("psychomotor/", views.psychomotor_view, name="psychomotor"),
    path("save-psychomotor/", views.save_psychomotor_view, name="save_psychomotor"),

    path("reportcard/", views.reportcard_home, name="reportcard_home"),
    path("reportcard/students/<int:class_id>/<path:session>/<str:term>/",
         views.reportcard_students, name="reportcard_students"),
     path("reportcard/download/<int:class_id>/<path:session_str>/<str:term_str>/", views.reportcard_download_all,
     name="reportcard_download_all",
     ),

    path("reportcard/<int:student_id>/<path:session>/<str:term>/", views.reportcard_view,
    name="reportcard",),

    path(
    "reportcard/print-all/<int:class_id>/<str:session_str>/<str:term_str>/",
    views.reportcard_print_all,
    name="reportcard_print_all",
    ),

    path('send-reportcards/', views.send_reportcards_view, name='send_reportcards'),
    path('get_students/<int:class_id>/', views.get_students, name='get_students'),

    path('promote/', views.promote_students, name='promote_students'),
    path('graduated_students/', views.view_graduated_students, name='graduated_students'),

    # path('publish_result/', views.publish_result, name='publish_result'),
    
    path("broadsheet/", views.broadsheet, name="broadsheet"),
    path("broadsheet/pdf/", views.broadsheet_pdf, name="broadsheet_pdf"),


    # urls.py
    path('classes/<int:class_id>/grading/custom/setup/', 
        views.setup_custom_grading, 
        name='setup_custom_grading'),
        

    path("payments/", views.payments, name="payments"),
    path("process-payment/", views.process_payment, name="process_payment"),
    path("verify-payment/", views.verify_payment, name="verify_payment"),
    # path("publish-results/", views.publish_results, name="publish_results"),
    path('publish-results/', views.publish_results, name='publish_results'),
    path('check-published-students/', views.check_published_students, name='check_published_students'),


    path("invoices/", views.invoices, name="invoices"),
    path("invoices/receipt/<str:reference>/", views.download_receipt, name="download_receipt"),





    path('cbt/login/', views.cbt_login, name='cbt_login'),
    path('cbt/exam/<int:exam_id>/take/', views.take_cbt_exam, name='take_cbt_exam'),
    path('cbt/result/<int:result_id>/', views.view_cbt_result, name='view_cbt_result'),
    
    # ========================================
    # CBT EXAM URLS - TEACHER/ADMIN
    # ========================================
    
    # Dashboard
    path('cbt/dashboard/', views.cbt_dashboard, name='cbt_dashboard'),
    
    # Exam Management
    path('cbt/exams/', views.cbt_exam_list, name='cbt_exam_list'),
    path('cbt/exams/create/', views.create_cbt_exam, name='create_cbt_exam'),
    path('cbt/exams/<int:exam_id>/edit/', views.edit_cbt_exam, name='edit_cbt_exam'),
    path('cbt/exams/<int:exam_id>/delete/', views.delete_cbt_exam, name='delete_cbt_exam'),
    path('cbt/exams/<int:exam_id>/toggle-status/', views.toggle_exam_status, name='toggle_exam_status'),
    
    # Question Management
    path('cbt/exams/<int:exam_id>/questions/', views.cbt_question_list, name='cbt_question_list'),
    path('cbt/exams/<int:exam_id>/questions/create/', views.create_cbt_question, name='create_cbt_question'),
    path('cbt/questions/<int:question_id>/edit/', views.edit_cbt_question, name='edit_cbt_question'),
    path('cbt/questions/<int:question_id>/delete/', views.delete_cbt_question, name='delete_cbt_question'),
    
    # Results Management
    path('cbt/results/', views.cbt_results_list, name='cbt_results_list'),
    path('cbt/results/export/', views.export_cbt_results, name='export_cbt_results'),
    path('cbt/exams/<int:exam_id>/results/', views.exam_results_detail, name='exam_results_detail'),
    

    # score/urls.py
    path(
        "analytics/student/",
        views.select_student_for_analytics,
        name="select_student_analytics"
    ),
    path(
        "analytics/student/<int:student_id>/",
        views.student_performance_analytics,
        name="student_analytics"
    ),

    # ── ASSIGNMENT URLS ──────────────────────────────────────
    # Subject teacher
    path('assignments/', views.assignment_list, name='assignment_list'),
    path('assignments/create/', views.create_assignment, name='create_assignment'),
    path('assignments/<int:assignment_id>/edit/', views.edit_assignment, name='edit_assignment'),
    path('assignments/<int:assignment_id>/delete/', views.delete_assignment, name='delete_assignment'),
    path('assignments/<int:assignment_id>/submissions/', views.view_submissions, name='view_submissions'),

    # Class teacher
    path('teacher/assignments/', views.class_teacher_assignments, name='class_teacher_assignments'),
    path('teacher/assignments/<int:assignment_id>/submissions/', views.class_teacher_view_submissions, name='class_teacher_view_submissions'),

    # Student
    path('student/assignments/', views.student_assignments, name='student_assignments'),
    path('student/assignments/<int:assignment_id>/submit/', views.submit_assignment, name='submit_assignment'),

    # Subjects API (for assignment form dynamic subject dropdown)
    path('api/subjects/', views.get_subjects_for_class, name='get_subjects_for_class'),
]
