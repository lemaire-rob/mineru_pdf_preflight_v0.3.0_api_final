from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--worker", action="store_true", help="Run PDF processing worker")
    parser.add_argument("--api-worker", action="store_true", help="Run MinerU API worker")
    parser.add_argument("--task", help="Path to task JSON")
    parser.add_argument("--result", help="Path to result JSON")
    args, _ = parser.parse_known_args()

    if args.worker:
        from src.worker_entry import main as worker_main
        return worker_main(args.task, args.result)

    if args.api_worker:
        from src.api_worker_entry import main as api_worker_main
        return api_worker_main(args.task, args.result)

    from src.gui import run_gui
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
