FROM python:3.9-slim

WORKDIR /app

# Install system dependencies needed for mysqlclient and other python packages
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Ensure upload directories exist inside the container
RUN mkdir -p static/uploads/avatars static/uploads/covers static/uploads/games

EXPOSE 8080

# Use gunicorn to run the flask application
# --timeout: prevent worker timeouts
# --capture-output: enable logging
# --error-logfile: capture errors
CMD ["gunicorn", \
     "--timeout", "120", \
     "--capture-output", \
     "--error-logfile", "-", \
     "--access-logfile", "-", \
     "-w", "4", \
     "-b", "0.0.0.0:8080", \
     "app:app"]
