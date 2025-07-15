FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Kopiujemy tylko kod Pythona i wymagania
COPY insert_data.py /app/insert_data.py

# Do wrzucenia danych CSV używamy montowania w docker-compose,
# więc nie kopiujemy ich do obrazu – zostaną udostępnione przez wolumen.
# Jeśli jednak wolisz trzymać je w obrazie, możesz użyć:
# COPY data /app/data

# # Instalujemy zależności
# RUN pip install -r requirements.txt

CMD ["python", "insert_data.py"]
