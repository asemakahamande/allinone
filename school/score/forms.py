

from django import forms
from .models import School
from django.contrib.auth.hashers import make_password


def get_country_choices():
    from .location_data import COUNTRY_DATA
    choices = [("", "Select Country")]
    choices.extend((name, name) for name in sorted(COUNTRY_DATA.keys()))
    return choices


class SchoolRegistrationForm(forms.ModelForm):
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Confirm Password"}),
        label="Confirm Password"
    )
    country = forms.ChoiceField(
        choices=get_country_choices(),
        required=True,
        widget=forms.Select(attrs={
            "class": "border border-gray-300 rounded-lg w-full p-2",
            "id": "id_country",
        }),
    )
    state = forms.ChoiceField(
        choices=[("", "Select State/Province")],
        required=True,
        widget=forms.Select(attrs={
            "class": "border border-gray-300 rounded-lg w-full p-2",
            "id": "id_state",
        }),
    )
    local_government = forms.ChoiceField(
        choices=[("", "Select Local Government")],
        required=True,
        widget=forms.Select(attrs={
            "class": "border border-gray-300 rounded-lg w-full p-2",
            "id": "id_local_government",
        }),
    )

    class Meta:
        model = School
        fields = [
            "name", "country", "state", "local_government", "phone", "address",
            "registration_number", "logo",
            "admin_name", "admin_phone", "website",
            "owner_first_name", "owner_middle_name", "owner_surname", "owner_gender",
            "email", "password"
        ]
        widgets = {
            "password": forms.PasswordInput(attrs={"placeholder": "Enter Password"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["registration_number"].required = False

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        # Ensure password confirmation
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")

        return cleaned_data

    def save(self, commit=True):
        school = super().save(commit=False)
        # Hash the password before saving
        school.password = make_password(self.cleaned_data["password"])
        if commit:
            school.save()
        return school

from django import forms
from .models import ClassGroup, Subject, Student

# class ClassGroupForm(forms.ModelForm):
#     class Meta:
#         model = ClassGroup
#         fields = ['name', 'class_teacher', 'scoring_system']


from django import forms
from django.forms import inlineformset_factory
from .models import ClassGroup, CustomScoringSystem

class ClassGroupForm(forms.ModelForm):
    class Meta:
        model = ClassGroup
        fields = ['name', 'class_teacher', 'scoring_system']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'border border-gray-300 rounded-lg w-full p-2'}),
            'class_teacher': forms.TextInput(attrs={'class': 'border border-gray-300 rounded-lg w-full p-2'}),
            'scoring_system': forms.Select(attrs={'class': 'border border-gray-300 rounded-lg w-full p-2'}),
        }

# Formset for custom scoring
CustomScoringSystemFormSet = inlineformset_factory(
    ClassGroup,
    CustomScoringSystem,
    fields=('name', 'components'),  # use 'components' as in your model, not 'score'
    extra=5,
    can_delete=True,
    widgets={
        'name': forms.TextInput(attrs={'class': 'border p-2 rounded w-full'}),
        'components': forms.TextInput(attrs={'class': 'border p-2 rounded w-full'}),
    }
)





class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name', 'class_group']




