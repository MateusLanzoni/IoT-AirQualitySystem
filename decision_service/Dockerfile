FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SERVER_HOST=0.0.0.0

EXPOSE 8002

CMD ["python", "main.py"]
