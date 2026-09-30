FROM apache/spark:4.1.3-python3

# The Kafka connector is resolved at BUILD time into an Ivy cache inside the image,
# so `docker compose up` does not need Maven Central and starts the same way every time.
ARG SPARK_KAFKA_PACKAGE=org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.3

USER root
RUN pip3 install --no-cache-dir "psycopg[binary]==3.3.6" \
    && mkdir -p /opt/spark/ivy /checkpoints /app \
    && chown -R spark:spark /opt/spark/ivy /checkpoints /app

WORKDIR /app
COPY --chown=spark:spark spark_job.py warm_ivy.py ./

USER spark
ENV SPARK_KAFKA_PACKAGE=${SPARK_KAFKA_PACKAGE}

# Starting any Spark app with --packages downloads the connector and its dependencies.
RUN /opt/spark/bin/spark-submit \
    --packages "${SPARK_KAFKA_PACKAGE}" \
    --conf spark.jars.ivy=/opt/spark/ivy \
    /app/warm_ivy.py

# Same coordinates and Ivy dir as above, so resolution is served from the cache.
# The exec-form CMD does not expand variables, hence the shell.
CMD ["sh", "-c", "exec /opt/spark/bin/spark-submit --packages \"$SPARK_KAFKA_PACKAGE\" --conf spark.jars.ivy=/opt/spark/ivy /app/spark_job.py"]
