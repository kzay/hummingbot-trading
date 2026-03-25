from __future__ import annotations

import argparse
import logging
import os

from platform_lib.logging.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


def _to_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _build_auth_check():
    auth_enabled = _to_bool(os.getenv("REALTIME_UI_API_AUTH_ENABLED", "false"))
    auth_token = os.getenv("REALTIME_UI_API_AUTH_TOKEN", "").strip()
    allow_query_token = _to_bool(os.getenv("REALTIME_UI_API_ALLOW_QUERY_TOKEN", "false"))

    if auth_enabled and not auth_token:
        raise RuntimeError("REALTIME_UI_API_AUTH_ENABLED requires REALTIME_UI_API_AUTH_TOKEN")

    def _auth_check(request):
        from starlette.responses import Response

        if not auth_enabled:
            return None

        authorized = request.headers.get("authorization", "") == f"Bearer {auth_token}"
        if not authorized and allow_query_token:
            authorized = request.query_params.get("token", "").strip() == auth_token

        if authorized:
            return None

        return Response(
            content='{"status":"unauthorized"}',
            status_code=401,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    return _auth_check


def create_app():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from services.common.research_api import create_research_routes

    cors_allow_origin = os.getenv("REALTIME_UI_API_CORS_ALLOW_ORIGIN", "*").strip() or "*"
    allowed_origins = [
        item.strip()
        for item in os.getenv("REALTIME_UI_API_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    ]
    if not allowed_origins:
        allowed_origins = [cors_allow_origin] if cors_allow_origin != "*" else ["*"]

    auth_check = _build_auth_check()

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes = [
        Route("/health", health, methods=["GET"]),
        *create_research_routes(auth_check=auth_check),
    ]
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    ]
    return Starlette(routes=routes, middleware=middleware)


def run() -> None:
    import uvicorn

    bind_host = os.getenv("RESEARCH_WORKER_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.getenv("RESEARCH_WORKER_PORT", "9920"))
    app = create_app()

    logger.info("research_worker starting host=%s port=%s", bind_host, port)
    uvicorn.run(
        app,
        host=bind_host,
        port=port,
        log_level="info",
        access_log=True,
        ws="auto",
        lifespan="off",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dedicated research worker API.")
    parser.add_argument("--once", action="store_true", help="Unused compatibility flag; kept for service symmetry.")
    _ = parser.parse_args()
    run()


if __name__ == "__main__":
    main()
