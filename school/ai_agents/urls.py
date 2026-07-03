from django.urls import path
from . import views

urlpatterns = [
    path('api/chat/', views.chat_api, name='chat_api'),
    
    path('parent/dashboard/', views.parent_dashboard, name='parent_dashboard'),
    
    path('teacher/dashboard/', views.normal_teacher_dashboard, name='normal_teacher_dashboard'),
]
