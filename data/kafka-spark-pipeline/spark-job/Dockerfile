FROM apache/spark:3.5.3

USER root
RUN pip install --no-cache-dir psycopg2-binary==2.9.9
COPY spark_job.py /app/spark_job.py
WORKDIR /app

# spark-sql-kafka connector + postgres jdbc driver get pulled from Maven the
# first time spark-submit runs with --packages; no need to bake jars into
# the image, just eats ~30s on first start while it resolves them.
CMD ["/opt/spark/bin/spark-submit", \
     "--packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,org.postgresql:postgresql:42.7.3", \
     "/app/spark_job.py"]
