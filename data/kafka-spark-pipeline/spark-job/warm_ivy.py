"""Build-time helper: start and stop a local Spark session so spark-submit resolves --packages."""
from pyspark.sql import SparkSession

SparkSession.builder.master("local[1]").appName("warm-ivy").getOrCreate().stop()
print("ivy cache warmed")
