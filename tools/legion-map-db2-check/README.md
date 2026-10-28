# Native Map.db2 validation

`check-map.cpp` uses the pinned Forever core's real `DB2FileLoader` and
`MapMeta`. It prints one row per readable map; strings are UTF-8 bytes encoded
as hex so embedded line breaks cannot split records. Opaque sections are skipped,
without providing keys or changing their contents.

Compile against the same core headers and `common`/`fmt` libraries used to build
the server. The cloud check used the already-built libraries in the subclass
build workspace; this tool does not require rebuilding the user's server.
Set `MAP_DB2_NATIVE_CHECKER` to the resulting executable when running Python tests.

On the previously uploaded 70532 Map.db2, the source yields 73 readable maps.
The prototype adds Map 1220 with private WDT 15730590, yielding 74 readable maps;
all 73 previous output rows match exactly. This establishes core-loader acceptance,
not acceptance by WowB.exe or availability of server maps/vmaps.

The new map keeps map zero's settings as a prototype template, clears its ZMP
reference, and assigns a unique directory and new WDT. Settings and world flags
still require actual client/server testing before use.
