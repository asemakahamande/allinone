import uuid
from django.db import models
from django.db.models import Q
from .helpers import ScoreHelper


from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password, check_password



from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from .helpers import ScoreHelper


class School(models.Model):
    # School Info
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    local_government = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    address = models.TextField()
    registration_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    logo = models.ImageField(upload_to="school_logos/", blank=True, null=True)

    # Admin Info
    admin_name = models.CharField(max_length=255)
    admin_phone = models.CharField(max_length=20)
    website = models.URLField(blank=True, null=True)

    # Owner Info
    owner_first_name = models.CharField(max_length=100)
    owner_middle_name = models.CharField(max_length=100, blank=True, null=True)
    owner_surname = models.CharField(max_length=100)
    owner_gender = models.CharField(
        max_length=10,
        choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")],
    )

    # Login Details
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)  # hashed
    reset_token = models.CharField(max_length=100, blank=True, null=True)
    reset_token_created = models.DateTimeField(blank=True, null=True)

    # Payment: site admin can enable/disable payment per school
    payment_active = models.BooleanField(default=False)

    tier_name = models.CharField(max_length=50, default='basic')

    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw_password):
        self.password = make_password(raw_password)
        self.save(update_fields=["password"])

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Schools"
    


class ClassGroup(models.Model):
    SCORING_SYSTEMS = [
        ('scheme_1', 'CA1:20, CA2:20, CA3:20, Exam:40'),
        ('scheme_2', 'CA1:20, CA2:10, CA3:10, Exam:60'),
        ('scheme_3', 'CA1:20, CA2:15, CA3:15, Exam:50'),
        ('scheme_4', 'CA1:10, CA2:10, CA3:10, Exam:70'),
        ('custom', 'Custom Grading System'),  # new option
    ]
    # 🔐 Teacher login account
    teacher_user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="class_teacher"
    )

    # Store generated password ONCE (for admin to give teacher)
    generated_password = models.CharField(max_length=50, blank=True, null=True)

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=50)
    class_teacher = models.CharField(max_length=100, blank=True, null=True)
    scoring_system = models.CharField(max_length=20, choices=SCORING_SYSTEMS, default='scheme_1')
    next_class = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True,
                                   related_name='previous_classes')
    is_graduating_class = models.BooleanField(default=False)

    def __str__(self):
        teacher = f" - {self.class_teacher}" if self.class_teacher else ""
        return f"{self.name}{teacher} ({self.school.name})"


# ===========================
# SUBJECT MODEL
# ===========================
class Subject(models.Model):
    name = models.CharField(max_length=100)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name="subjects")

    def __str__(self):
        return f"{self.name} ({self.class_group})"

    class Meta:
        unique_together = ('name', 'class_group')
        ordering = ['name']






class AcademicSession(models.Model):
    name = models.CharField(max_length=20, unique=True)  # e.g., "2024/2025"

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-name']


class Term(models.Model):
    name = models.CharField(max_length=20, unique=True)  # e.g. "First Term"

    def __str__(self):
        return self.name



from django.db import models



