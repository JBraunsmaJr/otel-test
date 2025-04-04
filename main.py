import os
from contextlib import asynccontextmanager
from http import HTTPMethod

import httpx
import uvicorn
from fastapi import FastAPI
from common.tracing import setup_tracing, TracingMiddleware, traced_http, traced_function, log_with_trace, setup_logging
import time
import random
import logging

logger = setup_logging(endpoint="http://jaeger:4317/v1/traces")
logger.setLevel(logging.DEBUG)


SERVICE_NAME = os.environ.get("SERVICE_NAME")
CALL_ENDPOINT = os.environ.get("INVOKE", None)

app = FastAPI()

setup_tracing(app, SERVICE_NAME, "http://jaeger:4317/v1/traces")
app.add_middleware(TracingMiddleware)

@asynccontextmanager
async def get_http_client():
    async with httpx.AsyncClient() as client:
        yield client

@app.get("/")
async def root():
    if CALL_ENDPOINT is not None:
        async with get_http_client() as client:
            response = await traced_http(HTTPMethod.GET, CALL_ENDPOINT, client)
            print(f"{response.status_code}")

    return {"message": "Hello World"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

@app.get("/random")
async def test_random():
    log_with_trace("Starting random thing")
    do_some_work()
    return {"message": "YES"}

@traced_function
def do_some_work():
    log_with_trace("This is a message")
    wait_time = random.uniform(0.5, 2.5)
    time.sleep(wait_time)
    log_with_trace("Wait period", wait_time=wait_time)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)