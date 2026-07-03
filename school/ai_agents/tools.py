import json
from django.urls import reverse
from score.models import Student, ClassGroup, Score, Timetable, Attendance, Payment
from django.db.models import Avg

def get_student_report_cards_pdf(admission_number, request=None):
    """
    Returns links to generate the report card PDFs for a student given their admission number.
    """
    try:
        student = Student.objects.get(exam_no=admission_number)
        return json.dumps({
            "status": "success",
            "message": f"Found student {student.full_name}.",
            # We can't generate the PDF directly in this simple function without a request object 
            # and proper context easily, but we can return the URL that the user can click to download/view it.
            # Assuming reportcard URL takes student.id, session, term
            "student_id": student.id,
            "action": "Tell the user they can view their report cards on the student portal or you can provide the direct link if you have the session and term."
        })
    except Student.DoesNotExist:
        return json.dumps({"status": "error", "message": "Student not found with that admission number."})

def get_my_results(student_id):
    """
    Fetches the academic scores of the student.
    """
    try:
        student = Student.objects.get(id=student_id)
        scores = Score.objects.filter(student=student).values('subject__name', 'term__name', 'session__name', 'total')
        return json.dumps({"status": "success", "scores": list(scores)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def get_class_performance(class_id):
    """
    Fetches the average scores of a class.
    """
    try:
        class_group = ClassGroup.objects.get(id=class_id)
        scores = Score.objects.filter(student__class_group=class_group).values('subject__name').annotate(average_score=Avg('total'))
        return json.dumps({"status": "success", "class_name": class_group.name, "averages": list(scores)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

# Mapping tool names to functions for the LangChain agent
TOOLS_MAP = {
    "get_student_report_cards_pdf": get_student_report_cards_pdf,
    "get_my_results": get_my_results,
    "get_class_performance": get_class_performance,
}
