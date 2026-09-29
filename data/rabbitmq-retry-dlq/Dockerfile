FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY taskqueue ./taskqueue
COPY demo_tasks.py run_worker.py produce_demo.py ./

CMD ["python", "run_worker.py"]
