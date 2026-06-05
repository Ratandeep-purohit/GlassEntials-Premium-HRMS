from django.contrib import admin

from .models import JoiningLetter


@admin.register(JoiningLetter)
class JoiningLetterAdmin(admin.ModelAdmin):
    list_display = ('letter_number', 'letter_type', 'candidate_name', 'joining_date', 'designation', 'status', 'organization')
    list_filter = ('letter_type', 'status', 'joining_date', 'organization')
    search_fields = ('letter_number', 'candidate_name', 'candidate_email', 'designation')
