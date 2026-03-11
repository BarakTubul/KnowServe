# Use official slim Python image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies required for compiling Python packages (like psycopg2, PyMuPDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose the API port
EXPOSE 8000

# The default command runs the FastAPI server. 
# Celery workers will override this command in docker-compose or Render config.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
