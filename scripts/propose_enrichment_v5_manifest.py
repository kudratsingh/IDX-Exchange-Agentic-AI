"""Write a proposed v5 effective-store manifest for the owner to freeze (WO-035).

Writes one new file at `--output`, a path the owner chooses; never over an existing
file, the v4 manifest or a pinned input. Prints the written file's name and hash only.
"""

# Before writing, it checks the v4 freeze manifest (unchanged), ruling 8's overlay
# against its own manifest, and the frozen scope's rules version. The owner freezes the
# proposal by copying it to `data/enrichment/effective-store-v5-manifest.json`; nothing
# here does that.

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.build_enrichment_effective_store import (  # noqa: E402
    ROOT as DATA_ROOT,
)
from scripts.build_enrichment_effective_store import (  # noqa: E402
    load_jsonl,
    paths,
    verify_manifest,
)

from idx_agent.enrichment import store_v5  # noqa: E402
from idx_agent.enrichment.policy_rules import POLICY_RULES_VERSION  # noqa: E402
from idx_agent.enrichment.source_check import (  # noqa: E402
    EXPECTED_RESULTS_DIGEST,
    EXPECTED_WATERMARK,
    trusted_source_rows,
)


def propose(output: Path, root: Path = DATA_ROOT, **trusted) -> dict:
    """Verify the inputs and write the proposal; return its name, hash and size.

    `trusted` overrides the frozen digest and watermark (tests only).
    """
    results_digest = trusted.get("results_digest", EXPECTED_RESULTS_DIGEST)
    watermark = trusted.get("source_watermark", EXPECTED_WATERMARK)
    where = paths(root)
    artifacts = where["v5_artifacts"]
    pinned = {p.resolve() for p in artifacts.values()} | {
        where["manifest"].resolve(),
        where["manifest_v5"].resolve(),
    }
    if output.resolve() in pinned or output.exists():
        raise ValueError("refusing to write over an existing or pinned file")
    v4_manifest = json.loads(where["manifest"].read_text())
    verify_manifest(v4_manifest, where["artifacts"])
    scope = json.loads(artifacts["dataset_scope"].read_text())
    if scope.get("rules_version") != POLICY_RULES_VERSION:
        raise ValueError("frozen scope's rules version differs from the rules")
    store_v5.validate_cleanup(
        load_jsonl(artifacts["cleanup_overlay"]),
        json.loads(artifacts["cleanup_manifest"].read_text()),
        overlay_name=artifacts["cleanup_overlay"].name,
        overlay_sha256=store_v5.sha256_file(artifacts["cleanup_overlay"]),
        dataset_overlay_sha256=v4_manifest["dataset_overlay"],
    )
    rows = trusted_source_rows(results_digest)
    if rows is None:
        raise ValueError("the results digest is not a trusted source")
    manifest = store_v5.propose_manifest(
        artifacts,
        rules_version=POLICY_RULES_VERSION,
        results_digest=results_digest,
        source_rows=rows,
        source_watermark=watermark,
    )
    raw = store_v5.canonical_bytes(manifest)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(raw)
    # Round trip: what was written verifies exactly as the builder will verify it.
    store_v5.verify_v5_manifest(
        output.read_bytes(),
        artifacts,
        results_digest=results_digest,
        source_rows=rows,
        source_watermark=watermark,
        rules_version=POLICY_RULES_VERSION,
    )
    return {
        "written": output.name,
        "sha256": store_v5.sha256_file(output),
        "artifacts": len(manifest["artifacts"]),
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(propose(args.output, args.data_root)))


if __name__ == "__main__":
    main()
