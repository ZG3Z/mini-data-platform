import os
import logging
import time
from confluent_kafka import Consumer, KafkaException, KafkaError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("kafka-consumer")

BOOTSTRAP_SERVERS = os.environ["BOOTSTRAP_SERVERS"]
SCHEMA_REGISTRY_URL = os.environ["SCHEMA_REGISTRY_URL"]
TOPICS = os.environ["TOPICS"].split(",")
AUTO_OFFSET_RESET = os.environ.get("AUTO_OFFSET_RESET", "earliest")
GROUP_ID = os.environ.get("GROUP_ID", "python-consumer-group")

def create_consumer():
    schema_registry_conf = {'url': SCHEMA_REGISTRY_URL}
    schema_registry_client = SchemaRegistryClient(schema_registry_conf)
    avro_deserializer = AvroDeserializer(schema_registry_client)
    consumer_config = {
        'bootstrap.servers': BOOTSTRAP_SERVERS,
        'group.id': GROUP_ID,
        'auto.offset.reset': AUTO_OFFSET_RESET,
        'enable.auto.commit': True,
    }
    consumer = Consumer(consumer_config)
    return consumer, avro_deserializer

def process_message(msg, avro_deserializer):
    try:
        value = avro_deserializer(msg.value(), None)
        logger.info(f"[{msg.topic()}] {value}")
    except Exception as e:
        logger.error(f"Error deserializing Avro message: {e}")

def subscribe_with_retry(consumer, topics, max_retries=10, retry_interval=5):
    retries = 0
    while retries < max_retries:
        try:
            consumer.subscribe(topics)
            logger.info(f"Subscribed to: {topics}")
            return
        except KafkaException as e:
            err = e.args[0]
            if err.code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                logger.warning("Topics not yet available. Retrying in 5s...")
                time.sleep(retry_interval)
                retries += 1
            else:
                raise
    logger.error("Failed to subscribe to topics after retries. Exiting.")
    exit(1)

def main():
    consumer, avro_deserializer = create_consumer()
    logger.info("Waiting 10s before subscribing to topics...")
    time.sleep(10)
    subscribe_with_retry(consumer, TOPICS)
    
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() in (KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART):
                    continue
                else:
                    raise KafkaException(msg.error())
            if msg.value() is None:
                logger.info(f"[{msg.topic()}] Tombstone for key {msg.key()}; skipping")
                continue
            process_message(msg, avro_deserializer)
    except KeyboardInterrupt:
        logger.info("Consumer interrupted by user")
    finally:
        consumer.close()
        logger.info("Consumer closed")

if __name__ == "__main__":
    main()