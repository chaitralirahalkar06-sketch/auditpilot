FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser

FROM base AS test

COPY . .
RUN python scripts/make_data.py --output-dir /app/data
RUN mkdir -p /app/docs /app/auditpilot/.adk \
    && chown -R appuser:appuser /app

USER appuser
CMD ["pytest", "-q"]

FROM base AS runtime

COPY . .
RUN python scripts/make_data.py --output-dir /app/data \
    && rm -f /app/data/ground_truth.csv \
    && mkdir -p /app/docs /app/auditpilot/.adk \
    && chown -R appuser:appuser /app/data /app/docs /app/auditpilot/.adk

USER appuser

EXPOSE 8080
CMD ["python", "main.py"]
