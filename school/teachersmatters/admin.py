from django.contrib import admin

# Register your models here.
# teachers/admin.py
from django.contrib import admin
from .models import Teacher, Employer, Hire


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = (
        'sname', 'fname', 'mname',
        'email', 'phone',
        'discipline', 'experience_years',
        'country', 'state', 'town',
        'is_currently_hired'
    )
    list_filter = ('discipline', 'country', 'state')
    search_fields = ('sname', 'fname', 'email', 'phone')
    readonly_fields = ()
    ordering = ('sname', 'fname')


@admin.register(Employer)
class EmployerAdmin(admin.ModelAdmin):
    list_display = ('sname', 'fname', 'mname', 'email', 'phone')
    search_fields = ('sname', 'fname', 'email', 'phone')
    ordering = ('sname', 'fname')


@admin.register(Hire)
class HireAdmin(admin.ModelAdmin):
    list_display = (
        'teacher',
        'employer',
        'date_hired',
        'date_unhired',
        'unhired_by_owner',
        'is_active'
    )
    list_filter = ('unhired_by_owner', 'date_hired')
    search_fields = (
        'teacher__sname',
        'teacher__fname',
        'employer__sname',
        'employer__fname'
    )
    ordering = ('-date_hired',)
