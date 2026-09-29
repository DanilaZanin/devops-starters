FROM docker.elastic.co/beats/filebeat:9.5.4

# The config is copied in, not bind-mounted: a bind mount from a path the Docker VM
# cannot see (a copy under macOS $TMPDIR with colima, a remote daemon) arrives empty.
# The smoke test builds with FILEBEAT_CONFIG=traps/filebeat.collect-all.yml to get the
# broken variant.
ARG FILEBEAT_CONFIG=filebeat/filebeat.yml
COPY --chown=root:root ${FILEBEAT_CONFIG} /usr/share/filebeat/filebeat.yml
