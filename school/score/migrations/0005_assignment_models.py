from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('score', '0004_schoolsetting_subject_teacher_pin'),
    ]

    operations = [
        migrations.CreateModel(
            name='Assignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('questions', models.JSONField(default=list)),
                ('total_marks', models.FloatField(default=0)),
                ('deadline', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('class_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='score.classgroup')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='score.school')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='score.subject')),
                ('term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assignments', to='score.term')),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assignments', to='score.academicsession')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='AssignmentSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('answers', models.JSONField(default=list)),
                ('file', models.FileField(blank=True, null=True, upload_to='assignments/submissions/')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('submitted', 'Submitted'), ('graded', 'Graded')], default='submitted', max_length=10)),
                ('score', models.FloatField(blank=True, help_text='Score given by subject teacher after grading', null=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('graded_at', models.DateTimeField(blank=True, null=True)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='score.assignment')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignment_submissions', to='score.student')),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='assignmentsubmission',
            unique_together={('assignment', 'student')},
        ),
    ]
