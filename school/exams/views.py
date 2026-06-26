from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from io import BytesIO
import base64

try:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
except ImportError:
    pass

from .models import Exam, Question, StudentResult, ClassLevel
from .forms import ExamLoginForm


# ------------------------------------------
# LOGIN PAGE WITH CLASS DROPDOWN
# ------------------------------------------
from django.shortcuts import render, redirect
from .forms import ExamLoginForm
from .models import Exam, ClassLevel

def exam_login(request):
    error = None

    if request.method == 'POST':
        form = ExamLoginForm(request.POST)
        if form.is_valid():
            student_name = form.cleaned_data['student_name']
            class_obj = form.cleaned_data['student_class']
            exam_code = form.cleaned_data['exam_code']

            try:
                exam = Exam.objects.get(exam_code=exam_code)

                # Save details in session
                request.session['student_name'] = student_name
                request.session['student_class_id'] = class_obj.id
                request.session['exam_id'] = exam.id

                return redirect('exams:take_exam', exam_id=exam.id)
            except Exam.DoesNotExist:
                error = 'Invalid exam code'
    else:
        form = ExamLoginForm()

    return render(request, 'exams/exam_login.html', {'form': form, 'error': error})



# ------------------------------------------
# EXAM PAGE – PROCESS SUBMISSION
# ------------------------------------------
from django.shortcuts import render, redirect, get_object_or_404
from io import BytesIO
import base64
try:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
except ImportError:
    pass

from .models import Exam, Question, StudentResult, ClassLevel


def take_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)

    if 'student_name' not in request.session:
        return redirect('exams:exam_login')

    questions = exam.questions.all()
    duration_seconds = exam.duration_minutes * 60

    if request.method != 'POST':
        # Render exam page
        return render(request, 'exams/take_exam.html', {
            'exam': exam,
            'question_data': [{
                'id': q.id,
                'question': q.question_text,
                'image': q.image,
                'options': [(chr(65+i), opt) for i, opt in enumerate(q.options())],
                'plain_options': q.options(),
            } for q in questions],
            'duration_seconds': duration_seconds,
        })

    # --------------------------
    # PROCESS SUBMISSION
    # --------------------------
    score = 0
    total = questions.count()
    detail_rows = []

    for q in questions:
        user_answer = request.POST.get(str(q.id))
        plain_options = q.options()

        # Convert clicked text into A/B/C/D
        if user_answer in plain_options:
            user_key = chr(65 + plain_options.index(user_answer))
        else:
            user_key = None

        is_correct = (user_key == q.correct_answer)

        if is_correct:
            score += 1

        # Get the text of the correct option
        correct_index = ord(q.correct_answer) - 65 if q.correct_answer else None
        correct_option_text = ''
        if correct_index is not None and 0 <= correct_index < len(plain_options):
            correct_option_text = f"{q.correct_answer}. {plain_options[correct_index]}"

        detail_rows.append({
            'question': q.question_text,
            'image': q.image,
            'options': [(chr(65+i), opt) for i, opt in enumerate(plain_options)],
            'plain_options': plain_options,
            'your_answer': user_answer or 'No answer',
            'correct_answer': q.correct_answer,
            'correct_option_text': correct_option_text,
            'is_correct': is_correct,
            'explanation': q.explanation,
        })

    # --------------------------
    # SAVE STUDENT RESULT
    # --------------------------
    student_name = request.session['student_name']
    class_id = request.session.get('student_class_id')
    student_class_obj = None

    if class_id:
        student_class_obj = ClassLevel.objects.get(id=class_id)

    StudentResult.objects.create(
        student_name=student_name,
        student_class=student_class_obj,
        exam=exam,
        score=score,
        total=total
    )

    # --------------------------
    # GENERATE PIE CHART
    # --------------------------
    correct_percentage = round((score / total) * 100)
    wrong_percentage = 100 - correct_percentage

    fig, ax = plt.subplots(figsize=(4, 4))
    ax.pie(
        [score, total - score],
        labels=[f"{correct_percentage}% Correct", f"{wrong_percentage}% Wrong"],
        startangle=90,
        textprops={'fontsize': 12, 'weight': 'bold'}
    )
    ax.axis('equal')

    buffer = BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    buffer.seek(0)
    chart_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    buffer.close()
    plt.close(fig)

    # --------------------------
    # RENDER RESULT PAGE
    # --------------------------
    return render(request, 'exams/result.html', {
        'exam': exam,
        'score': score,
        'total': total,
        'question_results': detail_rows,
        'chart_base64': chart_base64,
        'student_name': student_name,
        'student_class': student_class_obj.name if student_class_obj else "",
        'correct_percentage': correct_percentage,
        'wrong_percentage': wrong_percentage,
    })



