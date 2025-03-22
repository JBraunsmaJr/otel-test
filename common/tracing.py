from http import HTTPMethod

import httpx
from httpx import Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.propagate import inject, extract
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from functools import wraps
import logging

LOGGER: logging.Logger | None = None

def setup_logging(endpoint: str):
    logger_provider = LoggerProvider()
    log_exporter = OTLPLogExporter(endpoint=endpoint)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

    handler = LoggingHandler(level=logging.INFO,
                             logger_provider=logger_provider)
    logging.basicConfig(handlers=[handler], level=logging.INFO)

    global LOGGER
    LOGGER = logging.getLogger(__name__)
    return LOGGER

def setup_tracing(
        app,
        service_name: str,
        tracing_endpoint: str
):
    provider: TracerProvider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name})
    )

    trace.set_tracer_provider(provider)
    otlp_exporter = OTLPSpanExporter(
        endpoint=tracing_endpoint
    )
    span_processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(span_processor)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    RequestsInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tracer = trace.get_tracer(__name__)
        context = extract(request.headers) # Extract trace context from headers

        with tracer.start_as_current_span(request.url.path, context=context):
            response = await call_next(request)
        return response

async def traced_http(method: HTTPMethod,
                      url: str,
                      client: httpx.AsyncClient,
                      headers: dict = None,
                      json_data = None,
                      form_data = None):
    headers = headers or {}
    inject(headers) # injects trace context
    response: Response | None = None

    parameters = dict()
    if json_data is not None:
        parameters["json"] = json_data
    elif form_data is not None:
        parameters["data"] = form_data

    match method:
        case HTTPMethod.GET:
            response = await client.get(url, headers=headers)
        case HTTPMethod.POST:
            response = await client.post(url, **parameters, headers=headers)
        case HTTPMethod.PUT:
            response = await client.put(url, **parameters, headers=headers)
        case HTTPMethod.DELETE:
            response = await client.delete(url, headers=headers)

    return response

def traced_function(func):
    """
    Decorator to create a span for a function
    The span name defaults to the function name but can be overridden

    :param func:
    :return:
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        span_name = func.__name__
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(span_name):
            return func(*args, **kwargs)
    return wrapper


def traced_class(cls):
    """
    Class decorator to apply tracing to all methods
    :param cls: Class to transform all functions into traced functions

    :example
        @traced_class
        class DataService:
            def clean(self, data):
                return data.strip()
    :return:
    """
    for attr_name in dir(cls):
        attr = getattr(cls, attr_name)
        if callable(attr) and not attr_name.startswith("__"):
            setattr(cls, attr_name, traced_function(attr_name)(attr))
    return cls

def log_with_trace(message: str, level=logging.INFO, **kwargs):
    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(message)

    LOGGER.log(level, message, extra=kwargs)