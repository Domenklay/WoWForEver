#!/usr/bin/env python3
"""Verify isolated staged VMAP names with the pinned native VMAP manager."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('geometry_builder', root/'build-tools.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
with tempfile.TemporaryDirectory(prefix='geometry-activation-') as temp:
    output = Path(temp)/'bin'
    builder.build('/src/TrinityCore', '/src/TrinityCore/build', output)
    result = subprocess.run([str(output/'check-height'), '/geometry/vmaps', '1220', '33', '23'],
                            capture_output=True, text=True, timeout=120)
    print(result.stdout, flush=True)
    print(result.stderr, flush=True)
    rows = [line for line in result.stdout.splitlines() if line.startswith('{')]
    if result.returncode or not rows:
        raise SystemExit('Native staged collision probe failed')
    report = json.loads(rows[-1])
    if not report.get('load_success') or not report.get('city_collision_samples'):
        raise SystemExit('No staged city collision')
    Path('/out/native-probe.json').write_text(json.dumps(report, indent=2)+'\n')
