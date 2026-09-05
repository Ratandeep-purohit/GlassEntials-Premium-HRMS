from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0009_location_fields'),
        ('employees', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendancesettings',
            name='location_apply_to',
            field=models.CharField(
                max_length=10,
                choices=[('all', 'All Employees'), ('selected', 'Selected Employees')],
                default='all',
                help_text='Whether location restriction applies to all employees or only selected ones.',
            ),
        ),
        migrations.AddField(
            model_name='attendancesettings',
            name='location_restricted_employees',
            field=models.ManyToManyField(
                to='employees.Employee',
                blank=True,
                related_name='location_restricted_settings',
                help_text='Employees subject to GPS location validation when apply_to=selected.',
            ),
        ),
    ]
