ARG CLEAN_BUILD_IMAGE
ARG CLEAN_RUNTIME_IMAGE
FROM ${CLEAN_BUILD_IMAGE} AS build
COPY mods/forever-advancement /gameplay/mods/forever-advancement
COPY mods/living-encyclopedia /gameplay/mods/living-encyclopedia
COPY mod-forever-scaling /gameplay/mod-forever-scaling
COPY mods/forever-dungeon-finder /gameplay/mods/forever-dungeon-finder
COPY scripts/inject-advancement.py scripts/inject-gameplay.py scripts/inject-forever-scaling.py scripts/inject-forever-dungeons.py scripts/inject-forever-dungeon-finder.py /gameplay/scripts/
COPY docker/patches/0004-forever-subclass-server-addon-endpoint.patch /tmp/gameplay-endpoint.patch
RUN git -C /src/TrinityCore apply /tmp/gameplay-endpoint.patch \
    && python3 /gameplay/scripts/inject-gameplay.py /src/TrinityCore
ARG BUILD_JOBS=2
RUN cmake -S /src/TrinityCore -B /src/TrinityCore/build \
    && cmake --build /src/TrinityCore/build -j "${BUILD_JOBS}" \
    && cmake --install /src/TrinityCore/build

FROM ${CLEAN_RUNTIME_IMAGE} AS runtime
ARG ADVANCEMENT_SOURCE
ARG GAMEPLAY_SOURCE
LABEL org.wowforever.baseline="gameplay" org.wowforever.advancement="1.11.0" \
      org.wowforever.advancement.source="${ADVANCEMENT_SOURCE}" \
      org.wowforever.encyclopedia="0.9.8-v2.1-smartai-abilities" org.wowforever.scaling="0.4.0" org.wowforever.dungeonfinder="0.2.0" \
      org.wowforever.gameplay.source="${GAMEPLAY_SOURCE}"
COPY --from=build /opt/trinitycore /opt/trinitycore
COPY docker/clean/entrypoint.py /usr/local/bin/forever-clean-entrypoint.py
COPY mods/forever-advancement/provenance.json /opt/trinitycore/share/forever-advancement/provenance.json
RUN rm -f /opt/trinitycore/bin/pristine-servers.sha256 /opt/trinitycore/bin/advancement-servers.sha256 \
    && cd /opt/trinitycore/bin && sha256sum worldserver bnetserver > gameplay-servers.sha256
