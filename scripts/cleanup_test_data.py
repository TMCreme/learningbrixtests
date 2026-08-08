#!/usr/bin/env python
"""Delete the TEST-prefixed schools and feature packs left behind by test runs.

Why this has to exist, and why it deletes over SQL rather than the API:

  1. `DELETE /school_profile/{id}` is broken. Every FK pointing at
     `school_profiles` is declared ON DELETE CASCADE in Postgres, but the ORM
     relationships lack `passive_deletes=True`, so SQLAlchemy loads the children
     and tries to NULL their `school_id` before deleting the parent — which the
     NOT NULL constraint rejects:
         null value in column "school_id" of relation "academic_year"
     Teardown therefore never removes anything.

  2. Both `/school_profile/` and `/feature-packs/` cap their responses at 100
     rows. Once the leftovers reach that cap, a newly created feature pack falls
     outside the page the assign-pack dialog renders, so provisioning fails at
     "assign pack to school" with a selector timeout that looks nothing like the
     real cause. That is what it did.

Deleting straight through the database sidesteps the ORM bug entirely and lets
the CASCADE rules do the work they were declared for.

    python scripts/cleanup_test_data.py            # dry run — counts only
    python scripts/cleanup_test_data.py --yes      # actually delete
    python scripts/cleanup_test_data.py --keep 10  # keep the 10 newest schools
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402


# Only ever touches rows whose name starts with this. Every entity the suite
# creates carries it (config/feature_scenarios.yaml).
PREFIX = "TEST"

# The row count at which the list endpoints start hiding new records.
LIST_CAP = 100


def psql(db_container: str, sql: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", db_container, "psql", "-U", "postgres",
         "-d", "schoolappdb", "-tAc", sql],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise SystemExit(f"psql failed: {proc.stderr.strip()[:500]}")
    return proc.stdout.strip()


def counts(db_container: str) -> tuple[int, int]:
    schools = psql(db_container,
                   f"select count(*) from school_profiles where name like '{PREFIX}%';")
    packs = psql(db_container,
                 f"select count(*) from feature_packs where name like '{PREFIX}%';")
    return int(schools or 0), int(packs or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually delete")
    parser.add_argument("--keep", type=int, default=0,
                        help="keep the N most recently created test schools")
    parser.add_argument("--db-container", default="salschdb")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    schools, packs = counts(args.db_container)
    if not args.quiet:
        print(f"TEST schools: {schools}   TEST feature packs: {packs}"
              f"   (list endpoints cap at {LIST_CAP})")

    if not args.yes:
        doomed = max(0, schools - args.keep)
        print(f"dry run — would delete {doomed} school(s) and {packs} pack(s). "
              f"Re-run with --yes.")
        return 0

    keep_clause = ""
    if args.keep > 0:
        keep_clause = (
            f" and id not in (select id from school_profiles "
            f"where name like '{PREFIX}%' order by date_created desc "
            f"limit {args.keep})"
        )

    # Children cascade at the database level, which is exactly what the ORM
    # fails to let happen.
    psql(args.db_container,
         f"delete from school_profiles where name like '{PREFIX}%'{keep_clause};")
    psql(args.db_container,
         f"delete from feature_packs where name like '{PREFIX}%';")

    # Users the suite created are not reachable from school_profiles, so they
    # are matched on the address pattern data_factories.unique_email builds.
    settings = get_settings()
    domain = settings.test_email_domain
    psql(args.db_container,
         f"delete from users where email like 'playwright+%@{domain}' "
         f"and email <> '{settings.superadmin_email}';")

    after_schools, after_packs = counts(args.db_container)
    print(f"deleted — schools {schools} → {after_schools}, "
          f"packs {packs} → {after_packs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
