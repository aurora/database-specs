# Sphinx 2.2.11 (last open-source release) from Debian's own package - no third-party binaries.
FROM docker.io/library/debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends sphinxsearch=2.2.11-8+b1 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/lib/sphinx /var/run/sphinx /var/log/sphinx
COPY sphinx.conf /etc/sphinx/sphinx.conf
EXPOSE 9306
CMD ["searchd", "--nodetach", "--config", "/etc/sphinx/sphinx.conf"]
