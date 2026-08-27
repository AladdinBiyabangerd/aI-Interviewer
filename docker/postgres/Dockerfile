ARG POSTGRES_IMAGE="postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"

FROM ${POSTGRES_IMAGE}

# The service starts as the image's postgres user, so the root-only privilege
# drop helper is unreachable and is removed from the final filesystem.
USER root
RUN apk add --no-cache --upgrade \
        "libcrypto3=3.5.8-r0" \
        "libssl3=3.5.8-r0" \
    && rm -f /usr/local/bin/gosu

USER postgres
