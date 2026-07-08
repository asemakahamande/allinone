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
            if request.content_type.startswith('multipart/form-data'):
                message = request.POST.get('message', '')
                role = request.POST.get('role', 'student')
                uploaded_file = request.FILES.get('file')
            else:
                data = json.loads(request.body)
                message = data.get('message', '')
                role = data.get('role', 'student')
                uploaded_file = None
            
            # Extract text from file if attached
            extracted_text = ""
            if uploaded_file:
                import tempfile
                import os
                from .services import extract_text_from_file
                # Save temporarily to extract text
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
                    for chunk in uploaded_file.chunks():
                        tmp.write(chunk)
                    tmp_path = tmp.name
                
                try:
                    extracted_text = extract_text_from_file(tmp_path)
                finally:
                    os.unlink(tmp_path)
            
            # Determine specific context based on session
            context_data = {}
            if role == 'parent':
                student_id = request.session.get('parent_student_id')
                if student_id:
                    student = Student.objects.get(id=student_id)
                    context_data['student_name'] = student.full_name
                    context_data['school_name'] = student.school.name
            
            # Simple stateless call for now to integrate quickly
            response_text = process_chat_message(request.user, role, message, context_data=context_data, extracted_text=extracted_text)
            
            return JsonResponse({'status': 'success', 'response': response_text})
        except Exception as e:
            import traceback
            traceback.print_exc()
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
    import datetime
    today = datetime.date.today()
    total_attendance = Attendance.objects.filter(student=student).count()
    present_count = Attendance.objects.filter(student=student, status="present").count()
    attendance_percentage = round((present_count / total_attendance * 100), 2) if total_attendance else 0
    
    today_attendance = Attendance.objects.filter(student=student, date=today).first()
    today_status = today_attendance.status.capitalize() if today_attendance else "Not marked"
    
    setting = SchoolSetting.objects.filter(school=student.school).first()
    
    # Get assignments for this student's class with submission status
    from score.models import Assignment, AssignmentSubmission
    all_assignments = Assignment.objects.filter(
        class_group=student.class_group
    ).select_related('subject', 'term').order_by('-deadline')
    
    subject_counts = {}
    assignments = []
    for a in all_assignments:
        if subject_counts.get(a.subject_id, 0) < 5:
            assignments.append(a)
            subject_counts[a.subject_id] = subject_counts.get(a.subject_id, 0) + 1
    
    submission_map = {
        sub.assignment_id: sub
        for sub in AssignmentSubmission.objects.filter(student=student)
    }
    for a in assignments:
        a.my_submission = submission_map.get(a.id)
    
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
        'today_status': today_status,
        'current_term': current_term,
        'terms': terms,
        'sessions': sessions,
        'classes': classes,
        'assignments': assignments,
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
