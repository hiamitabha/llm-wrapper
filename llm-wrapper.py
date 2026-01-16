import httpx
import json
import os
import logging
import time
import asyncio
import uvicorn
import sqlite3

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, List, Dict

from monitor.manage_monitor_db import (
    init_db as init_monitor_db,
    save_event_group,
    fetch_unprocessed_event_groups,
    mark_event_group_processed,
)

# Initialize FastAPI application
app = FastAPI(
    title="LLM Proxy API",
    version="1.0.0",
    description="Unified API wrapper LLM providers"
)

load_dotenv()

#Global dictionary of providers
providers = dict()

PARALLEL_API_BASE = "https://api.parallel.ai/v1alpha"
# ========== Core LLM Provider Class ==========
class LLMProvider:
    def __init__(self, name: str, base_url: str, api_key_env: str,
                 supported_models: List[str],
                 payload_extra_options: Dict):
        """Initialize the LLMProvider
        """
        self.name = name
        self.client = None
        self.base_url = base_url
        self.supported_models = supported_models
        self.payload_extra_options = payload_extra_options
        self.logger = logging.getLogger(name)
        self.api_key = os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(f"API Key for provder {name} is missing."
                             f"Please either provide the API Key, or edit the config.json file to exclude the provider")

    def get_name(self) -> str:
        """Get the name of the model
        """
        return self.name

    def check_if_model_supported(self, model_name:str):
        """Check if a specific model is supported
        """
        if model_name in self.supported_models:
            return True
        else:
            return False

    def chat_completion(self, payload: dict, stream: bool = False):
        """Complete the chat, given payload
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        if self.payload_extra_options:
            payload.update(self.payload_extra_options)
        
        if stream:
            return self._stream_completion(payload, headers)
        else:
            return self._standard_completion(payload, headers)

    def _standard_completion(self, payload: dict, headers: dict):
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=300
            )
            response_json = response.json()
            return response_json
        except httpx.HTTPStatusError as e:
            self.logger.error(f"API Error: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Provider API error: {e.response.text}"
            )
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing JSON response: {e}")
            raise HTTPException(
                status_code= 500,
                detail="Error parsing JSON response"
            )

    async def _stream_completion(self, payload: dict, headers: dict) -> AsyncGenerator[str, None]:
        self.client = httpx.AsyncClient()
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=300
            )
            async for chunk in response.aiter_lines():
                processed = self.process_streaming_chunk(chunk)
                if processed:
                    yield processed
        except httpx.HTTPError as e:
            self.logger.error(f"Streaming error: {str(e)}")
            yield json.dumps({"error": str(e)})

    def process_streaming_chunk(self, chunk: str) -> Optional[str]:
        if chunk.startswith("data: "):
            data = chunk[6:].strip()
            if data == "[DONE]":
                return "data: [DONE]\n\n"
            try:
                parsed = json.loads(data)
                normalized = self.normalize_response(parsed)
                if normalized:
                    return f"data: {json.dumps(normalized)}\n\n"
                else:
                    return None
            except json.JSONDecodeError:
                return None
        return None

    def normalize_response(self, response: dict) -> dict:
        if "choices" not in response:
            response["choices"] = [{"message": {"role": "assistant", "content": ""}}]
        elif self.name == "Perplexity Sonar":
           choices = response.get("choices")
           if choices and choices[0].get("delta"):
               delta = choices[0]["delta"]
               response["choices"] = [{"index": 0, "delta": delta}]
           else:
               return None
        response["created"] = int(time.time())
        response["model"] = response.get("model", "unknown")
        return response


class AnalyticsLogger:
    def __init__(self):
        self.logger = logging.getLogger("analytics")
        logging.basicConfig(
            filename="llm_proxy.log",
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    def log_request(self, username: str, provider: str, model: str):
        self.logger.info(f"Request - Username: {username} Provider: {provider}, Model: {model}")


def load_providers(config_file: str):
    global providers
    with open(config_file, 'r') as f:
        data = json.load(f)
    
        for provider_name, config_data in data.items():
            providers[provider_name] = LLMProvider(
                name=config_data.get("name"),
                base_url=config_data.get("base_url"),
                api_key_env=config_data.get("api_key_env"),
                supported_models=config_data.get("supported_models", []),
                payload_extra_options = config_data.get("payload_extra_parameters")
            )

def get_provider(model: str) -> LLMProvider:
    """Returns an instance of the LLMProvider given an input model.
       Note: In case multiple LLM providers provide the same model,
       the current logic is to return the LLMProvider first encountered.
    """
    for provider in providers.values():
        if provider.check_if_model_supported(model):
            return provider
    raise HTTPException(
        status_code=400,
        detail=f"Model {model} not supported"
    )


def is_token_valid(token: str, db_path="tokens/auth_tokens.db") -> (bool, str):
    """Check if the token exists, is not expired, and enforce rate limiting. Returns (True, username) if valid, else (False, None)."""
    if not token:
        return False, None
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT username, expiry, request_count, rate_limit, last_request_date, lifetime_requests FROM tokens WHERE token=?", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, None
    username, expiry, request_count, rate_limit, last_request_date, lifetime_requests = row
    try:
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        conn.close()
        return False, None
    if expiry_dt <= datetime.now():
        conn.close()
        return False, None
    # Rate limit enforcement
    today = datetime.now().date().isoformat()
    if last_request_date != today:
        # Reset count for new day
        request_count = 0
        last_request_date = today
    if request_count >= rate_limit:
        conn.close()
        # Special return for rate limit exceeded
        return "rate_limited", username
    # Increment request count, lifetime requests, and update last_request_date
    c.execute("UPDATE tokens SET request_count=?, last_request_date=?, lifetime_requests=? WHERE token=?", 
              (request_count + 1, today, lifetime_requests + 1, token))
    conn.commit()
    conn.close()
    return True, username

@app.on_event("startup")
def startup_event():
    load_providers("./config.json")
    init_monitor_db()

# ========== API Endpoints ==========
@app.post("/v1/chat/completions")
async def chat_endpoint(
    request: Request,
    payload: dict,
    authorization: Optional[str] = Header(None)
):
    # Extract Bearer token
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    is_valid, username = is_token_valid(token)
    if is_valid == "rate_limited":
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again tomorrow.")
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid or expired authorization token.")

    model = payload.get("model", "")
    provider = get_provider(model)
    AnalyticsLogger().log_request(username, provider.get_name(), model)
   
    if payload.get("stream") == True:
        return StreamingResponse(
            provider.chat_completion(payload, True),
            media_type="text/event-stream"
        )
    else:
        response = provider.chat_completion(payload, False)
        return response

@app.get("/")
async def root():
    """Serve the default HTML page for the LLM wrapper."""
    try:
        with open("html/index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return StreamingResponse(iter([html_content]), media_type="text/html")
    except FileNotFoundError:
        return StreamingResponse(
            iter(["<h1>LLM Wrapper API Gateway</h1><p>HTML file not found. Please check the html/index.html file.</p>"]), 
            media_type="text/html"
        )


@app.post("/webhooks/parallel-monitor")
async def parallel_monitor_webhook(request: Request):
    """Webhook receiver for Parallel Monitor events. Stores event_group_ids for later retrieval."""
    payload = await request.json()
    data = payload.get("data", {})
    event_info = data.get("event", {})
    event_group_id = event_info.get("event_group_id")
    monitor_id = data.get("monitor_id")
    metadata = data.get("metadata")

    if not event_group_id or not monitor_id:
        raise HTTPException(status_code=400, detail="Missing monitor_id or event_group_id in webhook payload.")

    save_event_group(monitor_id, event_group_id, metadata)
    return {"status": "stored", "event_group_id": event_group_id}


async def stream_monitor_events() -> AsyncGenerator[str, None]:
    """Stream stored monitor events to the client in SSE format."""
    api_key = os.getenv("PARALLEL_API_KEY")
    if not api_key:
        yield "data: {\"error\":\"PARALLEL_API_KEY not set\"}\n\n"
        yield "data: [DONE]\n\n"
        return

    event_groups = fetch_unprocessed_event_groups()
    if not event_groups:
        yield "data: {\"info\":\"No pending monitor events\"}\n\n"
        yield "data: [DONE]\n\n"
        return

    headers = {
        "x-api-key": api_key
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for group in event_groups:
            monitor_id = group["monitor_id"]
            event_group_id = group["event_group_id"]
            url = f"{PARALLEL_API_BASE}/monitors/{monitor_id}/event_groups/{event_group_id}"
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                events_payload = response.json()
                for event in events_payload.get("events", []):
                    message = {
                        "monitor_id": monitor_id,
                        "event_group_id": event_group_id,
                        "event": event,
                        "metadata": json.loads(group["metadata"]) if group.get("metadata") else None,
                        "received_at": group["received_at"]
                    }
                    yield f"data: {json.dumps(message)}\n\n"
                mark_event_group_processed(event_group_id)
            except httpx.HTTPError as exc:
                error_message = {"error": f"Failed to fetch events for {event_group_id}", "detail": str(exc)}
                yield f"data: {json.dumps(error_message)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/update/chat/completions")
async def monitor_updates_endpoint(authorization: Optional[str] = Header(None)):
    """Expose monitor updates as an SSE stream. Requires valid bearer token."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    is_valid, _ = is_token_valid(token)
    if is_valid == "rate_limited":
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again tomorrow.")
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid or expired authorization token.")

    return StreamingResponse(stream_monitor_events(), media_type="text/event-stream")

# ========== Main Execution ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
