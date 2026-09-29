import os

import psycopg
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, from_json, lit, when, window
from pyspark.sql.functions import sum as spark_sum
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

KAFKA_BOOTSTRAP = os.environ["KAFKA_BOOTSTRAP"]
TOPIC = os.environ["TOPIC"]
PG_HOST = os.environ["PG_HOST"]
PG_DB = os.environ["PG_DB"]
PG_USER = os.environ["PG_USER"]
PG_PASSWORD = os.environ["PG_PASSWORD"]
# Offsets and aggregation state live here. It must be on a volume: with the default
# (a temp dir inside the container) every restart starts over from "earliest".
CHECKPOINT_DIR = os.environ["CHECKPOINT_DIR"]
# The dead-letter query reads the same topic, with its own offsets.
DEAD_LETTER_CHECKPOINT_DIR = CHECKPOINT_DIR + "-dead-letters"

schema = StructType([
    StructField("order_id", StringType()),
    StructField("product", StringType()),
    StructField("price", DoubleType()),
    StructField("quantity", IntegerType()),
    StructField("ts", StringType()),
])


def connect():
    return psycopg.connect(host=PG_HOST, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)


def ensure_dead_letter_table():
    """Created here (not only in postgres-init) so a Postgres volume from an older
    version of this module gets the table too."""
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dead_letter_events (
                topic           TEXT NOT NULL,
                kafka_partition INT NOT NULL,
                kafka_offset    BIGINT NOT NULL,
                raw_value       TEXT,
                reason          TEXT NOT NULL,
                received_at     TIMESTAMP NOT NULL DEFAULT now(),
                PRIMARY KEY (topic, kafka_partition, kafka_offset)
            )
            """
        )


def write_dead_letters(batch_df, batch_id):
    rows = batch_df.collect()
    if not rows:
        return
    # ON CONFLICT DO NOTHING: a replayed batch does not duplicate rows.
    # Postgres text cannot hold NUL bytes, and a malformed event may well contain
    # one, so it is replaced: the dead-letter writer must not become the next poison.
    with connect() as conn:
        conn.cursor().executemany(
            """
            INSERT INTO dead_letter_events (topic, kafka_partition, kafka_offset, raw_value, reason)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (r.topic, r.kafka_partition, r.kafka_offset, (r.raw_value or "").replace("\x00", "\ufffd")[:10000], r.reason)
                for r in rows
            ],
        )
    print(f"dead-letter batch {batch_id}: stored {len(rows)} malformed events", flush=True)


def write_batch_to_postgres(batch_df, batch_id):
    rows = batch_df.collect()
    if not rows:
        print(f"batch {batch_id}: nothing to write", flush=True)
        return

    # outputMode("update") re-emits a window's aggregate every trigger until
    # its watermark closes it out, so plain append would violate the
    # (window_start, product) primary key the moment a window gets a second
    # order. Upsert with ON CONFLICT instead. collect() is fine here: these
    # are small per-trigger aggregate batches (a handful to a few hundred
    # rows), not the raw event stream. The upsert also makes a replayed batch
    # (after a crash between the write and the checkpoint commit) harmless.
    # `with connect()` commits on success, rolls back on error and closes.
    with connect() as conn:
        conn.cursor().executemany(
            """
            INSERT INTO product_revenue_by_window
                (window_start, window_end, product, orders_count, revenue)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (window_start, product) DO UPDATE SET
                orders_count = EXCLUDED.orders_count,
                revenue = EXCLUDED.revenue
            """,
            [(r.window_start, r.window_end, r.product, r.orders_count, r.revenue) for r in rows],
        )

    print(f"batch {batch_id}: upserted {len(rows)} aggregated rows into postgres", flush=True)


def main():
    spark = (
        SparkSession.builder
        .appName("orders-revenue-streaming")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", TOPIC)
        .option("startingOffsets", "earliest")
        .load()
    )

    parsed = (
        raw.select(
            col("topic"),
            col("partition").alias("kafka_partition"),
            col("offset").alias("kafka_offset"),
            col("value").cast("string").alias("raw_value"),
        )
        .withColumn("data", from_json(col("raw_value"), schema))
        .withColumn("event_time", col("data.ts").cast("timestamp"))
    )

    # An event the aggregation and the sink cannot take: not a JSON object, or a field
    # the table needs is missing or has the wrong type (from_json turns those into NULL).
    # Left in the stream, one such event fails the sink (NOT NULL) on every restart.
    is_valid = (
        col("data.product").isNotNull() & (col("data.product") != "") & col("event_time").isNotNull()
        & col("data.price").isNotNull() & col("data.quantity").isNotNull()
    )

    events = (
        parsed.filter(is_valid)
        .select("data.*", "event_time")
        .withColumn("line_total", col("price") * col("quantity"))
    )

    dead_letters = parsed.filter(~is_valid).select(
        "topic",
        "kafka_partition",
        "kafka_offset",
        "raw_value",
        when(col("data").isNull(), lit("not a JSON object matching the schema"))
        .otherwise(lit("missing or invalid product, ts, price or quantity"))
        .alias("reason"),
    )

    aggregated = (
        events
        .withWatermark("event_time", "1 minute")
        .groupBy(window(col("event_time"), "1 minute"), col("product"))
        .agg(
            count("*").alias("orders_count"),
            spark_sum("line_total").alias("revenue"),
        )
        .select(
            col("window.start").alias("window_start"),
            col("window.end").alias("window_end"),
            col("product"),
            col("orders_count"),
            col("revenue"),
        )
    )

    ensure_dead_letter_table()

    (
        aggregated.writeStream
        .foreachBatch(write_batch_to_postgres)
        .outputMode("update")
        .option("checkpointLocation", CHECKPOINT_DIR)
        .trigger(processingTime="15 seconds")
        .start()
    )
    (
        dead_letters.writeStream
        .foreachBatch(write_dead_letters)
        .option("checkpointLocation", DEAD_LETTER_CHECKPOINT_DIR)
        .trigger(processingTime="15 seconds")
        .start()
    )

    # Returns (or raises) as soon as either query stops, so the container restarts.
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
