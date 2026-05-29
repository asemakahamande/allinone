FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system libraries required by reportlab/weasyprint/Pillow
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libfreetype6 \
    libfreetype6-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libcairo2 \
    libcairo2-dev \
    libfontconfig1 \
    libharfbuzz-dev \
    libpango-1.0-0 \
    libpango1.0-dev \
    libpangocairo-1.0-0 \
    libpangocairo-1.0-dev \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libgdk-pixbuf2.0-dev \
    libglib2.0-0 \
    libgobject-2.0-0 \
    libxml2 \
    libxml2-dev \
    libxslt1.1 \
    libxslt1-dev \
    libffi-dev \
    fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY school/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel && python -m pip install -r /app/requirements.txt

# Copy project
COPY . /app

# Collect static assets for Whitenoise
RUN python manage.py collectstatic --noinput

# Default port
EXPOSE 8000

# Start the app, using the platform port variable when available
CMD ["sh", "-c", "gunicorn school.wsgi:application --bind 0.0.0.0:${PORT:-8000}"]
