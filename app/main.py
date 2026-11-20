import logging
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import router
from app.config import Settings, get_settings
from app.errors import AppError
from app.keitaro.base import KeitaroClient, KeitaroError
from app.keitaro.fake import FakeKeitaroClient
from app.keitaro.http import HttpKeitaroClient

BASE_DIR = Path(__file__).resolve().parent


def create_app(
    *, settings: Settings | None = None, keitaro: KeitaroClient | None = None
) -> FastAPI:
    settings = settings or get_settings()
    if keitaro is None:
        keitaro = (
            FakeKeitaroClient()
            if settings.keitaro_mode == "fake"
            else HttpKeitaroClient(settings)
        )

    application = FastAPI(
        title="Adrobot Keitaro Wrapper",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )
    application.state.settings = settings
    application.state.keitaro = keitaro
    application.include_router(router)
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")

    @application.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "details": exc.details,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Check the highlighted input values",
                    "retryable": False,
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )

    @application.exception_handler(KeitaroError)
    async def handle_keitaro_error(request: Request, exc: KeitaroError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable and not exc.outcome_unknown,
                    "details": {"outcome_unknown": exc.outcome_unknown},
                }
            },
        )

    @application.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"keitaro_mode": cast(Settings, request.app.state.settings).keitaro_mode},
        )

    @application.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
    def editor(request: Request, campaign_id: int) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="editor.html",
            context={
                "campaign_id": campaign_id,
                "keitaro_mode": cast(Settings, request.app.state.settings).keitaro_mode,
            },
        )

    return application


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = create_app()
