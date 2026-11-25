# Sphinx 3 binaries as published by the vendor (sphinxsearch.com), verified by the SHA1 listed on
# https://sphinxsearch.com/downloads/current/ - update both lines together.
FROM docker.io/library/debian:bookworm-slim
ARG SPHINX=sphinx-3.9.1-141d2ea-linux-amd64
ARG SHA1=c2934d34aeecebeba2c14f7bbeb02138b02907cc
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
 && curl -fsSL -o /tmp/sphinx.tar.gz "https://sphinxsearch.com/files/${SPHINX}.tar.gz" \
 && echo "${SHA1}  /tmp/sphinx.tar.gz" | sha1sum -c - \
 && mkdir -p /opt/sphinx && tar -xzf /tmp/sphinx.tar.gz -C /opt/sphinx --strip-components=1 \
 && rm /tmp/sphinx.tar.gz && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/lib/sphinx/data
ENV PATH=/opt/sphinx/bin:$PATH
COPY sphinx.conf /etc/sphinx/sphinx.conf
EXPOSE 9306
CMD ["searchd", "--nodetach", "--config", "/etc/sphinx/sphinx.conf"]
