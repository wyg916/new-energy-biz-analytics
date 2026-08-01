FROM postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777

# The upstream entrypoint needs a privilege-drop helper. Replace the static
# gosu binary (built with a vulnerable Go stdlib in this upstream snapshot)
# with Alpine's small C-based, command-compatible su-exec implementation.
RUN apk add --no-cache su-exec \
    && rm -f /usr/local/bin/gosu \
    && ln -s /sbin/su-exec /usr/local/bin/gosu
