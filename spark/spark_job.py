import logging
import traceback
from pyspark.sql import SparkSession, DataFrame, Column
from pyspark.sql.functions import col, current_timestamp, when, regexp_extract, length

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("kafka-avro-to-delta")

class AvroDeserializer:
    def __init__(self, spark: SparkSession, schema_registry_url: str):
        self.spark = spark
        self.schema_registry_url = schema_registry_url

    def from_confluent_avro(self, value_col: Column, topic: str, is_key: bool = False) -> Column:
        jvm = self.spark._jvm
        abris_config = (
            jvm.za.co.absa.abris.config.AbrisConfig
            .fromConfluentAvro()
            .downloadReaderSchemaByLatestVersion()
            .andTopicNameStrategy(topic, is_key)
            .usingSchemaRegistry(self.schema_registry_url)
        )
        return Column(
            jvm.za.co.absa.abris.avro.functions.from_avro(
                value_col._jc, abris_config
            )
        )

    def deserialize(self, df: DataFrame, topic: str, is_key: bool = False) -> DataFrame:
        logger.info(f"Deserializing Avro data for topic: {topic}")
        try:
            result = df.select(
                col("message_key"),
                self.from_confluent_avro(col("avro_value"), topic, is_key).alias("data"),
                col("topic"),
                col("partition"),
                col("offset"),
                col("timestamp")
            ).select(
                col("message_key"),
                col("data.*"),
                col("topic"),
                col("partition"),
                col("offset"),
                col("timestamp")
            )
            logger.info(f"Avro deserialization completed for {topic}")
            return result
        except Exception as e:
            logger.error(f"Failed to deserialize Avro data for {topic}: {e}")
            raise

class DataTransformer:
    @staticmethod
    def transform_product(df: DataFrame) -> DataFrame:
        logger.info("Transforming product data")
        try:
            result = df.select(
                col("after.id").cast("integer").alias("product_id"),
                col("after.name").alias("product_name"),
                col("after.price").cast("decimal(10,2)").alias("price_decimal"),
                col("after.category"),
                current_timestamp().alias("processed_at"),
                col("timestamp").alias("kafka_timestamp"),
                col("partition").alias("kafka_partition"),
                col("offset").alias("kafka_offset")
            ).withColumn("price_category", 
                when(col("price_decimal") < 10, "Low")
                .when(col("price_decimal") < 100, "Medium")
                .otherwise("High")
            )
            logger.info("Product data transformation completed")
            return result
        except Exception as e:
            logger.error(f"Failed to transform product data: {e}")
            raise

    @staticmethod
    def transform_transaction(df: DataFrame) -> DataFrame:
        logger.info("Transforming transaction data")
        try:
            result = df.select(
                col("after.id").cast("integer").alias("transaction_id"),
                col("after.user_id").cast("integer").alias("user_id"),
                col("after.amount").cast("decimal(15,2)").alias("amount_decimal"),
                col("after.currency"),
                current_timestamp().alias("processed_at"),
                col("timestamp").alias("kafka_timestamp"),
                col("partition").alias("kafka_partition"),
                col("offset").alias("kafka_offset")
            ).withColumn("amount_category",
                when(col("amount_decimal") < 100, "Small")
                .when(col("amount_decimal") < 1000, "Medium")
                .otherwise("Large")
            ).withColumn("is_usd", col("currency") == "USD")
            logger.info("Transaction data transformation completed")
            return result
        except Exception as e:
            logger.error(f"Failed to transform transaction data: {e}")
            raise

    @staticmethod
    def transform_user(df: DataFrame) -> DataFrame:
        logger.info("Transforming user data")
        try:
            result = df.select(
                col("after.id").cast("integer").alias("user_id"),
                col("after.name").alias("user_name"),
                col("after.email"),
                current_timestamp().alias("processed_at"),
                col("timestamp").alias("kafka_timestamp"),
                col("partition").alias("kafka_partition"),
                col("offset").alias("kafka_offset")
            ).withColumn("email_domain", 
                regexp_extract(col("email"), "@(.+)", 1)
            ).withColumn("name_length", length(col("user_name")))
            logger.info("User data transformation completed")
            return result
        except Exception as e:
            logger.error(f"Failed to transform user data: {e}")
            raise

