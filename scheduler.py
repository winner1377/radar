"""
scheduler.py — Run FeedBot on a schedule (default every 30 minutes)

Usage:
    python scheduler.py            # runs every 30 minutes
    python scheduler.py --interval 60   # runs every 60 minutes
"""

import sys
import time
import logging
import argparse
from apscheduler.schedulers.blocking import BlockingScheduler
from feedbot import init_db, run_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=360,
                        help="How often to run (minutes). Default: 30")
    args = parser.parse_args()

    init_db()
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, "interval", minutes=args.interval, id="feedbot")
    
    print(f"\n🤖 FeedBot Scheduler started — running every {args.interval} minutes")
    print("   (First run: indexing existing articles — nothing will be sent)\n")
    
    # First run: mark all existing matching articles as seen without sending
    run_cycle(dry_run=True)
    print("\n✅ Indexing complete. Now monitoring for new articles...\n")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n⏹ Scheduler stopped.")


if __name__ == "__main__":
    main()
