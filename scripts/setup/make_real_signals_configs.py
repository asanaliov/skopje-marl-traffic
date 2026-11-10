"""Create SUMO configs for the real-signals network from the original ones.

The real-signals variant (SKOPJE_NETWORK=real_signals) uses the same roads and
demand files as the original network but a different net file, so its configs
are copies of the original configs with only the ``net-file`` reference
changed. Re-run after adding new demand scenarios (for example ``peak``)::

    python scripts/setup/make_real_signals_configs.py
"""

from __future__ import annotations

import re
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "sumo" / "skopje" / "config"
ORIGINAL_NET = "skopje_initial.net.xml.gz"
VARIANT_NET = "skopje_real_signals.net.xml.gz"


def convert(source: Path, target: Path) -> None:
    text = source.read_text(encoding="utf-8")
    if ORIGINAL_NET not in text:
        raise ValueError(f"{source} does not reference {ORIGINAL_NET}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(ORIGINAL_NET, VARIANT_NET), encoding="utf-8")


def main() -> int:
    count = 0
    convert(
        CONFIG_DIR / "skopje_initial.sumocfg",
        CONFIG_DIR / "skopje_initial_real_signals.sumocfg",
    )
    count += 1
    for source in sorted((CONFIG_DIR / "scenarios").glob("*.sumocfg")):
        convert(source, CONFIG_DIR / "scenarios_real_signals" / source.name)
        count += 1
    print(f"Wrote {count} real-signals configs under {CONFIG_DIR}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
