FROM postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777 AS upstream

# The upstream entrypoint needs a privilege-drop helper. Replace the static
# gosu binary (built with a vulnerable Go stdlib in this upstream snapshot)
# with Alpine's small C-based, command-compatible su-exec implementation.
RUN apk add --no-cache su-exec \
    && rm -f /usr/local/bin/gosu \
    && ln -s /sbin/su-exec /usr/local/bin/gosu

# Copy the merged filesystem into a fresh image so the deleted Go binary is
# absent from every shipped layer. A normal child layer leaves the vulnerable
# binary recoverable and visible to layer-aware scanners even after deletion.
FROM scratch
COPY --from=upstream / /

ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=en_US.utf8 \
    PG_MAJOR=16 \
    PG_VERSION=16.14 \
    PG_SHA256=f6d077142737920858ce958ccdb75c6ee137a63b5b0853c70693d401ac7e3471 \
    DOCKER_PG_LLVM_DEPS="llvm21-dev clang21" \
    PGDATA=/var/lib/postgresql/data

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]
EXPOSE 5432
VOLUME ["/var/lib/postgresql/data"]
STOPSIGNAL SIGINT
