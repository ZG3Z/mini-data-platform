#!/bin/bash

ENDPOINT="http://localhost:9005"
ACCESS_KEY="minio"
SECRET_KEY="minio123"
BUCKET="delta-bucket"
TARGET_DIR="minio" 

curl -s -O https://dl.min.io/client/mc/release/darwin-amd64/mc
chmod +x ./mc

./mc alias set localminio "$ENDPOINT" "$ACCESS_KEY" "$SECRET_KEY"

echo "Searching recursively for .parquet files in bucket: $BUCKET"

mkdir -p "$TARGET_DIR"

./mc find localminio/"$BUCKET" --name "*.parquet" | while read -r FILE_PATH; do
    RELATIVE_PATH="${FILE_PATH#localminio/$BUCKET/}"
    LOCAL_PATH="$TARGET_DIR/$RELATIVE_PATH"
    LOCAL_DIR=$(dirname "$LOCAL_PATH")

    mkdir -p "$LOCAL_DIR"
    echo "Downloading: $FILE_PATH → $LOCAL_PATH"
    ./mc cp "$FILE_PATH" "$LOCAL_PATH"
done

rm mc