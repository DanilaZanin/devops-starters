FROM trinodb/trino:483

# Config, sample data and the trap script are copied in instead of bind-mounted: a bind
# mount from a path the Docker VM cannot see (a copy under macOS $TMPDIR with colima, a
# remote daemon) arrives empty.
COPY trino/catalog/iceberg.properties /etc/trino/catalog/iceberg.properties
COPY sample_data /sample_data
COPY traps /traps
