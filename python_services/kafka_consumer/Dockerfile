FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip list
COPY consumer.py .
CMD ["python", "consumer.py"]