class DeltaWriter:
    @staticmethod
    def write_stream_with_log(df: DataFrame, path: str, checkpoint_location: str):
        def log_and_write(batch_df, epoch_id):
            logger.info(f"Processing batch {epoch_id} for path: {path}")
            try:
                batch_df.show(truncate=False)
                batch_df.write.format("delta").mode("append").option("mergeSchema", "true").save(path)
                logger.info(f"Batch {epoch_id} written successfully to {path}")
            except Exception as e:
                logger.error(f"Failed to write batch {epoch_id} to {path}: {e}")
                raise
        
        return df.writeStream \
            .foreachBatch(log_and_write) \
            .outputMode("append") \
            .option("checkpointLocation", checkpoint_location) \
            .start()

class KafkaAvroToDeltaJob:
    def __init__(self):
        logger.info("Initializing Spark session")
        try:
            self.spark = SparkSession.builder \
                .appName("KafkaAvroToDelta") \
                .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
                .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
                .config("spark.sql.parquet.compression.codec", "uncompressed") \
                .config("spark.sql.delta.compression.codec", "uncompressed") \
                .config("spark.hadoop.fs.s3a.endpoint", "http://minio:9000") \
                .config("spark.hadoop.fs.s3a.access.key", "minio") \
                .config("spark.hadoop.fs.s3a.secret.key", "minio123") \
                .config("spark.hadoop.fs.s3a.path.style.access", "true") \
                .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
                .getOrCreate()
            self.spark.sparkContext.setLogLevel("WARN")
            logger.info("Spark session initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Spark session: {e}")
            raise
            
        self.schema_registry_url = "http://schema-registry:8081"
        self.kafka_bootstrap_servers = "kafka:9092"
        self.deserializer = AvroDeserializer(self.spark, self.schema_registry_url)

    def read_kafka_stream(self, topic_name: str) -> DataFrame:
        logger.info(f"Creating Kafka stream for topic: {topic_name}")
        try:
            result = self.spark.readStream \
                .format("kafka") \
                .option("kafka.bootstrap.servers", self.kafka_bootstrap_servers) \
                .option("subscribe", topic_name) \
                .option("startingOffsets", "earliest") \
                .load() \
                .select(
                    col("key").cast("string").alias("message_key"),
                    col("value").alias("avro_value"),
                    col("topic"),
                    col("partition"),
                    col("offset"),
                    col("timestamp")
                )
            logger.info(f"Kafka stream created for {topic_name}")
            return result
        except Exception as e:
            logger.error(f"Failed to create Kafka stream for {topic_name}: {e}")
            raise

    def run(self):
        try:
            logger.info("Starting Kafka stream processing")

            product_stream = self.read_kafka_stream("pg_server.public.products")
            transaction_stream = self.read_kafka_stream("pg_server.public.transactions")
            user_stream = self.read_kafka_stream("pg_server.public.users")

            logger.info("Kafka streams created successfully")

            product_avro = self.deserializer.deserialize(product_stream, "pg_server.public.products")
            transaction_avro = self.deserializer.deserialize(transaction_stream, "pg_server.public.transactions")
            user_avro = self.deserializer.deserialize(user_stream, "pg_server.public.users")

            logger.info("Avro deserialization completed")

            product_transformed = DataTransformer.transform_product(product_avro)
            transaction_transformed = DataTransformer.transform_transaction(transaction_avro)
            user_transformed = DataTransformer.transform_user(user_avro)

            logger.info("Data transformations completed")

            logger.info("Starting Delta Lake streaming writes")
            DeltaWriter.write_stream_with_log(
                product_transformed, 
                "s3a://delta-bucket/products",
                "s3a://delta-checkpoint/products"
            )
            DeltaWriter.write_stream_with_log(
                transaction_transformed, 
                "s3a://delta-bucket/transactions",
                "s3a://delta-checkpoint/transactions"
            )
            DeltaWriter.write_stream_with_log(
                user_transformed, 
                "s3a://delta-bucket/users",
                "s3a://delta-checkpoint/users"
            )

            logger.info("Streaming jobs started successfully")
            logger.info("Monitoring active streams...")
            self.spark.streams.awaitAnyTermination()

        except Exception as e:
            logger.error(f"Processing failed: {str(e)}")
            traceback.print_exc()
            logger.info("Stopping active streams...")
            for stream in self.spark.streams.active:
                stream.stop()
            raise e

if __name__ == "__main__":
    KafkaAvroToDeltaJob().run()