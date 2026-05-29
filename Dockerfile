FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system libraries required by reportlab/weasyprint/Pillow
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    libfreetype6 \
    libfreetype6-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libxml2 \
    libxslt1.1 \
    libffi-dev \
    fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY school/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy project
COPY . /app

# Default port
EXPOSE 8000

# Start the app (adjust if you use a different entrypoint)
CMD ["gunicorn", "school.wsgi:application", "--bind", "0.0.0.0:8000"]
