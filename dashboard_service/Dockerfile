FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY dashboard_service/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY env_loader.py .
COPY dashboard_service/main.py main.py
COPY dashboard_service/templates ./templates

EXPOSE 8501

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8501"]