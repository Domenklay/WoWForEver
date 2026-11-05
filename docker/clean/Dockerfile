# Pristine upstream game servers. No repository gameplay patches or injected modules.
FROM ubuntu:24.04 AS build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake make gcc g++ clang libmysqlclient-dev libssl-dev \
    libbz2-dev libreadline-dev libncurses-dev libboost-all-dev python3 \
    && rm -rf /var/lib/apt/lists/*
ARG TC_COMMIT=b4e7b940593f6402a822d4fbcdf31331d16f73b6
ARG BUILD_JOBS=2
RUN git init /src/TrinityCore && git -C /src/TrinityCore remote add origin https://github.com/advocaite/TrinityCore.git \
    && git -C /src/TrinityCore fetch --depth 1 origin "${TC_COMMIT}" \
    && git -C /src/TrinityCore checkout --detach FETCH_HEAD \
    && test "$(git -C /src/TrinityCore rev-parse HEAD)" = "${TC_COMMIT}"
WORKDIR /src/TrinityCore/build
RUN cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/trinitycore \
    -DTOOLS=0 -DSERVERS=1 -DWITH_WARNINGS=0 \
    && cmake --build . -j "${BUILD_JOBS}" && cmake --install . \
    && test -z "$(git -C /src/TrinityCore status --porcelain --untracked-files=no)" \
    && cd /opt/trinitycore/bin && sha256sum worldserver bnetserver > pristine-servers.sha256

# Only extraction tools receive the existing read-only CascLib file-open fallback.
# Game servers are already installed from pristine sources and are not rebuilt.
FROM build AS tools
RUN python3 - <<'PY'
from pathlib import Path
p = Path('/src/TrinityCore/dep/CascLib/src/common/FileStream.cpp')
s = p.read_text()
old = 'handle = open(szFileName, oflag | O_LARGEFILE);'
assert s.count(old) == 1, 'Review CascLib file-open fallback against the pinned source'
p.write_text(s.replace(old, old + '\n        if(handle == -1 && oflag == O_RDWR && (errno == EROFS || errno == EACCES))\n            handle = open(szFileName, O_RDONLY | O_LARGEFILE);'))
PY
RUN cmake .. -DTOOLS=1 -DSERVERS=0 \
    && cmake --build . -j "${BUILD_JOBS}" && cmake --install . \
    && cd /opt/trinitycore/bin && sha256sum -c pristine-servers.sha256

FROM ubuntu:24.04 AS database
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl p7zip-full \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tdb
RUN curl -fL --retry 3 -o tdb.7z https://github.com/advocaite/TrinityCore/releases/download/forever-tdb-2026-10-14/TDB_full_forever_2026_10_14.7z \
    && echo '373cdca7963927d4d67933032b4b858a811eae0af960d4de4ff19833a88d4f41  tdb.7z' | sha256sum -c - \
    && 7z e -y tdb.7z '*.sql' -r && rm tdb.7z \
    && sed -i -E 's#/\*!50013 DEFINER=`[^`]*`@`[^`]*` SQL SECURITY DEFINER \*/##' /tdb/*.sql \
    && ! grep -l 'DEFINER=' /tdb/*.sql

FROM ubuntu:24.04 AS runtime
ARG TC_COMMIT=b4e7b940593f6402a822d4fbcdf31331d16f73b6
LABEL org.wowforever.core="${TC_COMMIT}" org.wowforever.baseline="clean" org.wowforever.advancement="none"
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tzdata mysql-client python3 libmysqlclient21 libssl3t64 libbz2-1.0 \
    libreadline8t64 libncurses6 libboost-filesystem1.83.0 libboost-program-options1.83.0 \
    libboost-regex1.83.0 libboost-locale1.83.0 libboost-thread1.83.0 libboost-iostreams1.83.0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tools /opt/trinitycore /opt/trinitycore
COPY --from=build /src/TrinityCore/sql /src/TrinityCore/sql
COPY --from=database /tdb/ /opt/trinitycore/bin/
COPY docker/clean/entrypoint.py /usr/local/bin/forever-clean-entrypoint.py
COPY docker/clean/extract.sh /usr/local/bin/forever-clean-extract.sh
RUN chmod +x /usr/local/bin/forever-clean-extract.sh \
    && mkdir -p /opt/trinitycore/data /opt/trinitycore/logs /opt/trinitycore/certs
ENV LD_LIBRARY_PATH=/opt/trinitycore/lib
WORKDIR /opt/trinitycore/bin
ENTRYPOINT ["python3", "/usr/local/bin/forever-clean-entrypoint.py"]
CMD ["worldserver"]