class Student(models.Model):
    GENDER_CHOICES = [('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')]


    # 🔐 Student login account
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="student_account"
    )

    # Store generated password ONCE (admin use only)
    generated_password = models.CharField(max_length=50, blank=True, null=True)


    # For historical records across sessions
    base_student = models.ForeignKey('self', null=True, blank=True,
                                     on_delete=models.CASCADE, related_name='academic_records')

    # Personal Info
    surname = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)

    # Academic Info - NOW WITH school FIELD!
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="students")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name="students")
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="students")
    # Optional term at which this record is created (kept nullable for backwards compatibility)
    term = models.ForeignKey(
        Term,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )

    exam_no = models.CharField(max_length=50, blank=True, null=True)
    # Realistic uniqueness: same exam number allowed in different schools/sessions
    parent_surname = models.CharField(max_length=100)
    parent_first_name = models.CharField(max_length=100)
    parent_middle_name = models.CharField(max_length=100, blank=True, null=True)
    parent_email = models.EmailField(blank=True, null=True)
    parent_phone_number = models.CharField(max_length=20, blank=True, null=True)

    location = models.CharField(max_length=150, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    is_graduated = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        # Exam number should be unique per school + session (or just per school)
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'exam_no'],
                name='unique_exam_no_per_school',
                condition=~models.Q(exam_no__isnull=True) | ~models.Q(exam_no='')
            )
        ]
        # Optional: also prevent same student name in same class/session (rare but helpful)
        # unique_together = ('school', 'surname', 'first_name', 'session')
        ordering = ['surname', 'first_name']

    def __str__(self):
        return f"{self.surname} {self.first_name} ({self.class_group.name}, {self.session.name})"

    @property
    def full_name(self):
        parts = [self.surname, self.first_name, self.middle_name]
        return " ".join(p for p in parts if p).strip()

    # ----- Exam number auto-generation: SCHOOL_ABBREV/CLASS_NAME/0001 (e.g. SA/JSS3/0008) -----
    @staticmethod
    def get_school_abbreviation(school):
        """First letters of the first two words of the school name. E.g. 'Satellite Academy' -> 'SA'."""
        if not school or not school.name:
            return ""
        words = school.name.split()
        if len(words) >= 2:
            return (words[0][:2] if len(words[0]) >= 2 else (words[0][0] + words[1][0])).lower()
        if len(words) == 1:
            return words[0][:2].lower()
        return ""

    @staticmethod
    def get_next_exam_number(school, class_group):
        """
        Next exam number for this school + class. Format: SCHOOL_ABBREV/CLASS_NAME/SEQUENTIAL.
        E.g. SA/JSS3/0001, SA/JSS3/0002, SA/JSS3/0008.
        """
        school_abbrev = Student.get_school_abbreviation(school)
        class_name = (class_group.name or "").strip().replace(" ", "").lower()
        if not school_abbrev or not class_name:
            return None
        prefix = f"{school_abbrev}/{class_name}/"
        existing = Student.objects.filter(
            school=school,
            class_group=class_group,
            exam_no__startswith=prefix,
        ).exclude(exam_no__isnull=True).exclude(exam_no="")
        max_num = 0
        for s in existing:
            if not s.exam_no:
                continue
            parts = s.exam_no.split("/")
            if len(parts) == 3:
                try:
                    n = int(parts[2])
                    if n > max_num:
                        max_num = n
                except (ValueError, IndexError):
                    pass
        return f"{prefix}{max_num + 1:04d}"

    def save(self, *args, **kwargs):
        # Auto-set exam_no for new students (no pk, no exam_no, has school + class_group)
        if not self.pk and not (self.exam_no or "").strip() and self.school_id and self.class_group_id:
            self.exam_no = self.get_next_exam_number(self.school, self.class_group)
        super().save(*args, **kwargs)

    def update_exam_no_for_promotion(self, new_class):
        if not self.exam_no:
            return
        parts = self.exam_no.split("/")
        if len(parts) == 3:
            prefix, _, serial = parts
            class_name = (new_class.name or "").strip().replace(" ", "").lower()
            self.exam_no = f"{prefix}/{class_name}/{serial}"
            self.save(update_fields=["exam_no"])

    def create_record_for_next_session(self, next_class, next_session):
        new_exam_no = self.exam_no
        if new_exam_no:
            parts = new_exam_no.split("/")
            if len(parts) == 3:
                prefix, _, serial = parts
                class_name = (next_class.name or "").strip().replace(" ", "").lower()
                new_exam_no = f"{prefix}/{class_name}/{serial}"

        return Student.objects.create(
            base_student=self.base_student or self,
            school=self.school,
            surname=self.surname,
            first_name=self.first_name,
            middle_name=self.middle_name,
            gender=self.gender,
            class_group=next_class,
            exam_no=new_exam_no,
            session=next_session,
            parent_surname=self.parent_surname,
            parent_first_name=self.parent_first_name,
            parent_middle_name=self.parent_middle_name,
            parent_email=self.parent_email,
            parent_phone_number=self.parent_phone_number,
            location=self.location,
            address=self.address,
            is_active=True,
        )


from django.db import models
from .helpers import ScoreHelper
from django.db import models
from .helpers import ScoreHelper


