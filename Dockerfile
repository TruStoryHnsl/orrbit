FROM python:3.14-slim

# Install system dependencies for thumbnails
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Create app user (uid 3000, gid 4500)
RUN groupadd -g 4500 orrbit && \
    useradd -u 3000 -g 4500 -m -s /bin/bash orrbit

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Ensure data directory
RUN mkdir -p /app/data && chown orrbit:orrbit /app/data

USER orrbit

EXPOSE 5000
EXPOSE 2222

CMD ["gunicorn", "-c", "gunicorn.conf.py", "run_prod:app"]
