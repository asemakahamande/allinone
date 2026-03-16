from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Subject, Exam, Question, StudentResult, ClassLevel


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('subject', 'term', 'session', 'exam_code', 'created_by', 'duration_minutes')
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('short_text', 'exam', 'correct_answer')

    def short_text(self, obj):
        return obj.question_text[:40]

    short_text.short_description = "Question"


@admin.register(StudentResult)
class StudentResultAdmin(admin.ModelAdmin):
    list_display = ('student_name', 'exam', 'score', 'total', 'created_at')


# ✅ Register ClassLevel to appear in admin
@admin.register(ClassLevel)
class ClassLevelAdmin(admin.ModelAdmin):
    list_display = ('name',)