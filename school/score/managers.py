# score/managers.py
"""
Custom model managers to automatically filter queries by school
These managers provide convenient methods for school-based data isolation
"""

from django.db import models


class SchoolAwareManager(models.Manager):
    """
    Base manager that provides school-aware filtering
    """
    def for_school(self, school):
        """
        Get queryset filtered by school
        
        Usage: 
            ClassGroup.objects.for_school(request.school)
        """
        return self.filter(school=school)


class ClassGroupManager(models.Manager):
    """
    Custom manager for ClassGroup model
    """
    def for_school(self, school):
        """Get all classes for a school"""
        return self.filter(school=school).order_by('name')
    
    def active_for_school(self, school):
        """Get active classes for a school"""
        return self.filter(school=school).order_by('name')
    
    def with_students(self, school):
        """Get classes that have students"""
        return self.filter(
            school=school,
            students__isnull=False
        ).distinct().order_by('name')


class StudentManager(models.Manager):
    """
    Custom manager for Student model with school-aware methods
    """
    def for_school(self, school):
        """Get all students for a school"""
        return self.filter(school=school).order_by('surname', 'first_name')
    
    def active_for_school(self, school):
        """Get active students for a school"""
        return self.filter(
            school=school, 
            is_active=True
        ).order_by('surname', 'first_name')
    
    def for_class(self, class_group):
        """
        Get students for a specific class (automatically school-filtered)
        """
        return self.filter(
            class_group=class_group,
            school=class_group.school
        ).order_by('surname', 'first_name')
    
    def for_session(self, school, session):
        """Get students for a specific school and session"""
        return self.filter(
            school=school,
            session=session
        ).order_by('surname', 'first_name')
    
    def for_class_and_session(self, class_group, session):
        """Get students for a specific class and session"""
        return self.filter(
            class_group=class_group,
            session=session,
            school=class_group.school
        ).order_by('surname', 'first_name')
    
    def graduated_for_school(self, school):
        """Get graduated students for a school"""
        return self.filter(
            school=school,
            is_graduated=True
        ).order_by('surname', 'first_name')


class SubjectManager(models.Manager):
    """
    Custom manager for Subject model
    """
    def for_school(self, school):
        """Get all subjects for a school"""
        return self.filter(
            class_group__school=school
        ).select_related('class_group').order_by('name')
    
    def for_class(self, class_group):
        """Get subjects for a specific class"""
        return self.filter(
            class_group=class_group
        ).order_by('name')
    
    def for_class_and_school(self, class_group, school):
        """Get subjects for a specific class, ensuring it belongs to school"""
        return self.filter(
            class_group=class_group,
            class_group__school=school
        ).order_by('name')


class StaffManager(models.Manager):
    """
    Custom manager for Staff model
    """
    def for_school(self, school):
        """Get all staff for a school"""
        return self.filter(school=school).order_by('surname', 'firstname')
    
    def teaching_staff(self, school):
        """Get only teaching staff"""
        return self.filter(
            school=school,
            status='teaching'
        ).order_by('surname', 'firstname')
    
    def non_teaching_staff(self, school):
        """Get only non-teaching staff"""
        return self.filter(
            school=school,
            status='non-teaching'
        ).order_by('surname', 'firstname')


class ScoreManager(models.Manager):
    """
    Custom manager for Score model
    """
    def for_school(self, school):
        """Get all scores for students in a school"""
        return self.filter(
            student__school=school
        ).select_related('student', 'subject', 'term', 'session')
    
    def for_class(self, class_group):
        """Get scores for students in a specific class"""
        return self.filter(
            student__class_group=class_group,
            student__school=class_group.school
        ).select_related('student', 'subject', 'term', 'session')
    
    def for_term_and_session(self, school, term, session):
        """Get scores for a specific term and session"""
        return self.filter(
            student__school=school,
            term=term,
            session=session
        ).select_related('student', 'subject')
    
    def for_student(self, student):
        """Get all scores for a specific student"""
        return self.filter(
            student=student
        ).select_related('subject', 'term', 'session').order_by('-session', '-term')


