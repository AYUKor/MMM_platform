"""CLI for immutable model registration, activation and rollback."""

from __future__ import annotations

import argparse
import json

from mmm_core.model_registry import (
    activate_model,
    history,
    list_registrations,
    load_registration,
    register_model,
    resolve_channel,
    rollback_model,
    verify_registration,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operate the X5 MMM model registry.")
    parser.add_argument(
        "command",
        choices=["register", "verify", "list", "show", "history", "resolve", "activate", "rollback"],
    )
    parser.add_argument("--registry-root")
    parser.add_argument("--run-dir")
    parser.add_argument("--package-id")
    parser.add_argument("--channel", choices=["preprod", "production"])
    parser.add_argument("--expected-current")
    parser.add_argument("--expected-package-id")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    return parser.parse_args()


def required(value: str | None, flag: str) -> str:
    if not value:
        raise ValueError(f"{flag} is required for this registry command")
    return value


def main() -> None:
    args = parse_args()
    common = {"registry_root": args.registry_root}
    if args.command == "register":
        result = register_model(
            required(args.run_dir, "--run-dir"),
            registered_by=required(args.actor, "--actor"),
            reason=required(args.reason, "--reason"),
            **common,
        )
    elif args.command == "verify":
        result = verify_registration(required(args.package_id, "--package-id"), **common)
    elif args.command == "list":
        result = list_registrations(**common)
    elif args.command == "show":
        result = load_registration(required(args.package_id, "--package-id"), **common)
    elif args.command == "history":
        result = history(**common)
    elif args.command == "resolve":
        result = resolve_channel(
            required(args.channel, "--channel"),
            expected_package_id=args.expected_package_id,
            **common,
        )
    elif args.command == "activate":
        result = activate_model(
            required(args.package_id, "--package-id"),
            channel=required(args.channel, "--channel"),
            expected_current=required(args.expected_current, "--expected-current"),
            approved_by=required(args.actor, "--actor"),
            reason=required(args.reason, "--reason"),
            **common,
        )
    else:
        result = rollback_model(
            required(args.package_id, "--package-id"),
            expected_current=required(args.expected_current, "--expected-current"),
            approved_by=required(args.actor, "--actor"),
            reason=required(args.reason, "--reason"),
            **common,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
