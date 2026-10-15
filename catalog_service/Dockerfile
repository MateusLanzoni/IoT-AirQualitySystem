FROM python:3.11-slim

WORKDIR /app

COPY catalog_service/requirements.txt requirements.txt
COPY env_loader.py .
RUN pip install --no-cache-dir -r requirements.txt

COPY catalog_service/ .

ENV SERVER_HOST=0.0.0.0

EXPOSE 8001

CMD ["python", "main.py"]
