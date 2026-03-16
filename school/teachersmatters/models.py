# teachers/models.py
from django.db import models
from django.utils import timezone

class Teacher(models.Model):
    sname = models.CharField(max_length=50, verbose_name="Surname")
    fname = models.CharField(max_length=50, verbose_name="First Name")
    mname = models.CharField(max_length=50, blank=True, null=True, verbose_name="Middle Name")
    phone = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)  # In production, use Django User
    discipline = models.CharField(max_length=100)
    specialization = models.TextField()
    experience_years = models.PositiveIntegerField()
    image = models.ImageField(upload_to='teacher_images/')
    country = models.CharField(max_length=50)
    state = models.CharField(max_length=50)
    town = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.sname} {self.fname} {self.mname or ''}".strip()

    def is_currently_hired(self):
        """Return True if teacher is actively hired"""
        return Hire.objects.filter(teacher=self, date_unhired__isnull=True).exists()

    def hired_by(self):
        """Return the employer who currently hired this teacher"""
        hire = Hire.objects.filter(teacher=self, date_unhired__isnull=True).first()
        return hire.employer if hire else None


class Employer(models.Model):
    sname = models.CharField(max_length=50, verbose_name="Surname")
    fname = models.CharField(max_length=50, verbose_name="First Name")
    mname = models.CharField(max_length=50, blank=True, null=True, verbose_name="Middle Name")
    phone = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    def __str__(self):
        return f"{self.sname} {self.fname} {self.mname or ''}".strip()


class Hire(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='hires')
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name='hires_made')
    date_hired = models.DateTimeField(auto_now_add=True)
    date_unhired = models.DateTimeField(null=True, blank=True)
    unhired_by_owner = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date_hired']

    def is_active(self):
        return self.date_unhired is None

    def unhire(self, by_owner=False):
        if self.is_active():
            self.date_unhired = timezone.now()
            self.unhired_by_owner = by_owner
            self.save()
