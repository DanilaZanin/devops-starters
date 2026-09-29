import os

import psycopg
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, from_json, window
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

schema = StructType([
    StructField("order_id", StringType()),
    StructField("product", StringType()),
    StructField("price", DoubleType()),
    StructField("quantity", IntegerType()),
    StructField("ts", StringType()),
])


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
    with psycopg.connect(host=PG_HOST, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD) as conn:
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

    events = (
        raw.select(from_json(col("value").cast("string"), schema).alias("data"))
        .select("data.*")
        .withColumn("event_time", col("ts").cast("timestamp"))
        .withColumn("line_total", col("price") * col("quantity"))
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

    query = (
        aggregated.writeStream
        .foreachBatch(write_batch_to_postgres)
        .outputMode("update")
        .option("checkpointLocation", CHECKPOINT_DIR)
        .trigger(processingTime="15 seconds")
        .start()
    )

    query.awaitTermination()


if __name__ == "__main__":
    main()