class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        exclude = ["school", "base_student", "exam_no"]  # exam_no is auto-generated

        widgets = {
            "surname": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2", "required": "required"}),
            "first_name": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2", "required": "required"}),
            "middle_name": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "gender": forms.RadioSelect(attrs={"class": "form-radio text-blue-600"}),
            "class_group": forms.Select(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "session": forms.Select(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "term": forms.Select(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "parent_surname": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2", "required": "required"}),
            "parent_first_name": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2", "required": "required"}),
            "parent_middle_name": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "parent_email": forms.EmailInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "parent_phone_number": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "location": forms.TextInput(attrs={"class": "border border-gray-300 rounded-lg w-full p-2"}),
            "address": forms.Textarea(attrs={"class": "border border-gray-300 rounded-lg w-full p-2", "rows": 3}),
            "is_graduated": forms.CheckboxInput(attrs={"class": "form-checkbox text-green-600"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-checkbox text-green-600"}),
        }

    def __init__(self, *args, **kwargs):
        school = kwargs.pop('school', None)
        super().__init__(*args, **kwargs)

        if school:
            # Filter class groups
            self.fields['class_group'].queryset = ClassGroup.objects.filter(school=school).order_by('name')

            # Optional: Set default/current session
            try:
                # If you have a way to get current session (e.g., from settings or latest)
                current_session = AcademicSession.objects.order_by('-name').first()
                if current_session:
                    self.fields['session'].initial = current_session
            except:
                pass

        # Ensure session has options
        self.fields['session'].queryset = AcademicSession.objects.all().order_by('-name')
        if 'session' in self.fields and not self.fields['session'].queryset.exists():
            self.fields['session'].empty_label = "No sessions available"

        # Ensure term has options
        from .models import Term
        self.fields['term'].queryset = Term.objects.all().order_by('id')
        if 'term' in self.fields and not self.fields['term'].queryset.exists():
            self.fields['term'].empty_label = "No terms available"

    # Extra validation
    def clean(self):
        cleaned_data = super().clean()
        session = cleaned_data.get('session')
        term = cleaned_data.get('term')
        if not session:
            self.add_error('session', "Please select an academic session.")
        if not term:
            self.add_error('term', "Please select a term.")
        return cleaned_data
    
from django import forms
from .models import ClassGroup, Subject, Student

class ClassGroupForm(forms.ModelForm):
    class Meta:
        model = ClassGroup
        fields = ['name', 'class_teacher', 'scoring_system']
        widgets = {
        'name': forms.TextInput(attrs={
        'class': 'border border-gray-300 rounded-lg w-full p-2'
        }),
        'class_teacher': forms.TextInput(attrs={
        'class': 'border border-gray-300 rounded-lg w-full p-2'
        }),
        'scoring_system': forms.Select(attrs={
        'class': 'border border-gray-300 rounded-lg w-full p-2'
        }),
        }



class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "class_group"]
        widgets = {
        "name": forms.TextInput(attrs={
        "class": "border border-gray-300 rounded-lg w-full p-2"
        }),
        "class_group": forms.Select(attrs={
        "class": "border border-gray-300 rounded-lg w-full p-2"
        }),
        }



# forms.py
from django import forms
from .models import Staff

class StaffForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ["firstname", "surname", "middlename", "phone_number", "email", "qualification", "status"]
        widgets = {
            "status": forms.Select(attrs={"class": "border p-2 rounded w-full"}),
            "firstname": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "surname": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "middlename": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "phone_number": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "email": forms.EmailInput(attrs={"class": "border p-2 rounded w-full"}),
            "qualification": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
        }

from django import forms
from .models import Meeting, Staff

from django import forms
from .models import Meeting, Staff

class MeetingForm(forms.ModelForm):
    invited_staff = forms.ModelMultipleChoiceField(
        queryset=Staff.objects.none(),  # filtered later in view
        widget=forms.CheckboxSelectMultiple(attrs={
            "class": "space-y-2"  # spacing between checkboxes
        }),
        required=False
    )

    class Meta:
        model = Meeting
        fields = ["title", "agenda", "date", "invited_staff"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Enter meeting title"
            }),
            "agenda": forms.Textarea(attrs={
                "class": "border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500",
                "placeholder": "Enter meeting agenda",
                "rows": 4
            }),
            "date": forms.DateTimeInput(attrs={
                "type": "datetime-local",
                "class": "border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
            }),
        }




from django import forms
from .models import Timetable

class TimetableForm(forms.ModelForm):
    class Meta:
        model = Timetable
        fields = ["class_name", "subject", "teacher", "day", "start_time", "end_time"]
        widgets = {
            "class_name": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "subject": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "teacher": forms.TextInput(attrs={"class": "border p-2 rounded w-full"}),
            "day": forms.Select(attrs={"class": "border p-2 rounded w-full"}),
            "start_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "border p-2 rounded w-full",
                    "step": "60"  # 1-minute increments
                }
            ),
            "end_time": forms.TimeInput(
                attrs={
                    "type": "time",
                    "class": "border p-2 rounded w-full",
                    "step": "60"
                }
            ),
        }





# for cbt exam forms 


# Add these forms to your score app forms.py

from django import forms
from .models import Exam, Question, CBTResult, ClassGroup, Subject, AcademicSession, Term


class CBTExamForm(forms.ModelForm):
    """
    Form for creating/editing CBT exams
    """
    class Meta:
        model = Exam
        fields = [
            'class_group', 'subject', 'session', 'term',
            'title', 'description', 'duration_minutes', 
            'pass_mark', 'is_active', 'is_published'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., First Term Mathematics Exam'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief description of the exam...'
            }),
            'class_group': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'session': forms.Select(attrs={'class': 'form-select'}),
            'term': forms.Select(attrs={'class': 'form-select'}),
            'duration_minutes': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '5',
                'max': '300',
                'placeholder': '60'
            }),
            'pass_mark': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '100',
                'placeholder': '50'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'class_group': 'Class',
            'duration_minutes': 'Duration (minutes)',
            'pass_mark': 'Pass Mark (%)',
            'is_active': 'Active',
            'is_published': 'Published (students can see)',
        }
    
    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        if school:
            # Filter class groups and subjects by school
            self.fields['class_group'].queryset = ClassGroup.objects.filter(
                school=school
            ).order_by('name')
            
            self.fields['subject'].queryset = Subject.objects.filter(
                class_group__school=school
            ).distinct().order_by('name')
        
        # Set default values
        self.fields['duration_minutes'].initial = 60
        self.fields['pass_mark'].initial = 50
        self.fields['is_active'].initial = True


