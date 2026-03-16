from django.contrib import admin
from .models import (
    Student, Subject, Score, ClassGroup, SchoolSetting,
    AffectiveTrait, PsychomotorSkill, Term, AcademicSession,
    GraduationRecord, School  # ✅ School for registered schools count
)

# ===========================
# SCHOOL ADMIN (registered schools)
# ===========================
@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = (
        "name", "registration_number", "country", "state",
        "admin_name", "email", "phone", "payment_active", "created_at"
    )
    list_editable = ("payment_active",)  # checkbox editable in list view
    list_filter = ("country", "state", "payment_active", "created_at")
    search_fields = ("name", "registration_number", "admin_name", "email")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    actions = ["activate_payment", "deactivate_payment"]

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["total_schools"] = School.objects.count()
        return super().changelist_view(request, extra_context=extra_context)

    @admin.action(description="Activate payment for selected schools")
    def activate_payment(self, request, queryset):
        updated = queryset.update(payment_active=True)
        self.message_user(request, f"Payment activated for {updated} school(s).")

    @admin.action(description="Deactivate payment for selected schools")
    def deactivate_payment(self, request, queryset):
        updated = queryset.update(payment_active=False)
        self.message_user(request, f"Payment deactivated for {updated} school(s).")


# Register models without custom admin classes
admin.site.register(Student)
admin.site.register(Subject)

# ===========================
# CLASS GROUP ADMIN
# ===========================
@admin.register(ClassGroup)
class ClassGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'class_teacher', 'scoring_system', 'school')
    list_filter = ('scoring_system',)
    search_fields = ('name', 'class_teacher')
    ordering = ('name',)
    fields = ('name', 'class_teacher', 'scoring_system', 'school')  # include school



# ===========================
# SCORE ADMIN
# ===========================
# @admin.register(Score)
# class ScoreAdmin(admin.ModelAdmin):
#     list_display = (
#         'student', 'subject',
#         'ca1', 'ca2', 'affective', 'psychomotor', 'exam',
#         'total', 'max_score', 'min_score', 'avg_score',
#         'position', 'ordinal_position',
#         'grade', 'remark'
#     )
#     list_filter = ('subject', 'student')
#     ordering = ('subject__name', '-total')

@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'subject', 'term', 'session',
        'ca1', 'ca2', 'ca3', 'exam',
        'total', 'max_score', 'min_score', 'avg_score',
        'position', 'ordinal_position',
        'grade', 'remark'
    )
    list_filter = ('subject', 'term', 'session')
    search_fields = ('student__surname', 'student__first_name', 'subject__name')
    ordering = ('subject__name', '-total')
# ===========================
# SCHOOL SETTINGS ADMIN
# ===========================
@admin.register(SchoolSetting)
class SchoolSettingAdmin(admin.ModelAdmin):
    list_display = ("name", "exam_year", "exam_month", "school_open", "updated_at", "term_closes_on", "next_term_begins")
    list_filter = ("exam_year", "exam_month")
    ordering = ("-updated_at",)


# ===========================
# AFFECTIVE TRAIT ADMIN
# ===========================
@admin.register(AffectiveTrait)
class AffectiveAdmin(admin.ModelAdmin):
    list_display = ('student', 'neatness', 'leadership', 'punctuality', 'cooperation', 'creativity', 'relationship', 'hardwork', 'work_independently', 'attendance', 'comment')
    list_filter = ('student',)


# ===========================
# PSYCHOMOTOR ADMIN
# ===========================
@admin.register(PsychomotorSkill)
class PsychomotorAdmin(admin.ModelAdmin):
    list_display = ('student', 'movement', 'coordination', 'dexterity', 'strength', 'flexibility', 'speed')
    list_filter = ('student',)


# ===========================
# TERM ADMIN
# ===========================
@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    ordering = ('name',)


# ===========================
# ACADEMIC SESSION ADMIN
# ===========================
@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    ordering = ('name',)


# ===========================
# GRADUATION RECORD ADMIN ✅
# ===========================
from django.contrib import admin
from .models import GraduationRecord

@admin.register(GraduationRecord)
class GraduationRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'class_group', 'session', 'graduation_date', 'remarks')
    list_filter = ('session', 'class_group')
    search_fields = ('student__surname', 'student__first_name', 'session__name')
    ordering = ('-graduation_date',)
    date_hierarchy = 'graduation_date'




from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Term, AcademicSession, PublishedResult

def publish_result(request):
    if request.method == 'POST':
        term_id = request.POST.get('term')
        session_id = request.POST.get('session')

        term = Term.objects.get(id=term_id)
        session = AcademicSession.objects.get(id=session_id)

        obj, created = PublishedResult.objects.get_or_create(term=term, session=session)
        obj.is_published = True
        obj.save()

        messages.success(request, f"Results for {term.name} ({session.name}) have been published.")
        return redirect('publish_result')

    terms = Term.objects.all()
    sessions = AcademicSession.objects.all()
    return render(request, 'publish_result.html', {'terms': terms, 'sessions': sessions})



from django.contrib import admin
from .models import Staff, Meeting, Timetable

# Staff Admin
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("surname", "firstname", "middlename", "phone_number", "email", "status", "school")
    list_filter = ("status", "school")
    search_fields = ("surname", "firstname", "email", "phone_number")
    ordering = ("surname", "firstname")

# Meeting Admin
@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("title", "date", "school")
    list_filter = ("school", "date")
    search_fields = ("title", "agenda")
    filter_horizontal = ("invited_staff",)  # For ManyToManyField

# Timetable Admin
@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = ("class_name", "subject", "teacher", "day", "start_time", "end_time", "school")
    list_filter = ("school", "day", "class_name")
    search_fields = ("class_name", "subject", "teacher")
    ordering = ("class_name", "day", "start_time")