class Score(models.Model):
    student = models.ForeignKey("Student", on_delete=models.CASCADE)
    subject = models.ForeignKey("Subject", on_delete=models.CASCADE)
    term = models.ForeignKey("Term", on_delete=models.CASCADE)
    session = models.ForeignKey("AcademicSession", on_delete=models.CASCADE)
    custom_scores = models.JSONField(default=dict, blank=True, null=True)

    ca1 = models.FloatField(default=0)
    ca2 = models.FloatField(default=0)
    ca3 = models.FloatField(default=0)
    exam = models.FloatField(default=0)
    total = models.FloatField(default=0)
    grade = models.CharField(max_length=2, blank=True)
    remark = models.CharField(max_length=50, blank=True)

    max_score = models.FloatField(default=0)
    min_score = models.FloatField(default=0)
    avg_score = models.FloatField(default=0.0)
    position = models.IntegerField(default=0)
    ordinal_position = models.CharField(max_length=10, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "subject", "term", "session"],
                name="unique_score_per_student_subject_term_session"
            )
        ]

    def save(self, *args, **kwargs):
        # Calculate total based on grading system
        if self.custom_scores and isinstance(self.custom_scores, dict) and self.custom_scores:
            # Custom grading system - sum all custom score values
            self.total = round(sum(float(v) for v in self.custom_scores.values() if v), 2)
        else:
            # Default grading system - sum ca1, ca2, ca3, exam
            self.total = self.ca1 + self.ca2 + self.ca3 + self.exam

        # Calculate grade and remark based on total
        self.grade, self.remark = self.get_grade_and_remark(self.total)

        # Set ordinal position if position exists
        if self.position:
            self.ordinal_position = ScoreHelper.ordinal(self.position)

        super().save(*args, **kwargs)

    def get_grade_and_remark(self, total):
        if total >= 91:
            return "A+", "Exceptional"
        elif total >= 81:
            return "A", "Excellent"
        elif total >= 71:
            return "B", "Very Good"
        elif total >= 51:
            return "C+", "Good"
        elif total >= 33:
            return "P", "Average"
        else:
            return "NI", "Needs Improvement"

    def __str__(self):
        return f"{self.student.full_name} - {self.subject.name} ({self.term.name}, {self.session.name})"




# ===========================
# PROMOTION RECORD MODEL
# ===========================
class StudentPromotion(models.Model):
    STATUS_CHOICES = [
        ("Promoted", "Promoted"),
        ("Graduated", "Graduated"),
        ("Failed", "Failed"),
    ]

    student = models.ForeignKey("Student", on_delete=models.CASCADE)
    from_class = models.ForeignKey("ClassGroup", on_delete=models.SET_NULL, null=True, related_name="promoted_from")
    to_class = models.ForeignKey("ClassGroup", on_delete=models.SET_NULL, null=True, related_name="promoted_to", blank=True)
    session = models.ForeignKey("AcademicSession", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.full_name} - {self.status} ({self.session.name})"


# ===========================
# SCHOOL SETTINGS
# ===========================
class SchoolSetting(models.Model):
    school = models.OneToOneField(
        "School",
        on_delete=models.CASCADE,
        related_name="settings"
    )

    name = models.CharField(max_length=255, default="Your School Name")
    address = models.CharField(max_length=255, default="123 School Road, City")
    phone = models.CharField(max_length=20, default="+234-123-456-789")
    email = models.EmailField(default="info@yourschool.com")
    motto = models.CharField(max_length=255, default="Knowledge is Power")

    exam_year = models.IntegerField()
    exam_month = models.CharField(max_length=20)
    school_open = models.PositiveIntegerField(help_text="Number of times school opened")
    next_term_begins = models.DateField(null=True, blank=True)
    term_closes_on = models.DateField(null=True, blank=True)

    logo = models.ImageField(upload_to="school_logos/", blank=True, null=True)
    stamp_sign = models.ImageField(upload_to="school_logos/", blank=True, null=True)

    subject_teacher_pin = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Unique PIN for Subject Teachers to log in")

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.school.name} - {self.exam_month} {self.exam_year}"



# ===========================
# AFFECTIVE & PSYCHOMOTOR
# ===========================
class AffectiveTrait(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE)
    neatness = models.CharField(max_length=2, blank=True)
    leadership = models.CharField(max_length=2, blank=True)
    punctuality = models.CharField(max_length=2, blank=True)
    cooperation = models.CharField(max_length=2, blank=True)
    creativity = models.CharField(max_length=2, blank=True)
    relationship = models.CharField(max_length=2, blank=True)
    hardwork = models.CharField(max_length=2, blank=True)
    work_independently = models.CharField(max_length=2, blank=True)
    attendance = models.PositiveIntegerField(default=0)
    comment = models.TextField(blank=True)

    class Meta:
        unique_together = ('student', 'term', 'session')
        ordering = ['student__surname', 'student__first_name', 'session__name', 'term__name']

    def __str__(self):
        return f"Affective - {self.student.full_name} ({self.term.name}, {self.session.name})"


class PsychomotorSkill(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE)
    movement = models.CharField(max_length=2, blank=True)
    coordination = models.CharField(max_length=2, blank=True)
    dexterity = models.CharField(max_length=2, blank=True)
    strength = models.CharField(max_length=2, blank=True)
    flexibility = models.CharField(max_length=2, blank=True)
    speed = models.CharField(max_length=2, blank=True)

    class Meta:
        unique_together = ('student', 'term', 'session')
        ordering = ['student__surname', 'student__first_name', 'session__name', 'term__name']

    def __str__(self):
        return f"Psychomotor - {self.student.full_name} ({self.term.name}, {self.session.name})"

