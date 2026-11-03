# syntax=docker/dockerfile:1
# Standalone local CASC reader. Does not configure/build either game server.
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake make g++ libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

ARG TC_REPO=https://github.com/advocaite/TrinityCore.git
ARG TC_COMMIT=91d49b230f89c3ab4719f5b2b2d1e70ed36613c4
ARG BUILD_JOBS=2
# Optional managed-environment CA is mounted for Git only, never copied to layers.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export GIT_SSL_CAINFO=/run/secrets/proxy_ca; fi; \
    git init /src/TrinityCore \
    && git -C /src/TrinityCore remote add origin "${TC_REPO}" \
    && git -C /src/TrinityCore sparse-checkout init --cone \
    && git -C /src/TrinityCore sparse-checkout set dep/CascLib \
    && git -C /src/TrinityCore fetch --depth 1 --filter=blob:none origin "${TC_COMMIT}" \
    && git -C /src/TrinityCore checkout --detach FETCH_HEAD

# Same read-only-open fallback as the full probe; no ROOT/variant policy changes.
RUN sed -i 's|handle = open(szFileName, oflag \| O_LARGEFILE);|handle = open(szFileName, oflag \| O_LARGEFILE);\n        if(handle == -1 \&\& oflag == O_RDWR \&\& (errno == EROFS \|\| errno == EACCES))\n            handle = open(szFileName, O_RDONLY \| O_LARGEFILE);|' \
        /src/TrinityCore/dep/CascLib/src/common/FileStream.cpp \
    && grep -q 'errno == EROFS' /src/TrinityCore/dep/CascLib/src/common/FileStream.cpp

COPY tools/legion-casc-probe/minimal/CMakeLists.txt /probe-build/CMakeLists.txt
RUN cmake -S /probe-build -B /probe-build/output -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /probe-build/output --target casc --parallel "${BUILD_JOBS}"

COPY tools/legion-casc-probe/check-storage.cpp /probe-build/check-storage.cpp
RUN c++ -std=c++20 -O2 -I/src/TrinityCore/dep/CascLib/src \
    /probe-build/check-storage.cpp /src/TrinityCore/build/dep/CascLib/libcasc.a \
    -lz -lcrypto -o /usr/local/bin/check-storage
LABEL org.wowforever.casc-reader="standalone" \
      org.wowforever.casc-source="91d49b230f89c3ab4719f5b2b2d1e70ed36613c4"
ENTRYPOINT ["/usr/local/bin/check-storage"]
