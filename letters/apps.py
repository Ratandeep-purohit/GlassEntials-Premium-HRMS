from django.apps import AppConfig


class LettersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'letters'
    label = 'joining_letters'
    verbose_name = 'Letters'
