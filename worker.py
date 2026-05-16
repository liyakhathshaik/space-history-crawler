import json
import time
import traceback
import subprocess
import requests

from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────
# CONFIG
# ─────────────────────────────────────

BASE = "https://ll.thespacedevs.com/2.3.0/launches/"

SEARCH_TERMS = [
    "China",
    "Long March",
    "Apollo",
    "Falcon 9",
]

LIMIT = 100

REQUESTS_PER_CYCLE = 15

# 1 request every minute
REQUEST_SPACING = 60

# API hard rate limit recovery
RATE_LIMIT_SLEEP = 3600

# Wait between cycles
CYCLE_SLEEP = 3600

# ─────────────────────────────────────
# STORAGE
# ─────────────────────────────────────

ROOT = Path("historical_fetch")

RAW_DIR = ROOT / "raw_pages"
MERGED_DIR = ROOT / "merged"
STATE_DIR = ROOT / "state"

RAW_DIR.mkdir(parents=True, exist_ok=True)
MERGED_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / "progress.json"
MERGED_FILE = MERGED_DIR / "all_launches.json"

# ─────────────────────────────────────
# STATE
# ─────────────────────────────────────

if STATE_FILE.exists():

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

else:

    state = {
        "keyword_index": 0,
        "next_url": None,
        "page_number": 1,
        "completed_keywords": [],
        "total_requests": 0,
    }

# ─────────────────────────────────────
# LOAD EXISTING
# ─────────────────────────────────────

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
        json.dump(state, f, ensure_ascii=False, indent=2)

def save_merged():

    with open(MERGED_FILE, "w", encoding="utf-8") as f:
        json.dump(all_launches, f, ensure_ascii=False, indent=2)

def git_push():

    try:

        subprocess.run(["git", "add", "."], check=True)

        subprocess.run(
            ["git", "commit", "-m", "crawler progress"],
            check=False,
        )

        subprocess.run(["git", "push"], check=False)

        print("Git push complete", flush=True)

    except Exception as e:

        print("Git push failed:", e, flush=True)

# ─────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────

while True:

    try:

        print("=" * 60, flush=True)
        print("NEW FETCH CYCLE", flush=True)
        print("=" * 60, flush=True)

        request_count = 0

        for idx in range(
            state["keyword_index"],
            len(SEARCH_TERMS),
        ):

            keyword = SEARCH_TERMS[idx]

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

                if request_count >= REQUESTS_PER_CYCLE:

                    print(
                        "Reached request cycle limit",
                        flush=True,
                    )

                    save_state()
                    save_merged()
                    git_push()

                    break

                print(
                    f"Request #{request_count + 1}",
                    flush=True,
                )

                try:

                    response = requests.get(
                        url,
                        params=params if page_number == 1 else None,
                        timeout=60,
                    )

                    if response.status_code == 429:

                        print(
                            "429 detected",
                            flush=True,
                        )

                        save_state()
                        save_merged()
                        git_push()

                        time.sleep(RATE_LIMIT_SLEEP)

                        continue

                    response.raise_for_status()

                    data = response.json()

                except Exception as e:

                    print(
                        "REQUEST FAILED:",
                        e,
                        flush=True,
                    )

                    save_state()
                    save_merged()
                    git_push()

                    time.sleep(300)

                    continue

                # SAVE RAW PAGE
                safe_keyword = (
                    keyword
                    .replace(" ", "_")
                    .replace("/", "_")
                )

                raw_file = RAW_DIR / (
                    f"{safe_keyword}_page_{page_number}.json"
                )

                with open(raw_file, "w", encoding="utf-8") as f:
                    json.dump(
                        data,
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )

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

                # SAVE EVERYTHING IMMEDIATELY
                save_merged()

                # NEXT PAGE
                url = data.get("next")

                request_count += 1

                state["total_requests"] += 1

                page_number += 1

                state["keyword_index"] = idx
                state["next_url"] = url
                state["page_number"] = page_number

                save_state()

                print(
                    f"Sleeping {REQUEST_SPACING}s",
                    flush=True,
                )

                time.sleep(REQUEST_SPACING)

            # keyword complete
            if not url:

                state["completed_keywords"].append(keyword)

                state["keyword_index"] = idx + 1
                state["next_url"] = None
                state["page_number"] = 1

                save_state()

        # FULL SAVE AFTER CYCLE
        save_state()
        save_merged()
        git_push()

        print(
            f"Sleeping full cycle {CYCLE_SLEEP}s",
            flush=True,
        )

        time.sleep(CYCLE_SLEEP)

    except Exception as e:

        print(
            "FATAL ERROR",
            flush=True,
        )

        traceback.print_exc()

        save_state()
        save_merged()
        git_push()

        time.sleep(300)
