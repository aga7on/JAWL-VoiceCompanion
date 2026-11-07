"""Clean slate script: safely reset agent memory, facts, traits, and sensory records.

Clears:
- agent.db (conversations, turns, messages, traits, facts, entities)
- agent_graph.db (graph entities, relations)
- terminal history.json
- action_journal.jsonl
- sensory history (current-perception.json, weekly-history.json)
- voicemem vectors and SQLite store
- episodic visual memory webp images and lancedb tables
- narrative consolidator state
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path


def clean_sqlite_db(db_path: Path):
    if not db_path.exists():
        return
    print(f"Cleaning SQLite DB: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # List tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row[0] for row in cursor.fetchall()]
    for t in tables:
        cursor.execute(f"DELETE FROM {t};")
    conn.commit()
    conn.execute("VACUUM;")
    conn.close()
    print(f"  Truncated {len(tables)} tables in {db_path.name}")


def main():
    root = Path(__file__).resolve().parent.parent
    daily_data = root / "runtime" / "instances" / "daily" / "data"

    print("=" * 60)
    print("CLEAN SLATE: ZEROING AGENT MEMORY, TRAITS, AND FACTS")
    print("=" * 60)

    # 1. Truncate SQLite databases
    db_candidates = [
        daily_data / "agent.db",
        daily_data / "sql" / "db" / "agent.db",
        daily_data / "sensory" / "voicemem" / "voicemem.sqlite",
    ]
    for db in db_candidates:
        clean_sqlite_db(db)

    # Clean Kuzu graph DB
    graph_dir = daily_data / "graph"
    if graph_dir.exists():
        print(f"Resetting Kuzu graph DB in: {graph_dir}")
        for item in graph_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    # Remove wal / shm files
    for db in db_candidates:
        for ext in ["-wal", "-shm"]:
            wal = db.with_name(db.name + ext)
            if wal.exists():
                wal.unlink()

    # 2. Reset JSON/JSONL history and journal files
    files_to_reset = [
        daily_data / "agent" / "action_journal.jsonl",
        daily_data / "agent" / "action_journal.jsonl.1",
        daily_data / "agent" / "goals.json",
        daily_data / "interfaces" / "host" / "terminal" / "history.json",
        daily_data / "interfaces" / "host" / "terminal" / "history.json.bak",
        daily_data / "interfaces" / "host" / "terminal" / "gateway_events.json",
        daily_data / "sensory" / "current-perception.json",
        daily_data / "sensory" / "weekly-history.json",
        daily_data / "sensory" / "voicemem" / "voicemem.json",
    ]
    for f in files_to_reset:
        if f.exists():
            print(f"Resetting file: {f.relative_to(root)}")
            if f.suffix == ".jsonl":
                f.write_text("", encoding="utf-8")
            elif f.name == "history.json":
                f.write_text("[]", encoding="utf-8")
            elif f.name == "goals.json":
                f.write_text("{}", encoding="utf-8")
            else:
                f.write_text("{}", encoding="utf-8")

    # 3. Clean Vector DB storage
    vector_dirs = [
        daily_data / "vector" / "db" / "collection" / "knowledge",
        daily_data / "vector" / "db" / "collection" / "thoughts",
        daily_data / "vector" / "db" / "collection" / "code_ast",
        daily_data / "sensory" / "voicemem" / "vectors" / "collection" / "voicemem",
        daily_data / "sensory" / "voicemem" / "multi_modal",
    ]
    for vdir in vector_dirs:
        sqlite_file = vdir / "storage.sqlite"
        if sqlite_file.exists():
            clean_sqlite_db(sqlite_file)

    # 4. Clean LanceDB visual episodic memory and keyframe images
    visual_cache_dir = root / "runtime" / "instances" / "daily" / "visual_memory"
    if visual_cache_dir.exists():
        print(f"Removing visual episodic memory cache: {visual_cache_dir.relative_to(root)}")
        shutil.rmtree(visual_cache_dir)
        visual_cache_dir.mkdir(parents=True, exist_ok=True)

    # 5. Clean narrative consolidator storage
    narrative_file = root / "runtime" / "instances" / "daily" / "narrative_state.json"
    if narrative_file.exists():
        print(f"Removing narrative consolidator state: {narrative_file.relative_to(root)}")
        narrative_file.unlink()

    print("\n>>> CLEAN SLATE COMPLETED SUCCESSFULLY. Agent has 0 memory, 0 traits, 0 facts.")


if __name__ == "__main__":
    main()