# ===========================
# GRADUATION RECORD MODEL
# ===========================
class GraduationRecord(models.Model):
    student = models.ForeignKey("Student", on_delete=models.CASCADE, related_name="graduation_records")
    class_group = models.ForeignKey("ClassGroup", on_delete=models.SET_NULL, null=True)
    session = models.ForeignKey("AcademicSession", on_delete=models.CASCADE)
    graduation_date = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("student", "session")
        ordering = ["-graduation_date"]

    def __str__(self):
        return f"{self.student.full_name} graduated from {self.class_group.name} ({self.session.name})"




class Staff(models.Model):
    TEACHING_STATUS = [
        ("teaching", "Teaching Staff"),
        ("non-teaching", "Non-Teaching Staff"),
    ]

    school = models.ForeignKey(
        "School", on_delete=models.CASCADE, related_name="staff"
    )
    firstname = models.CharField(max_length=100)
    surname = models.CharField(max_length=100)
    middlename = models.CharField(max_length=100, blank=True, null=True)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(max_length=255)  # ✅ added email field
    qualification = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=TEACHING_STATUS, default="teaching")

    class Meta:
        unique_together = (
            ("school", "phone_number"),
            ("school", "email"),  # ✅ email unique per school
        )

    def __str__(self):
        return f"{self.surname} {self.firstname} ({self.get_status_display()})"


from django.db import models
from django.conf import settings
from .models import School, Staff

class Meeting(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="meetings")
    title = models.CharField(max_length=200)
    agenda = models.TextField()
    date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    invited_staff = models.ManyToManyField(Staff, related_name="meetings")

    def __str__(self):
        return f"{self.title} - {self.date.strftime('%Y-%m-%d %H:%M')}"

from django.db import models

class Timetable(models.Model):
    DAYS_OF_WEEK = [
        ("monday", "Monday"),
        ("tuesday", "Tuesday"),
        ("wednesday", "Wednesday"),
        ("thursday", "Thursday"),
        ("friday", "Friday"),
    ]

    school = models.ForeignKey("School", on_delete=models.CASCADE, related_name="timetables")
    class_name = models.CharField(max_length=100)  # e.g., JSS1, Grade 2
    subject = models.CharField(max_length=200)
    teacher = models.CharField(max_length=200, blank=True, null=True)  # optional
    day = models.CharField(max_length=20, choices=DAYS_OF_WEEK)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        unique_together = ("school", "class_name", "day", "start_time")

    def __str__(self):
        return f"{self.class_name} - {self.subject} ({self.day} {self.start_time}-{self.end_time})"



class Attendance(models.Model):
    student = models.ForeignKey("Student", on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=[("present", "Present"), ("absent", "Absent")],
    )
    school = models.ForeignKey("School", on_delete=models.CASCADE, related_name="attendance")

    class Meta:
        unique_together = ("student", "date")  # prevent duplicate entries per student/date

    def __str__(self):
        return f"{self.student.full_name} - {self.date} ({self.status})"



# models.py — Update CustomScoringSystem

class CustomScoringSystem(models.Model):
    class_group = models.OneToOneField(  # Changed from ForeignKey
        'ClassGroup',
        on_delete=models.CASCADE,
        related_name='custom_scoring_system'  # singular!
    )
    name = models.CharField(max_length=100, default="Custom Grading System")
    components = models.JSONField(
        default=dict,
        help_text='Example: {"CA1": 10, "Project": 20, "Exam": 60}'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def total_weight(self):
        return sum(self.components.values())

    def is_configured(self):
        return bool(self.components)

    def __str__(self):
        return f"{self.class_group.name} - Custom ({self.total_weight()}%)"





class Payment(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="payments"
    )
    reference = models.CharField(
        max_length=100, unique=True, default=uuid.uuid4, editable=False
    )
    num_students = models.PositiveIntegerField(
        help_text="Number of pins purchased"
    )
    amount = models.PositiveIntegerField(
        help_text="Amount in Kobo (₦1000 = 100000)"
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("paid", "Paid"),
            ("failed", "Failed"),
        ],
        default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    receipt_generated = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.school.name} - {self.reference} - {self.status}"

    @property
    def amount_display(self):
        return f"₦{self.amount / 100:,.2f}"

    @property
    def is_successful(self):
        return self.status == "paid"