# ------------------------------------------
# TEACHER DASHBOARD
# ------------------------------------------
def teacher_dashboard(request):
    exams = Exam.objects.all()
    return render(request, 'exams/teacher_dashboard.html', {'exams': exams})

@login_required
def exam_list(request):
    exams = Exam.objects.all().order_by('-id')
    return render(request, 'exams/exam_list.html', {'exams': exams})


from .models import StudentResult, ClassLevel, Exam, Subject, TERMS

def student_results(request):
    """
    Display student results filtered by session, term, class, subject,
    with optional search by student name.
    """
    # Filter options
    sessions = StudentResult.objects.values_list('exam__session', flat=True).distinct()
    classes = ClassLevel.objects.all().order_by('name')
    subjects = Subject.objects.all().order_by('name')
    terms = [term[0] for term in TERMS]

    # Get selected filters from GET parameters
    selected_session = request.GET.get('session', '')
    selected_term = request.GET.get('term', '')
    selected_class_id = request.GET.get('class', '')
    selected_subject_id = request.GET.get('subject', '')
    search_name = request.GET.get('search', '').strip()

    # Base queryset
    results = StudentResult.objects.all()

    # Apply filters
    if selected_session:
        results = results.filter(exam__session=selected_session)
    if selected_term:
        results = results.filter(exam__term=selected_term)
    if selected_class_id:
        results = results.filter(student_class_id=selected_class_id)
    if selected_subject_id:
        results = results.filter(exam__subject_id=selected_subject_id)
    if search_name:
        results = results.filter(student_name__icontains=search_name)

    # Sort alphabetically by student name
    results = results.order_by('student_name')

    context = {
        'results': results,
        'sessions': sessions,
        'classes': classes,
        'subjects': subjects,
        'terms': terms,
        'selected_session': selected_session,
        'selected_term': selected_term,
        'selected_class_id': selected_class_id,
        'selected_subject_id': selected_subject_id,
        'search_name': search_name,
    }

    return render(request, 'exams/student_results.html', context)


# exams/views.py
from django.shortcuts import render, redirect
from .forms import ExamForm, QuestionForm, StudentResultForm
from .models import Exam, Question, StudentResult

def create_exam(request):
    if request.method == "POST":
        form = ExamForm(request.POST)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.created_by = request.user
            exam.save()
            return redirect('exams:exam_list')  # <- use app namespace
    else:
        form = ExamForm()
    return render(request, 'exams/create_exam.html', {'form': form})


def create_question(request):
    if request.method == "POST":
        form = QuestionForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('exams:question_list')
    else:
        form = QuestionForm()
    return render(request, 'exams/create_question.html', {'form': form})


def create_result(request):
    if request.method == "POST":
        form = StudentResultForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('result_list')
    else:
        # form = StudentResultForm()
        form = QuestionForm()
    return render(request, 'exams/create_result.html', {'form': form})

# exams/views.py
from django.shortcuts import render, redirect
from .forms import ClassLevelForm, SubjectForm, ExamForm, QuestionForm, StudentResultForm


# exams/views.py
from django.shortcuts import render, redirect
from .forms import ClassLevelForm
from .models import ClassLevel

def create_classlevel(request):
    if request.method == "POST":
        form = ClassLevelForm(request.POST)
        if form.is_valid():
            form.save()
            print("Saved! Redirecting...")
            return redirect('exams:classlevel_list')
        else:
            print("Form errors:", form.errors)
    else:
        form = ClassLevelForm()
    return render(request, 'exams/create_classlevel.html', {'form': form})


def create_subject(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('exams:subject_list')  # <- include the app namespace
    else:
        form = SubjectForm()
    return render(request, 'exams/create_subject.html', {'form': form})

# exams/views.py
from .models import ClassLevel

def classlevel_list(request):
    classes = ClassLevel.objects.all().order_by('name')
    return render(request, 'exams/classlevel_list.html', {'classes': classes})

# exams/views.py
from .models import Subject
from django.shortcuts import render

def subject_list(request):
    subjects = Subject.objects.all().order_by('name')
    return render(request, 'exams/subject_list.html', {'subjects': subjects})


def exam_list(request):
    exams = Exam.objects.all().order_by('-id')  # newest first
    return render(request, 'exams/exam_list.html', {'exams': exams})

# exams/views.py

from .models import Question

def question_list(request):
    questions = Question.objects.all().order_by('-id')  # newest first
    return render(request, 'exams/question_list.html', {'questions': questions})