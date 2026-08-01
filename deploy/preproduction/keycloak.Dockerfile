FROM quay.io/keycloak/keycloak:26.7.0

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/oidc

RUN /opt/keycloak/bin/kc.sh build