class AttendanceManager(models.Manager):
    """
    Custom manager for Attendance model
    """
    def for_school(self, school):
        """Get all attendance records for a school"""
        return self.filter(school=school).select_related('student')
    
    def for_class(self, class_group):
        """Get attendance for students in a specific class"""
        return self.filter(
            student__class_group=class_group,
            school=class_group.school
        ).select_related('student')
    
    def for_date(self, school, date):
        """Get attendance for a specific date"""
        return self.filter(
            school=school,
            date=date
        ).select_related('student')


class MeetingManager(models.Manager):
    """
    Custom manager for Meeting model
    """
    def for_school(self, school):
        """Get all meetings for a school"""
        return self.filter(school=school).order_by('-date')
    
    def upcoming(self, school):
        """Get upcoming meetings"""
        from django.utils import timezone
        return self.filter(
            school=school,
            date__gte=timezone.now()
        ).order_by('date')
    
    def past(self, school):
        """Get past meetings"""
        from django.utils import timezone
        return self.filter(
            school=school,
            date__lt=timezone.now()
        ).order_by('-date')


class TimetableManager(models.Manager):
    """
    Custom manager for Timetable model
    """
    def for_school(self, school):
        """Get all timetable entries for a school"""
        return self.filter(school=school).order_by('day', 'start_time')
    
    def for_class(self, school, class_name):
        """Get timetable for a specific class"""
        return self.filter(
            school=school,
            class_name=class_name
        ).order_by('day', 'start_time')
    
    def for_day(self, school, day):
        """Get timetable for a specific day"""
        return self.filter(
            school=school,
            day=day
        ).order_by('start_time')


# ==================================================
# HOW TO ADD TO YOUR MODELS
# ==================================================
"""
In your models.py, update each model like this:

# Import the managers
from .managers import (
    ClassGroupManager, StudentManager, SubjectManager, 
    StaffManager, ScoreManager, AttendanceManager,
    MeetingManager, TimetableManager
)


class ClassGroup(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classes")
    # ... other fields ...
    
    # Add this line:
    objects = ClassGroupManager()
    
    class Meta:
        unique_together = [('school', 'name')]


class Student(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="students")
    # ... other fields ...
    
    # Add this line:
    objects = StudentManager()


class Subject(models.Model):
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name="subjects")
    # ... other fields ...
    
    # Add this line:
    objects = SubjectManager()


class Staff(models.Model):
    school = models.ForeignKey("School", on_delete=models.CASCADE, related_name="staff")
    # ... other fields ...
    
    # Add this line:
    objects = StaffManager()


class Score(models.Model):
    student = models.ForeignKey("Student", on_delete=models.CASCADE)
    # ... other fields ...
    
    # Add this line:
    objects = ScoreManager()


class Attendance(models.Model):
    student = models.ForeignKey("Student", on_delete=models.CASCADE, related_name="attendance")
    school = models.ForeignKey("School", on_delete=models.CASCADE, related_name="attendance")
    # ... other fields ...
    
    # Add this line:
    objects = AttendanceManager()


class Meeting(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="meetings")
    # ... other fields ...
    
    # Add this line:
    objects = MeetingManager()


class Timetable(models.Model):
    school = models.ForeignKey("School", on_delete=models.CASCADE, related_name="timetables")
    # ... other fields ...
    
    # Add this line:
    objects = TimetableManager()


# USAGE IN VIEWS:
# ================

@school_required
def dashboard(request):
    school = request.school
    
    # Use the custom manager methods
    classes = ClassGroup.objects.for_school(school)
    students = Student.objects.active_for_school(school)
    subjects = Subject.objects.for_school(school)
    staff = Staff.objects.teaching_staff(school)
    
    return render(request, 'dashboard.html', {
        'classes': classes,
        'students': students,
        'subjects': subjects,
        'staff': staff,
    })
"""