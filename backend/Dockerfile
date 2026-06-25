FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y build-essential libpq-dev curl docker.io && \
    # Remove apt index to keep image size low.
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy the backend package directory
COPY backend /app/backend
# Copy the common utilities to parent of app
COPY common /common

EXPOSE 8000

# Use a simple Python script wrapper that adds /app to sys.path
# This ensures the backend module can be imported regardless of how Python is invoked
CMD ["python", "/app/backend/run.py"]
