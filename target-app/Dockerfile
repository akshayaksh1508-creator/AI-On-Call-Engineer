FROM python:3.11-slim

WORKDIR /app

# Install curl for container health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY target-app /app/target-app
COPY target_app /app/target_app

ENV PYTHONPATH=/app
ENV SERVICE_NAME=gateway
ENV SERVICE_PORT=8080

EXPOSE 8080 8081 8082

CMD ["sh", "-c", "python -m uvicorn target_app.services.${SERVICE_NAME}.app:app --host 0.0.0.0 --port ${SERVICE_PORT}"]
