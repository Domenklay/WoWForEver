# Reuse the already cached, pinned clean build and current runtime. Only this
# explicit target receives the existing Advancement adapter and FAC1 endpoint.
ARG CLEAN_BUILD_IMAGE
ARG CLEAN_RUNTIME_IMAGE
FROM ${CLEAN_BUILD_IMAGE} AS build
COPY mods/forever-advancement /advancement-module
COPY scripts/inject-advancement.py /tmp/inject-advancement.py
COPY docker/patches/0004-forever-subclass-server-addon-endpoint.patch /tmp/advancement-endpoint.patch
RUN git -C /src/TrinityCore apply /tmp/advancement-endpoint.patch \
    && python3 /tmp/inject-advancement.py /src/TrinityCore --module /advancement-module
ARG BUILD_JOBS=2
RUN cmake --build /src/TrinityCore/build -j "${BUILD_JOBS}" \
    && cmake --install /src/TrinityCore/build

FROM ${CLEAN_RUNTIME_IMAGE} AS runtime
ARG ADVANCEMENT_SOURCE
LABEL org.wowforever.baseline="advancement" org.wowforever.advancement="1.11.0" \
      org.wowforever.advancement.source="${ADVANCEMENT_SOURCE}"
COPY --from=build /opt/trinitycore /opt/trinitycore
COPY docker/clean/entrypoint.py /usr/local/bin/forever-clean-entrypoint.py
COPY mods/forever-advancement/provenance.json /opt/trinitycore/share/forever-advancement/provenance.json
RUN rm -f /opt/trinitycore/bin/pristine-servers.sha256 \
    && cd /opt/trinitycore/bin && sha256sum worldserver bnetserver > advancement-servers.sha256
