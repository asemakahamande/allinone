from django.db import models
from django.contrib.auth.models import User
import uuid


TERMS = [
    ("1st Term", "1st Term"),
    ("2nd Term", "2nd Term"),
    ("3rd Term", "3rd Term"),
]


# ---------------------------------------
# NEW CLASS MODEL (For class dropdown)
# ---------------------------------------
class ClassLevel(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Exam(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    term = models.CharField(max_length=20, choices=TERMS)
    session = models.CharField(max_length=12)  # e.g. 2024/2025
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    exam_code = models.CharField(max_length=30, unique=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=30)

    def save(self, *args, **kwargs):
        if not self.exam_code:
            base = (self.subject.name[:3] if self.subject.name else 'EXM').upper()
            self.exam_code = f"{base}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subject.name} - {self.term} - {self.session}"


class Question(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    image = models.ImageField(upload_to='questions/', blank=True, null=True)
    option_a = models.CharField(max_length=255)
    option_b = models.CharField(max_length=255)
    option_c = models.CharField(max_length=255)
    option_d = models.CharField(max_length=255)
    correct_answer = models.CharField(
        max_length=1,
        choices=[
            ('A', 'A'),
            ('B', 'B'),
            ('C', 'C'),
            ('D', 'D')
        ]
    )
    explanation = models.TextField(blank=True, null=True)

    def options(self):
        return [
            self.option_a,
            self.option_b,
            self.option_c,
            self.option_d
        ]

    def __str__(self):
        return self.question_text[:50]


class StudentResult(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    student_name = models.CharField(max_length=200)

    # UPDATED: Now uses ForeignKey instead of CharField
    student_class = models.ForeignKey(ClassLevel, on_delete=models.SET_NULL, null=True)

    score = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def percentage(self):
        return (self.score / self.total) * 100 if self.total else 0

    def __str__(self):
        return f"{self.student_name} - {self.exam.exam_code} - {self.score}/{self.total}"


