"""Headless import + AnkiWeb sync of the shareable decks — no GUI needed.

  .venv/bin/python sync_decks.py [--profile "User 1"] [--dir deck/ankiweb_upload]

Imports every *.apkg in the dir into the profile's collection (existing notes
updated in place via their stable guids), then runs a full collection + media
sync using the auth token the desktop app stored in the profile. Desktop Anki
must be CLOSED (the collection is locked while it runs). A timestamped backup
of collection.anki2 is written next to it first.

Known limitation: Anki never overwrites an existing media file that has the
same name — a repaired clip with an unchanged name is only picked up by a
collection that doesn't already hold the old file (fresh import, or delete
the deck + Tools > Check Media > delete unused first).
"""
from __future__ import annotations
import argparse
import pickle
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from anki.collection import Collection
from anki.errors import DBError
from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest
from anki.sync import SyncAuth

ANKI2 = Path.home() / ".local/share/Anki2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="User 1")
    ap.add_argument("--dir", default="deck/ankiweb_upload")
    ap.add_argument("--no-sync", action="store_true", help="import only")
    a = ap.parse_args()

    prefs = sqlite3.connect(ANKI2 / "prefs21.db")
    data = pickle.loads(prefs.execute(
        "select data from profiles where name=?", (a.profile,)).fetchone()[0])
    prefs.close()

    col_path = ANKI2 / a.profile / "collection.anki2"
    backup = col_path.with_name(
        f"collection.backup-{datetime.now():%Y%m%d-%H%M%S}.anki2")
    shutil.copy2(col_path, backup)
    print(f"backup -> {backup.name}")

    try:
        col = Collection(str(col_path))
    except DBError:
        print("collection is locked — close desktop Anki first")
        return 1

    try:
        for apkg in sorted(Path(a.dir).glob("*.apkg")):
            req = ImportAnkiPackageRequest(
                package_path=str(apkg),
                options=ImportAnkiPackageOptions(
                    merge_notetypes=True,
                    update_notes=1,       # ALWAYS: existing notes update via stable guids
                    update_notetypes=0))  # IF_NEWER
            out = col.import_anki_package(req)
            log = out.log
            print(f"{apkg.name}: new {len(log.new)}, updated {len(log.updated)}, "
                  f"duplicate {len(log.duplicate)}, conflicting {len(log.conflicting)}")

        if a.no_sync:
            return 0
        auth = SyncAuth(hkey=data["syncKey"],
                        endpoint=data.get("currentSyncUrl") or None)
        out = col.sync_collection(auth, sync_media=True)
        print("collection sync:", out.required or "done")
        while True:
            s = col.media_sync_status()
            if not s.active:
                break
            p = s.progress
            print(f"  media: +{p.added} / -{p.removed} / checked {p.checked}", flush=True)
            time.sleep(3)
        print("media sync: done")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
