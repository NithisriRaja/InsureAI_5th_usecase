"""Write synthetic products, customers, policies and payments to the CSV data folder.

Stop the API first: it owns the data folder while running.

Usage:
    python -m backend.scripts.seed_data               # small: handcrafted edge cases only
    python -m backend.scripts.seed_data --size full   # + Faker data up to ~80 policies
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backend.db.models import MODELS, Product
from backend.db.session import get_db
from backend.seed import SIZES, seed
from backend.utils.clock import today


async def run(size: str) -> int:
    db = get_db()
    await db.create_all()
    async with db.session() as s:
        if s.all(Product):
            msg = "Data already seeded. Run python -m backend.scripts.reset_db first."
            print(msg, file=sys.stderr)
            await db.dispose()
            return 1
        counts = await seed(s, size)
    await db.save([m.__table__ for m in MODELS if m.__persist__])  # include empty tables
    await db.dispose()
    summary = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"Seeded {db.location} ({size}, as_of={today()}): {summary}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=sorted(SIZES), default="small")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.size)))


if __name__ == "__main__":
    main()
