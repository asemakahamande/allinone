from django import forms
from .models import Exam, ClassLevel, Subject


class ExamLoginForm(forms.Form):
    student_name = forms.CharField(
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter your full name",
            "class": "form-control"
        })
    )

    # UPDATED — NOW A DROPDOWN OF CLASS LEVELS
    student_class = forms.ModelChoiceField(
        queryset=ClassLevel.objects.all().order_by("name"),
        required=True,
        empty_label="Select your class",
        widget=forms.Select(attrs={
            "class": "form-control"
        })
    )

    exam_code = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter exam code",
            "class": "form-control"
        })
    )


# class QuestionForm(forms.Form):
#     """
#     Empty because questions are dynamically rendered.
#     """
#     pass
# exams/forms.py
from django import forms
from .models import Exam, Question, StudentResult

class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ['subject', 'term', 'session', 'duration_minutes']


class StudentResultForm(forms.ModelForm):
    class Meta:
        model = StudentResult
        fields = ['exam', 'student_name', 'student_class', 'score', 'total']
from django import forms
from .models import Exam, Question

class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ['subject', 'term', 'session', 'duration_minutes']
        widgets = {
            'subject': forms.Select(attrs={
                'class': 'w-full border rounded-lg px-3 py-2'
            }),
            'term': forms.Select(attrs={
                'class': 'w-full border rounded-lg px-3 py-2'
            }),
            'session': forms.TextInput(attrs={
                'class': 'w-full border rounded-lg px-3 py-2',
                'placeholder': '2024/2025'
            }),
            'duration_minutes': forms.NumberInput(attrs={
                'class': 'w-full border rounded-lg px-3 py-2'
            }),
        }


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = [
            'exam',            # Add this!
            'question_text',
            'image',
            'option_a',
            'option_b',
            'option_c',
            'option_d',
            'correct_answer',
            'explanation'
        ]
        widgets = {
            'exam': forms.Select(attrs={'class': 'w-full border rounded-lg px-3 py-2'}),
            'question_text': forms.Textarea(attrs={'class': 'w-full border rounded-lg px-3 py-2', 'rows': 4}),
            'option_a': forms.TextInput(attrs={'class': 'w-full border rounded-lg px-3 py-2'}),
            'option_b': forms.TextInput(attrs={'class': 'w-full border rounded-lg px-3 py-2'}),
            'option_c': forms.TextInput(attrs={'class': 'w-full border rounded-lg px-3 py-2'}),
            'option_d': forms.TextInput(attrs={'class': 'w-full border rounded-lg px-3 py-2'}),
            'correct_answer': forms.Select(attrs={'class': 'w-full border rounded-lg px-3 py-2'}),
            'explanation': forms.Textarea(attrs={'class': 'w-full border rounded-lg px-3 py-2', 'rows': 2}),
        }


class ClassLevelForm(forms.ModelForm):
    class Meta:
        model = ClassLevel
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500',
                'placeholder': 'e.g JSS 1'
            })
        }
class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-green-500',
                'placeholder': 'e.g Mathematics'
            })
        }