class CBTQuestionForm(forms.ModelForm):
    """
    Form for creating/editing questions
    """
    class Meta:
        model = Question
        fields = [
            'question_text', 'image',
            'option_a', 'option_b', 'option_c', 'option_d',
            'correct_answer', 'explanation', 'marks', 'order'
        ]
        widgets = {
            'question_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter your question here...'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'option_a': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Option A'
            }),
            'option_b': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Option B'
            }),
            'option_c': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Option C'
            }),
            'option_d': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Option D'
            }),
            'correct_answer': forms.Select(attrs={'class': 'form-select'}),
            'explanation': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Explain why this is the correct answer (optional)'
            }),
            'marks': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '10'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': 'Question order/number'
            }),
        }
        labels = {
            'question_text': 'Question',
            'image': 'Image (optional)',
            'option_a': 'Option A',
            'option_b': 'Option B',
            'option_c': 'Option C',
            'option_d': 'Option D',
            'correct_answer': 'Correct Answer',
            'explanation': 'Explanation (optional)',
            'marks': 'Marks/Points',
            'order': 'Question Number',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['marks'].initial = 1
        self.fields['order'].initial = 0


class QuickQuestionForm(forms.Form):
    """
    Quick form for adding questions without using ModelForm
    Used in the create_cbt_question view
    """
    question_text = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter your question here...',
            'required': True
        }),
        label='Question'
    )
    
    image = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
        label='Image (optional)'
    )
    
    option_a = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Option A',
            'required': True
        }),
        label='Option A'
    )
    
    option_b = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Option B',
            'required': True
        }),
        label='Option B'
    )
    
    option_c = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Option C',
            'required': True
        }),
        label='Option C'
    )
    
    option_d = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Option D',
            'required': True
        }),
        label='Option D'
    )
    
    correct_answer = forms.ChoiceField(
        choices=[
            ('A', 'Option A'),
            ('B', 'Option B'),
            ('C', 'Option C'),
            ('D', 'Option D'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Correct Answer'
    )
    
    explanation = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Explain why this is the correct answer (optional)'
        }),
        label='Explanation (optional)'
    )
    
    marks = forms.IntegerField(
        initial=1,
        min_value=1,
        max_value=10,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'max': '10'
        }),
        label='Marks/Points'
    )
    
    order = forms.IntegerField(
        initial=0,
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'placeholder': 'Question order/number'
        }),
        label='Question Number'
    )


class CBTExamFilterForm(forms.Form):
    """
    Form for filtering exams in lists
    """
    session = forms.ModelChoiceField(
        queryset=AcademicSession.objects.all().order_by('-name'),
        required=False,
        empty_label='All Sessions',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    term = forms.ModelChoiceField(
        queryset=Term.objects.all(),
        required=False,
        empty_label='All Terms',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    class_group = forms.ModelChoiceField(
        queryset=ClassGroup.objects.all().order_by('name'),
        required=False,
        empty_label='All Classes',
        label='Class',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.all().order_by('name'),
        required=False,
        empty_label='All Subjects',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    status = forms.ChoiceField(
        choices=[
            ('', 'All Status'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('published', 'Published'),
            ('unpublished', 'Unpublished'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        if school:
            self.fields['class_group'].queryset = ClassGroup.objects.filter(
                school=school
            ).order_by('name')
            
            self.fields['subject'].queryset = Subject.objects.filter(
                class_group__school=school
            ).distinct().order_by('name')


class CBTResultFilterForm(forms.Form):
    """
    Form for filtering CBT results
    """
    session = forms.ModelChoiceField(
        queryset=AcademicSession.objects.all().order_by('-name'),
        required=False,
        empty_label='All Sessions',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    term = forms.ModelChoiceField(
        queryset=Term.objects.all(),
        required=False,
        empty_label='All Terms',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    class_group = forms.ModelChoiceField(
        queryset=ClassGroup.objects.all().order_by('name'),
        required=False,
        empty_label='All Classes',
        label='Class',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.all().order_by('name'),
        required=False,
        empty_label='All Subjects',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    exam = forms.ModelChoiceField(
        queryset=Exam.objects.all().order_by('-created_at'),
        required=False,
        empty_label='All Exams',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Search by student name or exam number...'
        })
    )
    
    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        if school:
            self.fields['class_group'].queryset = ClassGroup.objects.filter(
                school=school
            ).order_by('name')
            
            self.fields['subject'].queryset = Subject.objects.filter(
                class_group__school=school
            ).distinct().order_by('name')
            
            self.fields['exam'].queryset = Exam.objects.filter(
                school=school
            ).order_by('-created_at')