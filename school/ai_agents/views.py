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
    student_id = request.session.get('parent_student_id')
    if not student_id:
        return redirect('unified_login')
        
    student = Student.objects.get(id=student_id)
    return render(request, "ai_agents/parent_dashboard.html", {"student": student})


def normal_teacher_dashboard(request):
    """
    Dashboard for normal teachers to chat with AI.
    """
    if not request.session.get('is_normal_teacher'):
        return redirect('unified_login')
    return render(request, "ai_agents/normal_teacher_dashboard.html")
