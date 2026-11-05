FROM ubuntu:24.04 AS compiler
RUN apt-get update && apt-get install -y --no-install-recommends mono-mcs mono-runtime \
    && rm -rf /var/lib/apt/lists/*
FROM compiler AS test
COPY tools/local-login/LocalKey.cs tests/fixtures/local-key-tests.cs /test/
RUN mcs -langversion:5 -warnaserror -out:/test/LocalKeyTests.exe /test/LocalKey.cs /test/local-key-tests.cs \
    && mono /test/LocalKeyTests.exe
