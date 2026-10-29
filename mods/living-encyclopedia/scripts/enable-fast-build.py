#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("Dockerfile")
if not p.is_file():
    raise SystemExit("Dockerfile not found")
s = p.read_text()

# BuildKit cache mounts require Dockerfile frontend syntax. Modern Docker/Compose
# already uses BuildKit in this project, so this is safe and idempotent.
if not s.startswith("# syntax=docker/dockerfile:"):
    s = "# syntax=docker/dockerfile:1.7\n" + s

# Compiler output cache: one changed Custom .cpp should not rebuild the whole core.
if "ccache" not in s.split("############################ database release", 1)[0]:
    s = re.sub(
        r"(libboost-all-dev\s+python3)(\s*\\)",
        r"\1 ccache\2",
        s,
        count=1,
    )

# Encyclopedia development does not need extractors/tools. A clean production
# build can still override this with --build-arg TOOLS=1.
s = re.sub(r"(?m)^ARG TOOLS=1\s*$", "ARG TOOLS=0", s, count=1)

# Enable ccache through CMake without replacing compilers.
if "CMAKE_CXX_COMPILER_LAUNCHER=ccache" not in s:
    s = s.replace(
        "        -DWITH_WARNINGS=0 \\\n",
        "        -DWITH_WARNINGS=0 \\\n"
        "        -DCMAKE_C_COMPILER_LAUNCHER=ccache \\\n"
        "        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \\\n",
        1,
    )

build_mount = (
    "RUN --mount=type=cache,id=wowforever-tc-build,target=/src/TrinityCore/build "
    "--mount=type=cache,id=wowforever-ccache,target=/root/.cache/ccache "
)

# Persist the CMake object tree between Docker builds. The install output still
# goes to /opt/trinitycore, so the final runtime image remains ordinary.
s = re.sub(r"(?m)^RUN cmake \.\. \\\n", build_mount + "cmake .. \\\n", s, count=1)

# The CascLib compatibility rebuild runs in the same CMake tree. Mount the same
# cache there as well or Docker would see an empty build directory in this RUN.
s = re.sub(r"(?m)^RUN sed -i ", build_mount + "sed -i ", s, count=1)

p.write_text(s)
print("Fast TrinityCore dev build enabled: BuildKit object cache + ccache + TOOLS=0")
