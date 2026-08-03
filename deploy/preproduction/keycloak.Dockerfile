FROM scratch AS patched-jars

ADD --checksum=sha256:4b40a06396f239f8de2da57419adde6e94e5edc18a2171d471ea05eeed4e5c2d \
    https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-core/2.21.4/jackson-core-2.21.4.jar \
    /jackson-core.jar
ADD --checksum=sha256:3888e9e69ab66fbacaacc9aea0e9ffbf15368288e4aca468b024dba11c09fbf9 \
    https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.21.4/jackson-databind-2.21.4.jar \
    /jackson-databind.jar
ADD --checksum=sha256:2de4fc13005c7740b46427a47ee04265a19779c147d53e583f441889b1148159 \
    https://repo.maven.apache.org/maven2/io/netty/netty-codec/4.1.136.Final/netty-codec-4.1.136.Final.jar \
    /netty-codec.jar
ADD --checksum=sha256:841be7fc6f1c929ecc63c70a909e0df085b4e80e44680acf46708f0e93e68037 \
    https://repo.maven.apache.org/maven2/io/netty/netty-codec-haproxy/4.1.136.Final/netty-codec-haproxy-4.1.136.Final.jar \
    /netty-codec-haproxy.jar
ADD --checksum=sha256:ffd1e1b19a533bc6e47ef2cbc1290374ff4a7cb53a280defa3df392538214948 \
    https://repo.maven.apache.org/maven2/io/netty/netty-codec-http/4.1.136.Final/netty-codec-http-4.1.136.Final.jar \
    /netty-codec-http.jar
ADD --checksum=sha256:14f67ae095c056b062aa0ee2c7b01f6b78004cf3620a6e9061bcb637f079387a \
    https://repo.maven.apache.org/maven2/io/netty/netty-codec-http2/4.1.136.Final/netty-codec-http2-4.1.136.Final.jar \
    /netty-codec-http2.jar
ADD --checksum=sha256:31fbf6f06b2217fb51d5100cee51b22625cc81640da0679b47914e54c1e6377c \
    https://repo.maven.apache.org/maven2/org/postgresql/postgresql/42.7.12/postgresql-42.7.12.jar \
    /postgresql.jar

FROM quay.io/keycloak/keycloak:26.7.0@sha256:0f198be292568439d700cdbfb893e69a6009bb43a94a06a945b1d3d506c76b13 AS hardened-root

USER 0
COPY --from=patched-jars /jackson-core.jar /opt/keycloak/lib/lib/main/com.fasterxml.jackson.core.jackson-core-2.21.2.jar
COPY --from=patched-jars /jackson-databind.jar /opt/keycloak/lib/lib/main/com.fasterxml.jackson.core.jackson-databind-2.21.2.jar
COPY --from=patched-jars /netty-codec.jar /opt/keycloak/lib/lib/main/io.netty.netty-codec-4.1.135.Final.jar
COPY --from=patched-jars /netty-codec-haproxy.jar /opt/keycloak/lib/lib/main/io.netty.netty-codec-haproxy-4.1.135.Final.jar
COPY --from=patched-jars /netty-codec-http.jar /opt/keycloak/lib/lib/main/io.netty.netty-codec-http-4.1.135.Final.jar
COPY --from=patched-jars /netty-codec-http2.jar /opt/keycloak/lib/lib/main/io.netty.netty-codec-http2-4.1.135.Final.jar
COPY --from=patched-jars /postgresql.jar /opt/keycloak/lib/lib/main/org.postgresql.postgresql-42.7.11.jar

# The v4 release supports PostgreSQL only. Removing the unused MSSQL driver
# eliminates its CVE without changing the supported database contract.
RUN /opt/keycloak/bin/kc.sh build --db=postgres \
    && rm -f /opt/keycloak/lib/lib/main/com.microsoft.sqlserver.mssql-jdbc-13.2.1.jre11.jar

# Flatten the merged filesystem so removed or overwritten vulnerable JARs are
# not shipped in recoverable parent layers.
FROM scratch
COPY --from=hardened-root / /

ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=en_US.UTF-8 \
    KC_RUN_IN_CONTAINER=true \
    KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/oidc

USER 1000
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
EXPOSE 8080 8443 9000

LABEL org.opencontainers.image.source="https://github.com/keycloak/keycloak" \
      org.opencontainers.image.version="26.7.0-p5b-hardened" \
      org.opencontainers.image.licenses="Apache-2.0"
