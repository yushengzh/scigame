"""Command-line entry point for the trusted private evaluation service.

Credentials are read from environment variables so they do not appear in the
process list.  The private pack factory is imported only by the ``serve``
process; Player workers use :mod:`role_benchmark.private_runner` instead.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from .private_eval import PrivateEvaluationService, load_private_case_pack
from .private_http import export_private_results, make_private_evaluation_http_server
from .wire import canonical_json_dumps


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) < 32:
        raise ValueError(
            "environment variable %s must contain at least 32 characters" % name
        )
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m role_benchmark.private_server")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="run the trusted evaluation service")
    serve.add_argument("--pack", required=True, help="service-only module:factory")
    serve.add_argument("--state-db", required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8443)
    serve.add_argument("--player-token-env", default="ROLE_BENCHMARK_PLAYER_TOKEN")
    serve.add_argument("--admin-token-env", default="ROLE_BENCHMARK_ADMIN_TOKEN")
    serve.add_argument("--tls-cert")
    serve.add_argument("--tls-key")

    export = subparsers.add_parser("export", help="export a completed private pack")
    export.add_argument("--endpoint", required=True)
    export.add_argument("--admin-token-env", default="ROLE_BENCHMARK_ADMIN_TOKEN")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            player_token = _secret(args.player_token_env)
            admin_token = _secret(args.admin_token_env)
            pack = load_private_case_pack(args.pack)
            service = PrivateEvaluationService(pack, args.state_db)
            server = make_private_evaluation_http_server(
                service,
                host=args.host,
                port=args.port,
                player_token=player_token,
                admin_token=admin_token,
                tls_certfile=args.tls_cert,
                tls_keyfile=args.tls_key,
            )
            scheme = "https" if args.tls_cert else "http"
            bound_host, bound_port = server.server_address[:2]
            print("private evaluation listening on %s://%s:%s" % (scheme, bound_host, bound_port))
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        result = export_private_results(
            args.endpoint, _secret(args.admin_token_env)
        )
        print(canonical_json_dumps(result))
        return 0
    except Exception as exc:
        print("private evaluation error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
