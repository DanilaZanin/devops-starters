# Same pinned tecnativa/docker-socket-proxy (HAProxy) image, but with our own config:
# its env switches allow whole path prefixes (CONTAINERS=1 also lets through
# /containers/{id}/attach/ws with stdin, /logs, /archive, /exec ...), ours a short list of paths.
FROM tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
COPY docker-proxy/haproxy.cfg /usr/local/etc/haproxy/allowlist.cfg
CMD ["haproxy", "-f", "/usr/local/etc/haproxy/allowlist.cfg"]
