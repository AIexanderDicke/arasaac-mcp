#!/usr/bin/env python
"""Download all ARASAAC pictograms for a language.

Metadata: https://api.arasaac.org/v1/pictograms/all/<lang>
Icons:    https://static.arasaac.org/pictograms/<id>/<id>_<size>.png
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API = "https://api.arasaac.org/v1"
STATIC = "https://static.arasaac.org/pictograms"


def slug(text: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE)
    return text.strip("_")[:60] or "pictogram"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def filename(pic: dict) -> str:
    keyword = next((k.get("keyword") for k in pic.get("keywords", []) if k.get("keyword")), "")
    suffix = f"_{slug(keyword)}" if keyword else ""
    return f"{pic['_id']}{suffix}.png"


def download(pic: dict, out: Path, size: int) -> str:
    dest = out / filename(pic)
    if dest.exists() and dest.stat().st_size > 0:
        return "skipped"
    for s in (size, 300, 2500):
        try:
            data = fetch(f"{STATIC}/{pic['_id']}/{pic['_id']}_{s}.png")
            dest.write_bytes(data)
            return "ok"
        except urllib.error.HTTPError:
            continue
    return "failed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", default="de", help="language code (default: de)")
    ap.add_argument("--size", type=int, default=500, help="icon width in px (default: 500)")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "icons")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Fetching metadata for '{args.lang}' ...", flush=True)
    pics = json.loads(fetch(f"{API}/pictograms/all/{args.lang}"))
    (args.out / f"metadata_{args.lang}.json").write_bytes(
        json.dumps(pics, ensure_ascii=False, indent=2).encode()
    )
    print(f"{len(pics)} pictograms -> {args.out}")

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download, p, args.out, args.size): p for p in pics}
        for i, fut in enumerate(as_completed(futures), 1):
            counts[fut.result()] += 1
            if i % 500 == 0 or i == len(pics):
                print(f"  {i}/{len(pics)}  ({counts})", flush=True)

    print(f"Done: {counts}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
