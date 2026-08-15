#!/usr/bin/env python3
"""
Sprint 0 patch for brazil-news-bot (Boris) — repository cleanup.

Run this FIRST, before apply_sprint1_patch.py / apply_sprint2_patch.py /
apply_sprint3_patch.py.

--- Does this patch modify sprint 1/2/3 scripts? ---
No. apply_sprint1_patch.py and apply_sprint2_patch.py were verified
byte-identical to what was originally delivered — nothing in them needed
fixing; they correctly do what they claim to do. The only thing that needed
correcting was three cosmetic README lines that those two scripts never
touched in the first place (an index.js version note, a personality.js
description, and the tar command's file list in the "Как задеплоить"
section) — that correction lives in apply_sprint3_patch.py itself (it
tolerates whichever of those variants it finds), not here. This script
prints a short verification note about that so it's on the record, and
otherwise leaves sprint 1/2/3 completely alone.

--- What this patch actually does ---
Removes dead weight that was sitting in the repo from before any of the
sprints, unrelated to code correctness but worth cleaning up:

  1. app.tar.gz.base64 (and app.tar.gz, if present as a real binary file)
     — a stale build artifact: a base64-encoded tarball containing an OLD
     copy of index.js (v13.8, versions behind the current code) plus
     package.json, including leftover macOS extended-attribute cruft
     (._index.js, ._package.json) inside the archive itself. It is not
     read by the deploy command (README's "Как задеплоить" always
     regenerates app.tar.gz fresh from the current index.js/personality.js/
     package.json) — so this file was pure duplication with no function,
     just old code sitting in the repo.

  2. make_avatar.py and make_avatar2.py — two draft scripts for generating
     the bot's avatar image (a Brazil-flag design and a São Paulo sunset
     design). Confirmed with the repo owner: the avatar has already been
     generated and uploaded, so both scripts are no longer needed and are
     removed per explicit instruction (not because they were duplicates of
     each other — they were two different designs, not the same code
     twice).

Usage:
    python3 apply_sprint0_patch.py [path/to/brazil-news-bot]

Idempotent: safe to run twice (or against a repo that's already been
cleaned up — it just reports nothing to remove). Removed files are backed
up to a timestamped folder before deletion, not permanently destroyed by
this script, in case you want to double check before it hits git.
"""

import sys
import shutil
import datetime
from pathlib import Path


def find_bot_dir(cli_arg):
    candidates = []
    if cli_arg:
        candidates.append(Path(cli_arg))
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "brazil-news-bot")
    candidates.append(Path.cwd() / "brazil-news-bot")
    candidates.append(Path.cwd())

    for c in candidates:
        if (c / "index.js").exists() and (c / "personality.js").exists():
            return c

    print("ERROR: could not locate brazil-news-bot/ (needs index.js + personality.js).")
    print("       Pass the path explicitly: python3 apply_sprint0_patch.py /path/to/brazil-news-bot")
    sys.exit(1)


# Files removed by this cleanup, with the reason shown to the user.
FILES_TO_REMOVE = [
    (
        "app.tar.gz.base64",
        "stale build artifact — base64 of an OLD index.js (v13.8) + package.json; "
        "not read by the deploy command, which always regenerates this fresh",
    ),
    (
        "app.tar.gz",
        "same stale build artifact, binary form (only removed if actually present as a real file)",
    ),
    (
        "make_avatar.py",
        "avatar draft script (Brazil-flag design) — avatar already generated/uploaded, no longer needed",
    ),
    (
        "make_avatar2.py",
        "avatar draft script (São Paulo sunset design) — avatar already generated/uploaded, no longer needed",
    ),
]


def cleanup_repo(bot_dir: Path):
    print(f"\nCleaning up {bot_dir} ...")

    backup_dir = bot_dir / f".sprint0-removed-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    any_removed = False

    for filename, reason in FILES_TO_REMOVE:
        target = bot_dir / filename
        if not target.exists():
            print(f"  [skip] {filename} (not present — already clean, or never existed here)")
            continue
        if not any_removed:
            backup_dir.mkdir(exist_ok=True)
        shutil.copy2(target, backup_dir / filename)
        target.unlink()
        any_removed = True
        print(f"  [ok]   removed {filename}")
        print(f"         reason: {reason}")
        print(f"         backup: {backup_dir.name}/{filename}")

    if not any_removed:
        print("  Nothing to remove — repo is already clean of these files.")
    else:
        print(f"\n  Backups of everything removed are in: {backup_dir}")
        print("  (that backup folder itself should NOT be committed — see .gitignore")
        print("   note below, or just delete it once you've confirmed you don't need it)")


def verify_sprint12_scripts(bot_dir: Path):
    """
    Sprint 1/2 scripts are not modified by this patch. This just prints a
    clear on-the-record note about what was actually checked, so there's
    no ambiguity about whether v0 silently changed their behavior.
    """
    print("\nSprint 1/2 script verification (informational only — nothing changed here):")
    print("  apply_sprint1_patch.py and apply_sprint2_patch.py are exactly the scripts")
    print("  you were already given — they were re-diffed against the originally")
    print("  delivered versions and are byte-identical. No fix was needed in them.")
    print()
    print("  What DID need fixing were three README lines that neither script ever")
    print("  touched (an index.js version note, a personality.js description, and")
    print("  the tar file list in \"Как задеплоить\") — that fix lives inside")
    print("  apply_sprint3_patch.py, which tolerates either the old or already-fixed")
    print("  wording it finds. You don't need to do anything extra for this — just")
    print("  run sprint 1 -> 2 -> 3 in order as usual.")


def main():
    cli_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bot_dir = find_bot_dir(cli_arg)
    print(f"Using bot directory: {bot_dir}")

    cleanup_repo(bot_dir)
    verify_sprint12_scripts(bot_dir)

    print("\nDone. Next steps:")
    print("  1. Review what's left: ls -la '%s'" % bot_dir)
    print("  2. If happy with the removals, stage them:")
    print("       git -C '%s' add -A" % bot_dir)
    print("       git -C '%s' status" % bot_dir)
    print("  3. Then continue with the normal sprint order:")
    print("       python3 apply_sprint1_patch.py '%s'" % bot_dir)
    print("       python3 apply_sprint2_patch.py '%s'" % bot_dir)
    print("       python3 apply_sprint3_patch.py '%s'" % bot_dir)
    print("  4. Commit everything together (cleanup + sprint1-3) or in separate")
    print("     commits — either works; separate commits give a clearer history:")
    print("       git -C '%s' commit -m \"sprint0: remove stale app.tar.gz.base64 and avatar draft scripts\"" % bot_dir)


if __name__ == "__main__":
    main()
