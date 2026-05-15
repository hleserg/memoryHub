"""
atman-maintenance — run background maintenance jobs.

Usage:
    python -m atman.cli_maintenance run --once
    python -m atman.cli_maintenance run --loop --interval 3600
    python -m atman.cli_maintenance run --job salience_decay --agent-id <uuid>
    python -m atman.cli_maintenance list [--status pending]
    python -m atman.cli_maintenance enqueue <job_name> --agent-id <uuid>
"""

import argparse
import logging
import sys
import time
from uuid import UUID

from atman.core.models.maintenance import JobName, JobStatus
from atman.core.services.maintenance_worker import MaintenanceWorker
from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.core.services.salience_decay_service import InMemorySalienceDecayService
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOG = logging.getLogger(__name__)


def cmd_run(args: argparse.Namespace) -> int:
    queue = InMemoryMaintenanceQueue()
    state_store = InMemoryStateStore()
    decay = InMemorySalienceDecayService(state_store)
    worker = MaintenanceWorker(queue=queue, salience_decay=decay)

    _LOG.warning(
        "Using in-memory queue — no jobs persisted. "
        "Use PostgresMaintenanceQueue in production."
    )

    job_name: JobName | None = None
    if args.job is not None:
        try:
            job_name = JobName(args.job)
        except ValueError:
            print(
                f"Unknown job type: {args.job!r}. "
                f"Valid values: {[j.value for j in JobName]}"
            )
            return 1

    if args.once:
        # Honour --job filter: claim only that job type
        if job_name is not None:
            jobs = queue.claim_batch(job_name=job_name, batch_size=args.batch_size)
            for job in jobs:
                worker._dispatch(job)  # noqa: SLF001
            count = len(jobs)
        else:
            count = worker.run_once(batch_size=args.batch_size)
        print(f"Processed {count} jobs.")
        return 0

    if args.loop:
        _LOG.info(
            "Starting maintenance loop (interval=%ds, batch_size=%d, job=%s)",
            args.interval,
            args.batch_size,
            job_name or "all",
        )
        try:
            while True:
                if job_name is not None:
                    jobs = queue.claim_batch(
                        job_name=job_name, batch_size=args.batch_size
                    )
                    for job in jobs:
                        worker._dispatch(job)  # noqa: SLF001
                    count = len(jobs)
                else:
                    count = worker.run_once(batch_size=args.batch_size)
                _LOG.info(
                    "Processed %d jobs. Sleeping %ds.", count, args.interval
                )
                time.sleep(args.interval)
        except KeyboardInterrupt:
            _LOG.info("Interrupted — exiting loop.")
        return 0

    # Neither --once nor --loop supplied
    print("Specify --once or --loop.", file=sys.stderr)
    return 1


def cmd_list(args: argparse.Namespace) -> int:
    queue = InMemoryMaintenanceQueue()
    _LOG.warning(
        "Using in-memory queue — this instance is empty. "
        "Use PostgresMaintenanceQueue in production to see persisted jobs."
    )

    status: JobStatus | None = None
    if args.status is not None:
        try:
            status = JobStatus(args.status)
        except ValueError:
            print(
                f"Unknown status: {args.status!r}. "
                f"Valid values: {[s.value for s in JobStatus]}"
            )
            return 1

    jobs = queue.list_jobs(status=status)
    if not jobs:
        print("No jobs found.")
        return 0

    # Header
    print(f"{'ID':<36}  {'JOB':<22}  {'STATUS':<10}  {'AGENT':<36}  SCHEDULED")
    print("-" * 120)
    for job in jobs:
        agent_str = str(job.agent_id) if job.agent_id else "(none)"
        print(
            f"{job.id!s:<36}  {job.job_name:<22}  {job.status:<10}  "
            f"{agent_str:<36}  {job.scheduled_at.isoformat()}"
        )
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    queue = InMemoryMaintenanceQueue()
    _LOG.warning(
        "Using in-memory queue — enqueued jobs will not persist. "
        "Use PostgresMaintenanceQueue in production."
    )

    try:
        job_name = JobName(args.job_name)
    except ValueError:
        print(
            f"Unknown job: {args.job_name!r}. "
            f"Valid values: {[j.value for j in JobName]}"
        )
        return 1

    agent_id: UUID | None = None
    if args.agent_id is not None:
        try:
            agent_id = UUID(args.agent_id)
        except ValueError:
            print(f"Invalid UUID for --agent-id: {args.agent_id!r}")
            return 1

    job = queue.enqueue(job_name, agent_id=agent_id)
    print(f"Enqueued job {job.id} ({job.job_name}) — status: {job.status}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atman-maintenance",
        description="Atman maintenance CLI — run, list, or enqueue background jobs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  atman-maintenance run --once\n"
            "  atman-maintenance run --loop --interval 1800 --batch-size 50\n"
            "  atman-maintenance run --job salience_decay --once\n"
            "  atman-maintenance list --status pending\n"
            "  atman-maintenance enqueue salience_decay "
            "--agent-id 00000000-0000-0000-0000-000000000001\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- run ----
    run_p = sub.add_parser("run", help="Execute maintenance jobs from the queue.")
    mode = run_p.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Claim and process one batch, then exit.",
    )
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Run in an infinite loop, sleeping --interval seconds between batches.",
    )
    run_p.add_argument(
        "--interval",
        type=int,
        default=3600,
        metavar="SECONDS",
        help="Loop sleep interval in seconds (default: 3600). Used with --loop.",
    )
    run_p.add_argument(
        "--batch-size",
        type=int,
        default=20,
        dest="batch_size",
        metavar="N",
        help="Maximum number of jobs to claim per batch (default: 20).",
    )
    run_p.add_argument(
        "--job",
        default=None,
        metavar="JOB_NAME",
        help=(
            "Filter to a specific job type "
            f"(choices: {', '.join(j.value for j in JobName)})."
        ),
    )
    run_p.add_argument(
        "--agent-id",
        default=None,
        dest="agent_id",
        metavar="UUID",
        help="Limit job processing to this agent UUID (informational only for now).",
    )

    # ---- list ----
    list_p = sub.add_parser("list", help="List maintenance jobs in the queue.")
    list_p.add_argument(
        "--status",
        default=None,
        metavar="STATUS",
        help=(
            "Filter by status "
            f"(choices: {', '.join(s.value for s in JobStatus)}). "
            "Omit to show all."
        ),
    )

    # ---- enqueue ----
    enq_p = sub.add_parser("enqueue", help="Manually enqueue a maintenance job.")
    enq_p.add_argument(
        "job_name",
        metavar="JOB_NAME",
        help=(
            "Job type to enqueue "
            f"(choices: {', '.join(j.value for j in JobName)})."
        ),
    )
    enq_p.add_argument(
        "--agent-id",
        default=None,
        dest="agent_id",
        metavar="UUID",
        help="Associate the job with this agent UUID.",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    dispatch = {
        "run": cmd_run,
        "list": cmd_list,
        "enqueue": cmd_enqueue,
    }
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
