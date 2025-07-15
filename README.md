# Mini Data Platform w kontenerach Docker

Platforma danych zbudowana w oparciu o kontenery Docker, która symuluje proces biznesowy, przetwarza dane przez PostgreSQL, Debezium, Kafka, Spark i przechowuje je w MinIO w formacie Delta Lake.

## Spis treści

- [Architektura systemu](#architektura-systemu)
- [Struktura projektu](#struktura-projektu)
- [Wdrożenie od podstaw](#wdrożenie-od-podstaw)
- [Dodawanie nowych danych](#dodawanie-nowych-danych)
- [Pobieranie danych z MinIO](#pobieranie-danych-z-minio)
- [Monitorowanie systemu](#monitorowanie-systemu)

## Architektura systemu

```
CSV Data → PostgreSQL → Debezium → Kafka (AVRO) → Spark → MinIO (Delta Lake)
```

System składa się z następujących komponentów:
- **PostgreSQL** - źródłowa baza danych 
- **Debezium** - Change Data Capture (CDC) dla PostgreSQL
- **Apache Kafka** - broker wiadomości 
- **Schema Registry** - zarządzanie schematami AVRO
- **Apache Spark** - przetwarzanie strumieniowe danych
- **MinIO** - magazyn obiektów kompatybilny z S3

## Struktura projektu

```
.
├── README.md
├── docker-compose.yml             # Główny plik orkiestracji
├── .env                           # Konfiguracja zmiennych środowiskowych 
├── minio_download.sh              # Skrypt do pobierania danych z MinIO
├── debezium/
│   ├── register_debezium.json     # Konfiguracja konektora Debezium
│   └── plugins/                   # Wtyczki konektora Debezium 
├── python_services/
│   ├── db_seeder/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── insert_data.py         # Skrypt do inicjalizacji bazy danych
│   │   └── data/                  # Folder z plikiami danych
│   └── kafka_consumer/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── consumer.py            # Konsument Kafka AVRO
└── spark/
    └── spark_job.py               # Job Spark Streaming
```

## Wdrożenie od podstaw

### 1. Klonowanie repozytorium

```bash
git clone <repository-url>
cd mini-data-platform-s23570
```

### 2. Weryfikacja pliku konfiguracyjnego

Plik `.env` jest już przykładowo skonfigurowany. Zawiera wszystkie niezbędne zmienne środowiskowe dla poszczególnych serwisów.

### 3. Uruchomienie całej platformy

```bash
# Budowanie obrazów i uruchomienie wszystkich serwisów
docker-compose up --build -d 

# Podgląd logów wszystkich serwisów
docker-compose logs -f
```

### 4. Weryfikacja uruchomienia serwisów

```bash
# Sprawdzenie zdrowia PostgreSQL
docker-compose exec postgres pg_isready -U postgres

# Sprawdzenie Kafka
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Sprawdzenie Schema Registry
curl http://localhost:8081/subjects

# Sprawdzenie Kafka Connect
curl http://localhost:8083/connectors
```

### 5. Automatyczna konfiguracja

System automatycznie:
- Inicjalizuje bazę danych PostgreSQL z danymi z plików CSV
- Rejestruje konektor Debezium
- Konfiguruje buckets w MinIO
- Uruchamia job Spark Streaming

## Dodawanie nowych danych

### Rozszerzanie danych przez db-seeder

Dane można rozszerzać wyłącznie poprzez dodawanie nowych linijek do istniejących 3 plików CSV w katalogu `python_services/db_seeder/data/`:

1. **Dodanie nowych rekordów do plików CSV:**
   ```bash
   # Edytuj istniejące pliki CSV dodając nowe linie
   nano python_services/db_seeder/data/users.csv
   nano python_services/db_seeder/data/products.csv  
   nano python_services/db_seeder/data/transactions.csv
   ```

2. **Uruchomienie db-seeder z nowymi danymi:**
   ```bash
   # Reset i uruchomienie db-seeder
   docker-compose up -d db-seeder
   ```

3. **Weryfikacja dodania danych:**
   ```bash
   # Sprawdzenie logów db-seeder
   docker-compose logs db-seeder
   
   # Połączenie z PostgreSQL i sprawdzenie danych
   docker-compose exec postgres psql -U user -d mydatabase -c "SELECT COUNT(*) FROM users;"
   ```

### Automatyczne przechwytywanie zmian

Po dodaniu nowych danych:
- Debezium automatycznie przechwytuje zmiany w PostgreSQL
- Nowe dane są wysyłane do Kafka w formacie AVRO jako komunikaty
- Spark przetwarza strumieniowo napływające komunikaty
- Przetworzone dane trafiają do MinIO w formacie Delta

**Uwaga:** Nie dodawaj nowych plików CSV - system jest skonfigurowany do pracy z trzema konkretnymi plikami.

## Pobieranie danych z MinIO

### Metoda 1: Interfejs webowy MinIO

1. Otwórz przeglądarkę i przejdź do: http://localhost:9006
2. Zaloguj się używając danych z pliku `.env`:
   - Login: `minio`
   - Hasło: `minio123`
3. Przeglądaj buckets `delta-bucket` i `delta-checkpoint`
4. Pobierz pliki ręcznie przez interfejs webowy

### Metoda 2: Bezpośrednie polecenia MinIO Client

```bash
# Uruchomienie kontenera MinIO Client z dostępem do sieci platformy
docker run --rm -it --network mini-data-platform_data-platform \
  minio/mc:latest /bin/sh

# W uruchomionym kontenerze mc wykonaj następujące polecenia:
# Konfiguracja aliasu dla lokalnego MinIO
mc alias set local http://minio:9000 minio minio123

# Wyświetlenie listy buckets
mc ls local/

# Pobranie wszystkich danych z bucket delta-bucket
mc cp -r local/delta-bucket/ /tmp/minio/

```

**Przykład:** Użycie skryptu minio_download.sh

W projekcie dostępny jest gotowy skrypt `minio_download.sh` automatyzujący proces pobierania danych z MinIO.

```bash
# Nadanie uprawnień wykonywania skryptu
chmod +x minio_download.sh

# Pobranie wszystkich danych z MinIO
./minio_download.sh

# Sprawdzenie pobranych danych w lokalnym katalogu
ls -la minio/
```

## Monitorowanie systemu

### Sprawdzanie statusu serwisów

```bash
# Status wszystkich kontenerów
docker-compose ps

# Logi poszczególnych serwisów
docker-compose logs postgres
docker-compose logs kafka
docker-compose logs spark
docker-compose logs kafka-consumer
```

### Monitorowanie Kafka

```bash
# Lista topików
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Szczegóły topiku
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --describe --topic pg_server.public.users

# Konsumowanie wiadomości z topiku
docker-compose exec kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic pg_server.public.users --from-beginning
```

### Dostęp do interfejsów webowych

- **MinIO Console**: http://localhost:9006 (minio/minio123)
- **Schema Registry**: http://localhost:8081/subjects
- **Kafka Connect REST API**: http://localhost:8083

## Czyszczenie i restart

```bash
# Pełny restart platformy z przebudowaniem obrazów
docker-compose up -d --build

# Zatrzymanie wszystkich kontenerów bez usuwania danych
docker-compose down

# Zatrzymanie kontenerów i usunięcie wolumenów (UWAGA: usuwa wszystkie dane!)
docker-compose down -v

# Usunięcie nieużywanych kontenerów, sieci, obrazów i wolumenów
docker system prune -f --volumes

# Zatrzymanie kontenerów i usunięcie wszystkich powiązanych obrazów
docker-compose down --rmi all
```
