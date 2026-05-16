# batch_crawler.py

import json
import time
import requests
import traceback

from pathlib import Path

# ─────────────────────────────────────
# CONFIG
# ─────────────────────────────────────

BASE = "https://ll.thespacedevs.com/2.3.0/launches/"

LIMIT = 100

# 1 request per minute
REQUEST_SLEEP = 60

# max requests per workflow run
MAX_REQUESTS = 15

# ─────────────────────────────────────
# PATHS
# ─────────────────────────────────────

ROOT = Path("historical_fetch")

KEYWORDS_DIR = ROOT / "keywords"
RAW_DIR = ROOT / "raw_pages"
MERGED_DIR = ROOT / "merged"
STATE_DIR = ROOT / "state"

KEYWORDS_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)
MERGED_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

GLOBAL_STATE_FILE = STATE_DIR / "global_state.json"

# ─────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────

if GLOBAL_STATE_FILE.exists():

    with open(GLOBAL_STATE_FILE, "r", encoding="utf-8") as f:
        global_state = json.load(f)

else:

    global_state = {
        "current_file_index": 0
    }

# ─────────────────────────────────────
# GET KEYWORD FILES
# ─────────────────────────────────────

keyword_files = sorted(
    KEYWORDS_DIR.glob("*.txt")
)

if not keyword_files:

    print("NO KEYWORD FILES FOUND", flush=True)
    raise SystemExit

# ─────────────────────────────────────
# CURRENT FILE
# ─────────────────────────────────────

current_file_index = global_state["current_file_index"]

if current_file_index >= len(keyword_files):

    print("ALL KEYWORD FILES COMPLETED", flush=True)
    raise SystemExit

keyword_file = keyword_files[current_file_index]

batch_name = keyword_file.stem

print("=" * 60, flush=True)
print(f"BATCH: {batch_name}", flush=True)
print("=" * 60, flush=True)

# ─────────────────────────────────────
# LOAD KEYWORDS
# ─────────────────────────────────────

with open(keyword_file, "r", encoding="utf-8") as f:

    keywords = [
        line.strip()
        for line in f.readlines()
        if line.strip()
    ]

print(f"KEYWORDS: {len(keywords)}", flush=True)

# ─────────────────────────────────────
# STATE FILE
# ─────────────────────────────────────

STATE_FILE = STATE_DIR / f"{batch_name}.json"

if STATE_FILE.exists():

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

else:

    state = {
        "keyword_index": 0,
        "next_url": None,
        "page_number": 1,
        "completed": False,
    }

# ─────────────────────────────────────
# MERGED FILE
# ─────────────────────────────────────

MERGED_FILE = MERGED_DIR / (
    f"{batch_name}_launches.json"
)

all_launches = []
seen_ids = set()

if MERGED_FILE.exists():

    with open(MERGED_FILE, "r", encoding="utf-8") as f:
        existing = json.load(f)

    for launch in existing:

        lid = launch.get("id")

        if lid:
            seen_ids.add(lid)

    all_launches.extend(existing)

# ─────────────────────────────────────
# SAVE HELPERS
# ─────────────────────────────────────

def save_state():

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
        )

def save_global_state():

    with open(
        GLOBAL_STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            global_state,
            f,
            ensure_ascii=False,
            indent=2,
        )

def save_merged():

    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(
            all_launches,
            f,
            ensure_ascii=False,
            indent=2,
        )

# ─────────────────────────────────────
# REQUEST LOOP
# ─────────────────────────────────────

request_count = 0

try:

    for idx in range(
        state["keyword_index"],
        len(keywords),
    ):

        keyword = keywords[idx]

        print("\n" + "-" * 60, flush=True)
        print(f"KEYWORD: {keyword}", flush=True)

        url = state["next_url"] or BASE

        params = {
            "search": keyword,
            "ordering": "-net",
            "mode": "detailed",
            "limit": LIMIT,
        }

        page_number = state["page_number"]

        while url:

            # ─────────────────────────────────────
            # REQUEST LIMIT
            # ─────────────────────────────────────

            if request_count >= MAX_REQUESTS:

                print(
                    "MAX REQUESTS REACHED",
                    flush=True,
                )

                save_state()
                save_merged()

                raise SystemExit

            print(
                f"Request #{request_count + 1}",
                flush=True,
            )

            print(
                f"Page: {page_number}",
                flush=True,
            )

            try:

                response = requests.get(
                    url,
                    params=params if page_number == 1 else None,
                    timeout=60,
                )

                # ─────────────────────────────────────
                # 429 HANDLING
                # ─────────────────────────────────────

                if response.status_code == 429:

                    print(
                        "429 RATE LIMIT",
                        flush=True,
                    )

                    save_state()
                    save_merged()

                    raise SystemExit

                response.raise_for_status()

                data = response.json()

            except Exception as e:

                print(
                    "REQUEST FAILED",
                    flush=True,
                )

                print(str(e), flush=True)

                save_state()
                save_merged()

                raise SystemExit

            # ─────────────────────────────────────
            # SAVE RAW PAGE
            # ─────────────────────────────────────

            safe_keyword = (
                keyword
                .replace(" ", "_")
                .replace("/", "_")
            )

            raw_file = RAW_DIR / (
                f"{batch_name}_"
                f"{safe_keyword}_"
                f"page_{page_number}.json"
            )

            with open(raw_file, "w", encoding="utf-8") as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            # ─────────────────────────────────────
            # PROCESS RESULTS
            # ─────────────────────────────────────

            results = data.get("results", [])

            added = 0

            for launch in results:

                lid = launch.get("id")

                if not lid:
                    continue

                if lid in seen_ids:
                    continue

                seen_ids.add(lid)

                all_launches.append(launch)

                added += 1

            print(
                f"Added: {added}",
                flush=True,
            )

            print(
                f"Total launches: {len(all_launches)}",
                flush=True,
            )

            # ─────────────────────────────────────
            # SAVE
            # ─────────────────────────────────────

            save_merged()

            # ─────────────────────────────────────
            # NEXT PAGE
            # ─────────────────────────────────────

            url = data.get("next")

            page_number += 1

            request_count += 1

            state["keyword_index"] = idx
            state["next_url"] = url
            state["page_number"] = page_number

            save_state()

            # ─────────────────────────────────────
            # REQUEST GAP
            # ─────────────────────────────────────

            if url:

                print(
                    f"Sleeping {REQUEST_SLEEP}s",
                    flush=True,
                )

                time.sleep(REQUEST_SLEEP)

        # ─────────────────────────────────────
        # KEYWORD COMPLETE
        # ─────────────────────────────────────

        state["keyword_index"] = idx + 1
        state["next_url"] = None
        state["page_number"] = 1

        save_state()

    # ─────────────────────────────────────
    # FILE COMPLETE
    # ─────────────────────────────────────

    print(
        f"BATCH COMPLETE: {batch_name}",
        flush=True,
    )

    state["completed"] = True

    save_state()

    # move to next keyword file
    global_state["current_file_index"] += 1

    save_global_state()

except Exception as e:

    print("FATAL ERROR", flush=True)

    traceback.print_exc()

    save_state()
    save_merged()

    raise
