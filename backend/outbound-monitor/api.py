#!/usr/bin/env python3
"""Placeholder FastAPI entrypoint for the outbound-monitor pipeline."""

from fastapi import FastAPI

app = FastAPI(title="Outbound Monitor API")


@app.get("/health")
def health():
    return {"status": "ok", "pipeline": "outbound-monitor"}
