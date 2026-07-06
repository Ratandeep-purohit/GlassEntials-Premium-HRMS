# Use the same major Python version as the development/runtime environment.
FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Set work directory
WORKDIR /app

# Install system dependencies (e.g. for mysqlclient)
RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project files
COPY . /app/

# Collect static files with build-time-only Django settings.
RUN DJANGO_SECRET_KEY=build-time-static-collection-key \
    DJANGO_DEBUG=False \
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
    python manage.py collectstatic --noinput --verbosity 0

# Expose port
EXPOSE $PORT

# Command to run the application using gunicorn
# GUNICORN_WORKERS: recommended = (2 * vCPUs) + 1, default 3
# GUNICORN_TIMEOUT: set high enough for payroll batch runs, default 120s
CMD gunicorn HRMS_Glassentials.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers ${GUNICORN_WORKERS:-3} \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --log-level ${GUNICORN_LOG_LEVEL:-info}