class PublishedResult(models.Model):
    SCOPE_CHOICES = (
        ('school', 'Entire School'),
        ('class', 'Single Class'),
        ('student', 'Individual Student'),
    )

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, null=True, blank=True
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, null=True, blank=True
    )

    term = models.ForeignKey(Term, on_delete=models.CASCADE)
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE)

    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    is_published = models.BooleanField(default=True)
    date_published = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'school',
                    'term',
                    'session',
                    'scope',
                    'class_group',
                    'student'
                ],
                name='unique_publish_scope'
            )
        ]

    def __str__(self):
        return f"{self.scope.upper()} | {self.school.name} | {self.term.name} {self.session.name}"


class Pin(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="pins")
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="pins")

    code = models.CharField(max_length=20, unique=True)
    used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True
    )

    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL, null=True, blank=True
    )
    session = models.ForeignKey(
        AcademicSession, on_delete=models.SET_NULL, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)














# Add these models to your existing score app models.py
# They integrate directly with your existing School, ClassGroup, Subject, Student, etc.

import random
import string
from django.db import models
from django.contrib.auth.models import User


# ------------------------------------------
# CBT EXAM MODELS (Add to score app)
# ------------------------------------------

class Exam(models.Model):
    """
    CBT Exam integrated with existing score app structure
    """
    school = models.ForeignKey(
        School, 
        on_delete=models.CASCADE, 
        related_name='cbt_exams'
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.CASCADE,
        related_name='cbt_exams'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='cbt_exams'
    )
    session = models.ForeignKey(
        AcademicSession,
        on_delete=models.CASCADE,
        related_name='cbt_exams'
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name='cbt_exams'
    )
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    exam_code = models.CharField(max_length=20, unique=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    pass_mark = models.PositiveIntegerField(default=50)
    
    is_active = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ('school', 'class_group', 'subject', 'session', 'term', 'title')
    
    def save(self, *args, **kwargs):
        if not self.exam_code:
            self.exam_code = self.generate_exam_code()
        super().save(*args, **kwargs)
    
    def generate_exam_code(self):
        """Generate unique exam code"""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not Exam.objects.filter(exam_code=code).exists():
                return code
    
    def __str__(self):
        return f"{self.title} - {self.class_group.name} ({self.session.name}, {self.term.name})"
    
    @property
    def total_questions(self):
        return self.cbt_questions.count()
    
    @property
    def total_attempts(self):
        return self.cbt_results.count()
    
    @property
    def average_score(self):
        results = self.cbt_results.all()
        if not results:
            return 0
        total = sum((r.score / r.total * 100) for r in results)
        return round(total / results.count(), 2)


class Question(models.Model):
    """
    Multiple choice question for CBT
    """
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='cbt_questions'
    )
    
    question_text = models.TextField()
    image = models.ImageField(upload_to='cbt_questions/', blank=True, null=True)
    
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    
    correct_answer = models.CharField(
        max_length=1,
        choices=[
            ('A', 'Option A'),
            ('B', 'Option B'),
            ('C', 'Option C'),
            ('D', 'Option D'),
        ]
    )
    
    explanation = models.TextField(blank=True, null=True)
    marks = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'id']
    
    def options(self):
        """Return list of options"""
        return [self.option_a, self.option_b, self.option_c, self.option_d]
    
    def __str__(self):
        return f"Q{self.order}: {self.question_text[:50]}..."


class CBTResult(models.Model):
    """
    Stores student CBT exam results
    Links to existing Student model in score app
    """
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='cbt_results'
    )
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='cbt_results'
    )
    
    score = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    percentage = models.FloatField(default=0)
    
    time_taken_minutes = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-submitted_at']
        unique_together = ('student', 'exam')
    
    def save(self, *args, **kwargs):
        if self.total > 0:
            self.percentage = round((self.score / self.total) * 100, 2)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.student.full_name} - {self.exam.title}: {self.score}/{self.total}"
    
    @property
    def grade(self):
        """Calculate grade based on percentage"""
        if self.percentage >= 91:
            return "A+"
        elif self.percentage >= 81:
            return "A"
        elif self.percentage >= 71:
            return "B"
        elif self.percentage >= 51:
            return "C+"
        elif self.percentage >= 33:
            return "P"
        else:
            return "NI"
    
    @property
    def passed(self):
        return self.percentage >= self.exam.pass_mark


class QuestionResponse(models.Model):
    """
    Optional: Store individual question responses for detailed analysis
    """
    result = models.ForeignKey(
        CBTResult,
        on_delete=models.CASCADE,
        related_name='responses'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='student_responses'
    )
    
    selected_answer = models.CharField(max_length=1, blank=True, null=True)
    is_correct = models.BooleanField(default=False)
    time_spent_seconds = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ('result', 'question')
    
    def __str__(self):
        return f"{self.result.student.full_name} - Q{self.question.order}"