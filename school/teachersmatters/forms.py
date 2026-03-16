from django import forms
from .models import Teacher, Employer

class TeacherRegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = Teacher
        fields = '__all__'

class EmployerRegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = Employer
        fields = '__all__'
