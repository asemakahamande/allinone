from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import json
from score.models import Student, ClassGroup, School
from .services import process_chat_message
from .models import ChatConversation, ChatMessage
from django.contrib.auth.models import User

# === CHAT INTERFACE VIEWS ===

def get_or_create_conversation(user, title="New Chat"):
    conv = ChatConversation.objects.filter(user=user).order_by('-updated_at').first()
    if not conv:
        conv = ChatConversation.objects.create(user=user, title=title)
    return conv

@csrf_exempt
def chat_api(request):
    """
    Unified endpoint to handle chat messages from any portal.
    Expects POST JSON with: {'message': '...', 'role': '...'}
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            message = data.get('message', '')
            role = data.get('role', 'student')
            
            # Determine specific context based on session
            context_data = {}
            if role == 'parent':
                student_id = request.session.get('parent_student_id')
                if student_id:
                    student = Student.objects.get(id=student_id)
                    context_data['student_name'] = student.full_name
                    context_data['school_name'] = student.school.name
            
            # Simple stateless call for now to integrate quickly
            response_text = process_chat_message(request.user, role, message, context_data=context_data)
            
            return JsonResponse({'status': 'success', 'response': response_text})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


# === NEW PORTALS (Normal Teacher & Parent) ===

def parent_dashboard(request):
    """
    Dashboard for parents to chat with the AI.
    """
    from score.models import Term, Score, Attendance, SchoolSetting, AcademicSession, ClassGroup
    
    student_id = request.session.get('parent_student_id')
    if not student_id:
        return redirect('unified_login')
        
    student = Student.objects.get(id=student_id)
    
    # Get all terms and sessions for dropdown
    terms = Term.objects.all()
    sessions = AcademicSession.objects.all().order_by('-name')
    classes = ClassGroup.objects.filter(school=student.school).order_by('name')
    
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
        'terms': terms,
        'sessions': sessions,
        'classes': classes,
    }
    
    return render(request, "ai_agents/parent_dashboard.html", context)


def normal_teacher_dashboard(request):
    """
    Dashboard for normal teachers to chat with AI.
    """
    from score.models import School, SchoolSetting, Subject, ClassGroup, Student, AcademicSession
    
    if not request.session.get('is_normal_teacher'):
        return redirect('unified_login')
        
    school_id = request.session.get('school_id')
    school = None
    setting = None
    subjects = []
    classes = []
    sessions = AcademicSession.objects.all().order_by('-name')
    total_students = 0
    total_classes = 0
    
    if school_id:
        school = School.objects.filter(id=school_id).first()
        if school:
            setting = SchoolSetting.objects.filter(school=school).first()
            subjects = Subject.objects.filter(class_group__school=school).order_by('name')
            classes = ClassGroup.objects.filter(school=school).order_by('name')
            total_students = Student.objects.filter(school=school).count()
            total_classes = classes.count()
            
    context = {
        'school': school,
        'setting': setting,
        'subjects': subjects,
        'classes': classes,
        'sessions': sessions,
        'total_students': total_students,
        'total_classes': total_classes,
    }
    return render(request, "ai_agents/normal_teacher_dashboard.html", context)
