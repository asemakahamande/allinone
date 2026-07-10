import json
from django.urls import reverse
from score.models import Student, ClassGroup, Score, Timetable, Attendance, Payment, Pin, Term, AcademicSession, Subject, StudentPromotion, GraduationRecord, School, Exam, Question, PublishedResult
from django.db.models import Avg, Sum
from django.db import transaction
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from weasyprint import HTML
from io import BytesIO
from score.views import reportcard_view_context, weasyprint_url_fetcher

try:
    from langchain_core.tools import tool
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    # Fallback decorator if langchain isn't installed
    def tool(func):
        return func

@tool
def get_student_report_cards_pdf(admission_number: str, school_id: int) -> str:
    """
    Returns links to generate the report card PDFs for a student given their admission number.
    Always requires the school_id to enforce security.
    """
    try:
        student = Student.objects.get(exam_no=admission_number, school_id=school_id)
        return json.dumps({
            "status": "success",
            "message": f"Found student {student.full_name}.",
            "student_id": student.id,
            "action": "Tell the user they can view their report cards on the student portal or you can provide the direct link if you have the session and term."
        })
    except Student.DoesNotExist:
        return json.dumps({"status": "error", "message": "Student not found with that admission number in your school."})

@tool
def get_my_results(student_id: int, school_id: int) -> str:
    """
    Fetches the academic scores of a specific student.
    Requires school_id for security.
    """
    try:
        student = Student.objects.get(id=student_id, school_id=school_id)
        scores = Score.objects.filter(student=student).values('subject__name', 'term__name', 'session__name', 'total')
        return json.dumps({"status": "success", "scores": list(scores)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def get_class_performance(class_id: int, school_id: int) -> str:
    """
    Fetches the average scores of a class.
    Requires school_id for security.
    """
    try:
        class_group = ClassGroup.objects.get(id=class_id, school_id=school_id)
        scores = Score.objects.filter(student__class_group=class_group).values('subject__name').annotate(average_score=Avg('total'))
        return json.dumps({"status": "success", "class_name": class_group.name, "averages": list(scores)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def fetch_billing_receipts(school_id: int, session_name: str = None, term_name: str = None, payment_reference: str = None) -> str:
    """
    Fetches billing and payment receipts for the admin portal. 
    Can filter by session_name (e.g. '2023/2024'), term_name (e.g. 'First Term'), or a specific payment_reference.
    Always strictly isolated to the admin's school_id.
    """
    try:
        query = Payment.objects.filter(school_id=school_id, status='paid')
        
        if payment_reference:
            query = query.filter(reference=payment_reference)
            
        # If session or term is provided, we filter via the associated Pins
        if session_name or term_name:
            pin_filters = {}
            if session_name:
                pin_filters['session__name__icontains'] = session_name
            if term_name:
                pin_filters['term__name__icontains'] = term_name
                
            # Get payments that have pins matching the session/term
            matching_payments = Pin.objects.filter(school_id=school_id, **pin_filters).values_list('payment_id', flat=True)
            query = query.filter(id__in=matching_payments)
            
        payments = query.order_by('-created_at')[:20] # Limit to 20 recent records for LLM context size
        
        results = []
        for p in payments:
            results.append({
                "reference": p.reference,
                "amount": p.amount_display,
                "num_students_pins": p.num_students,
                "date": p.created_at.strftime('%Y-%m-%d'),
                "action": f"Provide the user with a download link format: /billing/receipt/{p.reference}/download"
            })
            
        if not results:
            return json.dumps({"status": "success", "message": "No paid receipts found matching those criteria."})
            
        return json.dumps({
            "status": "success", 
            "count": query.count(),
            "receipts": results,
            "instruction": "Present these receipts to the user clearly and provide the mock download links."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Failed to fetch receipts: {str(e)}"})

@tool
def add_class_tool(name: str, school_id: int) -> str:
    """
    Creates a new ClassGroup for the specified school.
    Requires school_id for security.
    """
    try:
        if ClassGroup.objects.filter(name__iexact=name, school_id=school_id).exists():
            return json.dumps({"status": "error", "message": f"A class named '{name}' already exists in your school."})
        
        new_class = ClassGroup.objects.create(name=name, school_id=school_id)
        return json.dumps({
            "status": "success",
            "message": f"Successfully created class '{new_class.name}'.",
            "class_id": new_class.id
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def add_subject_tool(name: str, class_group_name: str, school_id: int) -> str:
    """
    Creates a new Subject assigned to a specific ClassGroup.
    Requires school_id for security.
    """
    try:
        class_group = ClassGroup.objects.filter(name__iexact=class_group_name, school_id=school_id).first()
        if not class_group:
            return json.dumps({"status": "error", "message": f"Could not find a class named '{class_group_name}' in your school."})
        
        if Subject.objects.filter(name__iexact=name, class_group=class_group).exists():
            return json.dumps({"status": "error", "message": f"The subject '{name}' already exists in class '{class_group.name}'."})
        
        new_subject = Subject.objects.create(name=name, class_group=class_group)
        return json.dumps({
            "status": "success",
            "message": f"Successfully added subject '{new_subject.name}' to class '{class_group.name}'."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def add_student_tool(surname: str, first_name: str, class_group_name: str, session_name: str, school_id: int, parent_surname: str = "Unknown", parent_first_name: str = "Unknown") -> str:
    """
    Creates a new Student record.
    Requires school_id for security.
    """
    try:
        class_group = ClassGroup.objects.filter(name__iexact=class_group_name, school_id=school_id).first()
        if not class_group:
            return json.dumps({"status": "error", "message": f"Could not find a class named '{class_group_name}' in your school."})
        
        session = AcademicSession.objects.filter(name__iexact=session_name).first()
        if not session:
            # Try to get the latest session if not found
            session = AcademicSession.objects.first()
            if not session:
                return json.dumps({"status": "error", "message": "No academic session found. Please create one first."})
        
        # Check if student already exists
        if Student.objects.filter(surname__iexact=surname, first_name__iexact=first_name, class_group=class_group, school_id=school_id, session=session).exists():
            return json.dumps({"status": "error", "message": f"Student '{surname} {first_name}' already exists in class '{class_group.name}' for session '{session.name}'."})
        
        school = School.objects.get(id=school_id)
        
        new_student = Student.objects.create(
            surname=surname,
            first_name=first_name,
            class_group=class_group,
            session=session,
            parent_surname=parent_surname,
            parent_first_name=parent_first_name,
            school=school
        )
        
        return json.dumps({
            "status": "success",
            "message": f"Successfully created student '{new_student.surname} {new_student.first_name}'.",
            "exam_no": new_student.exam_no,
            "class": class_group.name,
            "session": session.name
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def get_graduated_students_tool(school_id: int) -> str:
    """
    Retrieves all graduated students for the specified school.
    """
    try:
        graduated = Student.objects.filter(school_id=school_id, is_graduated=True).order_by('surname', 'first_name')
        if not graduated.exists():
            return json.dumps({"status": "success", "message": "There are no graduated students in the school yet."})
        
        results = [{"name": s.full_name, "exam_no": s.exam_no, "last_class": s.class_group.name if s.class_group else "Unknown"} for s in graduated[:50]]
        return json.dumps({
            "status": "success", 
            "count": graduated.count(),
            "graduated_students": results,
            "message": "Listed up to the first 50 graduated students." if graduated.count() > 50 else "Listed all graduated students."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def promote_students_tool(from_class_name: str, to_class_name: str, session_name: str, school_id: int) -> str:
    """
    Promotes ALL active students in the specified from_class to the to_class for the specified session.
    WARNING: This is a bulk operation. It automatically advances the whole class.
    """
    try:
        from_class = ClassGroup.objects.filter(name__iexact=from_class_name, school_id=school_id).first()
        if not from_class:
            return json.dumps({"status": "error", "message": f"Could not find the 'from' class '{from_class_name}'."})
            
        to_class = ClassGroup.objects.filter(name__iexact=to_class_name, school_id=school_id).first()
        if not to_class:
            return json.dumps({"status": "error", "message": f"Could not find the 'to' class '{to_class_name}'."})
            
        session = AcademicSession.objects.filter(name__iexact=session_name).first()
        if not session:
            return json.dumps({"status": "error", "message": f"Could not find session '{session_name}'."})
            
        students = Student.objects.filter(class_group=from_class, is_graduated=False, school_id=school_id)
        if not students.exists():
            return json.dumps({"status": "error", "message": f"No active students found in '{from_class.name}' to promote."})
            
        promoted_count = 0
        for student in students:
            # Replicate the logic in models.py create_record_for_next_session
            new_student = student.create_record_for_next_session(to_class, session)
            StudentPromotion.objects.create(
                student=student,
                from_class=from_class,
                to_class=to_class,
                status="Promoted",
                session=session
            )
            promoted_count += 1
            
        return json.dumps({
            "status": "success",
            "message": f"Successfully promoted {promoted_count} students from {from_class.name} to {to_class.name} for session {session.name}."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def get_class_view_tool(class_name: str, school_id: int) -> str:
    """
    Retrieves the list of active students and the class teacher for a specific class.
    """
    try:
        class_group = ClassGroup.objects.filter(name__iexact=class_name, school_id=school_id).first()
        if not class_group:
            return json.dumps({"status": "error", "message": f"Could not find class '{class_name}'."})
            
        students = Student.objects.filter(class_group=class_group, is_graduated=False, school_id=school_id).order_by('surname', 'first_name')
        student_list = [{"name": s.full_name, "exam_no": s.exam_no} for s in students[:50]]
        
        return json.dumps({
            "status": "success",
            "class_name": class_group.name,
            "class_teacher": class_group.class_teacher or "None assigned",
            "student_count": students.count(),
            "students": student_list,
            "message": "Listed up to 50 active students." if students.count() > 50 else "Listed all active students."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def get_student_analytics_tool(student_name: str, school_id: int) -> str:
    """
    Retrieves performance analytics (total scores across subjects) for a specific student by name.
    """
    try:
        student = Student.objects.filter(surname__icontains=student_name, school_id=school_id).first()
        if not student:
            student = Student.objects.filter(first_name__icontains=student_name, school_id=school_id).first()
            
        if not student:
            return json.dumps({"status": "error", "message": f"Could not find student matching '{student_name}'."})
            
        # Get latest session scores
        scores = Score.objects.filter(student=student, session=student.session).values('subject__name', 'term__name', 'total', 'grade', 'remark')
        
        # Calculate averages using the imported Avg model aggregate
        avg_total = Score.objects.filter(student=student, session=student.session).aggregate(average_total=Avg('total'))['average_total']
        
        return json.dumps({
            "status": "success",
            "student": student.full_name,
            "class": student.class_group.name,
            "session": student.session.name,
            "overall_average": round(avg_total, 2) if avg_total else 0,
            "scores": list(scores)
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def get_login_credentials_tool(role: str, name: str, school_id: int) -> str:
    """
    Retrieves login credentials.
    role: 'student' or 'teacher'
    name: The name of the student (for student) or the name of the class (for teacher).
    """
    try:
        if role.lower() == 'student':
            student = Student.objects.filter(surname__icontains=name, school_id=school_id).first()
            if not student:
                student = Student.objects.filter(first_name__icontains=name, school_id=school_id).first()
            
            if not student:
                return json.dumps({"status": "error", "message": f"Could not find student matching '{name}'."})
                
            return json.dumps({
                "status": "success",
                "role": "student",
                "name": student.full_name,
                "username_exam_no": student.exam_no,
                "generated_password": student.generated_password or "No password generated yet."
            })
            
        elif role.lower() == 'teacher':
            # Teachers log in via their class group credentials
            class_group = ClassGroup.objects.filter(name__icontains=name, school_id=school_id).first()
            if not class_group:
                return json.dumps({"status": "error", "message": f"Could not find class '{name}' for the teacher credentials."})
                
            return json.dumps({
                "status": "success",
                "role": "class_teacher",
                "class_name": class_group.name,
                "teacher_name": class_group.class_teacher,
                "generated_password": class_group.generated_password or "No password generated yet."
            })
        else:
            return json.dumps({"status": "error", "message": "Role must be 'student' or 'teacher'."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def mark_attendance_tool(student_name: str, date_str: str, status: str, school_id: int) -> str:
    """
    Marks attendance for a specific student on a given date.
    date_str should be in 'YYYY-MM-DD' format.
    status should be 'present' or 'absent'.
    """
    from datetime import datetime
    try:
        # Validate status
        status = status.lower()
        if status not in ['present', 'absent']:
            return json.dumps({"status": "error", "message": "Status must be 'present' or 'absent'."})
            
        # Parse date
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return json.dumps({"status": "error", "message": "Invalid date format. Use 'YYYY-MM-DD'."})
            
        # Find student
        student = Student.objects.filter(surname__icontains=student_name, school_id=school_id).first()
        if not student:
            student = Student.objects.filter(first_name__icontains=student_name, school_id=school_id).first()
            
        if not student:
            return json.dumps({"status": "error", "message": f"Could not find student matching '{student_name}'."})
            
        # Update or create attendance
        attendance, created = Attendance.objects.update_or_create(
            student=student,
            date=date_obj,
            defaults={'status': status, 'school_id': school_id}
        )
        
        action = "Created" if created else "Updated"
        return json.dumps({
            "status": "success",
            "message": f"Successfully {action.lower()} attendance. {student.full_name} is marked as '{status}' on {date_str}."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def pull_attendance_tool(class_name: str, date_str: str, school_id: int) -> str:
    """
    Retrieves the attendance record for an entire class on a specific date.
    date_str should be in 'YYYY-MM-DD' format.
    """
    from datetime import datetime
    try:
        # Parse date
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return json.dumps({"status": "error", "message": "Invalid date format. Use 'YYYY-MM-DD'."})
            
        # Find class
        class_group = ClassGroup.objects.filter(name__iexact=class_name, school_id=school_id).first()
        if not class_group:
            return json.dumps({"status": "error", "message": f"Could not find class '{class_name}'."})
            
        # Get students in class
        students = Student.objects.filter(class_group=class_group, is_graduated=False, school_id=school_id)
        if not students.exists():
            return json.dumps({"status": "error", "message": f"No active students found in '{class_group.name}'."})
            
        # Get attendance records
        attendance_records = Attendance.objects.filter(
            student__in=students, 
            date=date_obj,
            school_id=school_id
        )
        
        # Map attendance by student ID
        att_map = {att.student_id: att.status for att in attendance_records}
        
        results = []
        present_count = 0
        absent_count = 0
        unmarked_count = 0
        
        for student in students:
            status = att_map.get(student.id, "unmarked")
            if status == "present":
                present_count += 1
            elif status == "absent":
                absent_count += 1
            else:
                unmarked_count += 1
                
            results.append({
                "student_name": student.full_name,
                "exam_no": student.exam_no,
                "status": status
            })
            
        return json.dumps({
            "status": "success",
            "class_name": class_group.name,
            "date": date_str,
            "summary": {
                "total_students": students.count(),
                "present": present_count,
                "absent": absent_count,
                "unmarked": unmarked_count
            },
            "records": results
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def create_cbt_exam_tool(title: str, class_name: str, subject_name: str, session_name: str, term_name: str, duration_minutes: int, pass_mark: int, school_id: int, is_published: bool = False) -> str:
    """
    Creates a new CBT Exam.
    Requires title, class_name, subject_name, session_name, term_name, duration_minutes, pass_mark.
    is_published controls whether students can see it immediately.
    """
    try:
        class_group = ClassGroup.objects.filter(name__iexact=class_name, school_id=school_id).first()
        if not class_group:
            return json.dumps({"status": "error", "message": f"Could not find class '{class_name}'."})
            
        subject = Subject.objects.filter(name__iexact=subject_name, class_group=class_group).first()
        if not subject:
            return json.dumps({"status": "error", "message": f"Could not find subject '{subject_name}' in class '{class_name}'."})
            
        session = AcademicSession.objects.filter(name__iexact=session_name).first()
        if not session:
            # Fallback to latest session
            session = AcademicSession.objects.first()
            if not session:
                return json.dumps({"status": "error", "message": "No academic session found."})
                
        term = Term.objects.filter(name__iexact=term_name).first()
        if not term:
            # Fallback to first term
            term = Term.objects.first()
            if not term:
                return json.dumps({"status": "error", "message": "No term found."})
        
        school = School.objects.get(id=school_id)
        
        exam = Exam.objects.create(
            school=school,
            class_group=class_group,
            subject=subject,
            session=session,
            term=term,
            title=title,
            duration_minutes=duration_minutes,
            pass_mark=pass_mark,
            is_published=is_published
        )
        
        return json.dumps({
            "status": "success",
            "message": f"Successfully created exam '{exam.title}' with code {exam.exam_code}.",
            "exam_code": exam.exam_code
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def add_cbt_question_tool(exam_title: str, question_text: str, option_a: str, option_b: str, option_c: str, option_d: str, correct_answer: str, school_id: int, marks: int = 1) -> str:
    """
    Adds a multiple choice question to an existing CBT Exam.
    correct_answer MUST be exactly one of: 'A', 'B', 'C', 'D'.
    """
    try:
        correct_answer = correct_answer.strip().upper()
        if correct_answer not in ['A', 'B', 'C', 'D']:
            return json.dumps({"status": "error", "message": "correct_answer must be A, B, C, or D."})
            
        exam = Exam.objects.filter(title__icontains=exam_title, school_id=school_id).first()
        if not exam:
            return json.dumps({"status": "error", "message": f"Could not find an exam matching title '{exam_title}'."})
            
        question = Question.objects.create(
            exam=exam,
            question_text=question_text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=option_d,
            correct_answer=correct_answer,
            marks=marks
        )
        
        return json.dumps({
            "status": "success",
            "message": f"Successfully added question to exam '{exam.title}'. Total questions now: {exam.total_questions}."
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def publish_result_tool(term_name: str, session_name: str, publish_scope: str, school_id: int, class_name: str = None, student_name: str = None) -> str:
    """
    Publishes results, deducting PINs if school.payment_active is true.
    publish_scope must be 'school', 'class', or 'student'.
    If 'class', provide class_name. If 'student', provide student_name.
    """
    try:
        school = School.objects.get(id=school_id)
        term = Term.objects.filter(name__iexact=term_name).first()
        session = AcademicSession.objects.filter(name__iexact=session_name).first()
        
        if not term or not session:
            return json.dumps({"status": "error", "message": "Invalid term or session name."})
            
        students_to_publish = []
        
        if publish_scope == "school":
            existing = PublishedResult.objects.filter(school=school, term=term, session=session, scope="school")
            if existing.exists():
                return json.dumps({"status": "error", "message": "School results are already published."})
                
            published_classes = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope__in=["class", "school"]
            ).values_list("class_group_id", flat=True)
            
            unpublished_classes = ClassGroup.objects.filter(school=school).exclude(id__in=published_classes)
            if not unpublished_classes.exists():
                return json.dumps({"status": "error", "message": "All classes already published."})
                
            published_students = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope="student"
            ).values_list("student_id", flat=True)
            
            students_to_publish = Student.objects.filter(school=school, class_group__in=unpublished_classes).exclude(id__in=published_students)
            
        elif publish_scope == "class":
            if not class_name:
                return json.dumps({"status": "error", "message": "class_name is required for 'class' scope."})
            class_group = ClassGroup.objects.filter(name__iexact=class_name, school=school).first()
            if not class_group:
                return json.dumps({"status": "error", "message": "Class not found."})
                
            existing = PublishedResult.objects.filter(school=school, term=term, session=session, scope__in=["class", "school"], class_group=class_group)
            if existing.exists():
                return json.dumps({"status": "error", "message": "Class results are already published."})
                
            published_students = PublishedResult.objects.filter(
                school=school, term=term, session=session, scope="student"
            ).values_list("student_id", flat=True)
            
            students_to_publish = Student.objects.filter(school=school, class_group=class_group).exclude(id__in=published_students)
            
        elif publish_scope == "student":
            if not student_name:
                return json.dumps({"status": "error", "message": "student_name is required for 'student' scope."})
            student = Student.objects.filter(full_name__icontains=student_name, school=school).first()
            if not student:
                return json.dumps({"status": "error", "message": "Student not found."})
                
            existing = PublishedResult.objects.filter(school=school, term=term, session=session, student=student)
            if existing.exists():
                return json.dumps({"status": "error", "message": "Student result already published."})
                
            students_to_publish = [student]
        else:
            return json.dumps({"status": "error", "message": "Invalid publish_scope."})
            
        if not isinstance(students_to_publish, list):
            students_to_publish = list(students_to_publish)
            
        total_students = len(students_to_publish)
        if total_students == 0:
            return json.dumps({"status": "error", "message": "No students available to publish (already published)."})
            
        available_pins = Pin.objects.filter(school=school, used=False).order_by("created_at")
        if school.payment_active and total_students > available_pins.count():
            return json.dumps({"status": "error", "message": f"Not enough unused pins. Need: {total_students}, Available: {available_pins.count()}"})
            
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
                PublishedResult.objects.get_or_create(
                    school=school,
                    term=term,
                    session=session,
                    scope=publish_scope,
                    class_group=student_obj.class_group,
                    student=student_obj
                )
                
        return json.dumps({"status": "success", "message": f"Successfully published results for {total_students} students."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def send_report_to_parent_tool(class_name: str, session_name: str, term_name: str, school_id: int) -> str:
    """
    Emails PDF report cards to parents for a given class.
    """
    try:
        school = School.objects.get(id=school_id)
        term = Term.objects.filter(name__iexact=term_name).first()
        session = AcademicSession.objects.filter(name__iexact=session_name).first()
        class_group = ClassGroup.objects.filter(name__iexact=class_name, school=school).first()
        
        if not all([term, session, class_group]):
            return json.dumps({"status": "error", "message": "Invalid term, session, or class name."})
            
        published_student_ids = PublishedResult.objects.filter(
            school=school, session=session, term=term, class_group=class_group
        ).values_list("student_id", flat=True)
        
        students = Student.objects.filter(id__in=published_student_ids)
        if not students.exists():
            return json.dumps({"status": "error", "message": "No published results found for this class."})
            
        sent = 0
        failed = 0
        
        base_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')
        if not base_url.endswith('/'):
            base_url += '/'
            
        for student in students:
            if not student.parent_email:
                failed += 1
                continue
                
            context = reportcard_view_context(student, session, term)
            html_string = render_to_string("score/reportcard.html", context)
            
            pdf_buffer = BytesIO()
            HTML(
                string=html_string, 
                base_url=base_url,
                url_fetcher=weasyprint_url_fetcher
            ).write_pdf(pdf_buffer)
            
            html_body = render_to_string("score/email_reportcard_message.html", {"student": student})
            text_body = strip_tags(html_body)
            
            email = EmailMultiAlternatives(
                subject=f"{student.full_name} - {term.name} Report Card",
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[student.parent_email],
            )
            email.attach_alternative(html_body, "text/html")
            pdf_filename = f"{student.full_name.replace(' ', '_')}_ReportCard.pdf"
            email.attach(pdf_filename, pdf_buffer.getvalue(), "application/pdf")
            email.send()
            sent += 1
            
        return json.dumps({"status": "success", "message": f"Successfully sent {sent} emails. {failed} skipped (no email)."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

# Mapping tool names to functions for the LangChain agent
TOOLS_MAP = {
    "get_student_report_cards_pdf": get_student_report_cards_pdf,
    "get_my_results": get_my_results,
    "get_class_performance": get_class_performance,
    "fetch_billing_receipts": fetch_billing_receipts,
    "add_class_tool": add_class_tool,
    "add_subject_tool": add_subject_tool,
    "add_student_tool": add_student_tool,
    "get_graduated_students_tool": get_graduated_students_tool,
    "promote_students_tool": promote_students_tool,
    "get_class_view_tool": get_class_view_tool,
    "get_student_analytics_tool": get_student_analytics_tool,
    "get_login_credentials_tool": get_login_credentials_tool,
    "mark_attendance_tool": mark_attendance_tool,
    "pull_attendance_tool": pull_attendance_tool,
    "create_cbt_exam_tool": create_cbt_exam_tool,
    "add_cbt_question_tool": add_cbt_question_tool,
    "publish_result_tool": publish_result_tool,
    "send_report_to_parent_tool": send_report_to_parent_tool,
}
