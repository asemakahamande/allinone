from django.urls import path
from . import views

app_name = 'exams'

urlpatterns = [
    path('exam_login/', views.exam_login, name='exam_login'),
    path('take/<int:exam_id>/', views.take_exam, name='take_exam'),
    path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('student_results/', views.student_results, name='student_results'),
    

    path('classlevel/create/', views.create_classlevel, name='create_classlevel'),
    path('subject/create/', views.create_subject, name='create_subject'),
    path('exam/create/', views.create_exam, name='create_exam'),
    path('question/create/', views.create_question, name='create_question'),
    path('result/create/', views.create_result, name='create_result'),

    path('exams/', views.exam_list, name='exam_list'),
    path('exam/<int:exam_id>/questions/', views.create_question, name='create_question'),
    # exams/urls.py
    path('classlevels/', views.classlevel_list, name='classlevel_list'),

    path('classlevels/create/', views.create_classlevel, name='classlevel_create'),
    # exams/urls.py
    path('subject/', views.subject_list, name='subject_list'),
    path('exams/', views.exam_list, name='exam_list'),
    path('questions/', views.question_list, name='question_list'),

    

    
]
