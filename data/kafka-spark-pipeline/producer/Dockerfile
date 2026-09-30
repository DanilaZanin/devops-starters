FROM python:3.14.7-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY producer.py .

RUN useradd --system --uid 10001 --no-create-home app
USER 10001

CMD ["python", "producer.py"]
