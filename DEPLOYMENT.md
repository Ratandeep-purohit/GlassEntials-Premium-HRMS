# Deployment Checklist

Use this checklist before deploying GlassEntials HRMS to a real server.

## Required Environment Variables

Set these on the hosting platform, not in git:

```env
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=hrms.yourdomain.com,www.hrms.yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://hrms.yourdomain.com,https://www.hrms.yourdomain.com

DB_NAME=<production-db-name>
DB_USER=<production-db-user>
DB_PASSWORD=<production-db-password>
DB_HOST=<production-db-host>
DB_PORT=3306
DB_CONN_MAX_AGE=60

DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000

USE_S3=True
AWS_ACCESS_KEY_ID=<access-key-or-role-managed>
AWS_SECRET_ACCESS_KEY=<secret-key-or-role-managed>
AWS_STORAGE_BUCKET_NAME=<private-media-bucket>
AWS_S3_REGION_NAME=<region>

DJANGO_ADMIN_URL=<private-admin-path>/
DJANGO_LOG_LEVEL=WARNING
```

## Release Commands

Run these for each deployment:

```bash
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
```

## Required Operational Setup

- Use HTTPS only.
- Store HR document uploads in private object storage such as S3.
- Configure database backups.
- Configure logs and error monitoring.
- Schedule leave accrual and year-end jobs:

```bash
python manage.py accrue_leaves
python manage.py process_year_end
```

## Security Notes

- Do not commit `.env`.
- Do not commit `media/` uploads.
- Do not commit `__pycache__/` or `.pyc` files.
- Rotate any secret that was ever committed to git history.
