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
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, List, Dict

from monitor.manage_monitor_db import (
    init_db as init_monitor_db,
    save_event_group,
    fetch_unprocessed_event_groups,
    mark_event_group_processed,
    get_username_by_monitor_id,
    register_monitor,
)
from monitor.create_monitor import create_monitor

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
DEFAULT_MONITOR_WEBHOOK_URL = "https://knowledge.learnwitharobot.com/webhooks/parallel-monitor"
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

def contains_update_keywords(messages: List[dict]) -> bool:
    """Check if any message content contains update-related keywords."""
    update_keywords = ["update", "updates", "news", "latest", "recent", "new", "changes", "monitor"]

    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            content_lower = content.lower()
            if any(keyword in content_lower for keyword in update_keywords):
                return True
    return False


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
    messages = payload.get("messages", [])
    # Check if this is a monitor updates request: model="speed" and contains update keywords
    if model.lower() == "speed" and contains_update_keywords(messages):
        # Route to monitor events stream
        return StreamingResponse(
            stream_monitor_events(username),
            media_type="text/event-stream"
        )
    # Otherwise, route to normal LLM provider
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
async def serve_default_html():
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


@app.get("/create-monitor")
async def serve_create_monitor_html():
    """Serve the HTML page for creating monitors."""
    try:
        with open("html/create-monitor.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return StreamingResponse(iter([html_content]), media_type="text/html")
    except FileNotFoundError:
        return StreamingResponse(
            iter(["<h1>Create Monitor</h1><p>HTML file not found. Please check the html/create-monitor.html file.</p>"]), 
            media_type="text/html"
        )


@app.post("/webhooks/parallel-monitor")
async def parallel_monitor_webhook(request: Request):
    """Webhook receiver for Parallel Monitor events. Stores event_group_ids for later retrieval.

    Always returns HTTP 200 to acknowledge receipt per Parallel AI webhook best practices.
    Any other status code will trigger retries.
    Reference: https://docs.parallel.ai/resources/webhook-setup
    The username is looked up from the monitor_event_groups table using the monitor_id,
    since webhook payloads don't include username information.
    """
    try:
        payload = await request.json()
        data = payload.get("data", {})
        event_info = data.get("event", {})
        event_group_id = event_info.get("event_group_id")
        monitor_id = data.get("monitor_id")
        metadata = data.get("metadata")

        if not event_group_id or not monitor_id:
            # Log error but still return 200 to acknowledge receipt (prevents retries)
            logger = logging.getLogger("webhook")
            logger.warning(f"Missing monitor_id or event_group_id in webhook payload: {payload}")
            return JSONResponse(
                status_code=200,
                content={"status": "received", "error": "Missing monitor_id or event_group_id"}
            )

        # Look up username from monitor_event_groups table using monitor_id
        username = get_username_by_monitor_id(monitor_id)
        if not username:
            logger = logging.getLogger("webhook")
            logger.warning(
                f"Could not find username for monitor_id={monitor_id} in database; "
                f"not storing event_group_id. This may happen if this is the first event "
                f"for a monitor that hasn't been properly registered."
            )
            return JSONResponse(
                status_code=200,
                content={"status": "received", "error": f"Monitor {monitor_id} not found in database"}
            )

        stored = save_event_group(username, monitor_id, event_group_id, metadata)
        if stored:
            return JSONResponse(
                status_code=200,
                content={"status": "stored", "event_group_id": event_group_id}
            )
        else:
            # Event group may have already been stored (duplicate webhook)
            return JSONResponse(
                status_code=200,
                content={"status": "received", "event_group_id": event_group_id, "note": "Event group already exists"}
            )
    except Exception as e:
        # Log error but return 200 to acknowledge receipt and prevent retries
        logger = logging.getLogger("webhook")
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=200,
            content={"status": "received", "error": "Internal processing error"}
        )


@app.post("/v1/monitors/create")
async def create_monitor_endpoint(
    request: Request,
    payload: dict,
    authorization: Optional[str] = Header(None)
):
    """Create a Parallel Monitor via web UI or API.
    Requires valid authentication token. The monitor will be associated with the authenticated user.
    """
    # Extract Bearer token
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    is_valid, username = is_token_valid(token)
    if is_valid == "rate_limited":
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again tomorrow.")
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid or expired authorization token.")
    
    # Get required fields from payload
    query = payload.get("query")
    cadence = payload.get("cadence")
    if not query:
        raise HTTPException(status_code=400, detail="Missing required field: query")
    if not cadence:
        raise HTTPException(status_code=400, detail="Missing required field: cadence")
    if cadence not in ["hourly", "daily", "weekly"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cadence: {cadence}. Must be one of: hourly, daily, weekly"
        )
    # Get Parallel API key
    api_key = os.getenv("PARALLEL_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="PARALLEL_API_KEY not configured on server"
        )
    # Get webhook URL from environment variable with default
    webhook_url = os.getenv("MONITOR_WEBHOOK_URL", DEFAULT_MONITOR_WEBHOOK_URL)
    # Prepare metadata with username
    metadata = {"username": username}
    try:
        # Create the monitor via Parallel API
        created = create_monitor(
            api_key=api_key,
            query=query,
            cadence=cadence,
            webhook_url=webhook_url,
            event_types=["monitor.event.detected"],
            metadata=metadata,
        )
        monitor_id = created.get("monitor_id")
        if monitor_id:
            # Register the monitor_id -> username mapping
            registered = register_monitor(username, monitor_id)
            if not registered:
                logger = logging.getLogger("monitor")
                logger.warning(f"Monitor {monitor_id} created but registration failed (may already exist)")
        return JSONResponse(
            status_code=200,
            content={
                "monitor_id": monitor_id,
                "status": created.get("status", "active"),
                "cadence": created.get("cadence", cadence),
                "query": created.get("query", query),
                "webhook_url": webhook_url,
                "message": "Monitor created successfully"
            }
        )
    except httpx.HTTPStatusError as e:
        logger = logging.getLogger("monitor")
        logger.error(f"Parallel API error: {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to create monitor: {e.response.text}"
        )
    except Exception as e:
        logger = logging.getLogger("monitor")
        logger.error(f"Error creating monitor: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error creating monitor: {str(e)}"
        )

async def stream_monitor_events(username: str) -> AsyncGenerator[str, None]:
    """Stream stored monitor events to the client in SSE format (scoped to a single user).
    Returns OpenAI-compatible streaming format.
    """
    api_key = os.getenv("PARALLELAI_API_KEY")
    if not api_key:
        error_msg = {
            "id": "chatcmpl-error",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "monitor-updates",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "Error: PARALLELAI_API_KEY not set"},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(error_msg)}\n\n"
        yield "data: [DONE]\n\n"
        return

    event_groups = fetch_unprocessed_event_groups(username)
    if not event_groups:
        info_msg = {
            "id": "chatcmpl-info",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "monitor-updates",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "No pending monitor events."},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(info_msg)}\n\n"
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
                for idx, event in enumerate(events_payload.get("events", [])):
                    # Format as OpenAI-compatible SSE response
                    event_output = event.get("output", "")
                    event_date = event.get("event_date", "")
                    source_urls = event.get("source_urls", [])
                    # Create a formatted message combining event details
                    formatted_content = f"Event Date: {event_date}\n\n{event_output}"
                    if source_urls:
                        formatted_content += f"\n\nSources: {', '.join(source_urls)}"

                    # Format as OpenAI streaming response
                    is_last_event = idx == len(events_payload.get("events", [])) - 1
                    message = {
                        "id": f"chatcmpl-{event_group_id[:8]}-{idx}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "monitor-updates",
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": formatted_content + ("\n\n---\n\n" if not is_last_event else "")
                            },
                            "finish_reason": "stop" if is_last_event else None
                        }]
                    }
                    yield f"data: {json.dumps(message)}\n\n"
                mark_event_group_processed(event_group_id)
            except httpx.HTTPError as exc:
                error_msg = {
                    "id": "chatcmpl-error",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "monitor-updates",
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": f"Error: Failed to fetch events for {event_group_id}: {str(exc)}"
                        },
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(error_msg)}\n\n"
    yield "data: [DONE]\n\n"

# ========== Main Execution ==========
if __name__ == "__main__":
    import uvicorn
    # Get server configuration from environment variables
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8080"))

    # SSL/TLS configuration for HTTPS
    ssl_certfile = os.getenv("SSL_CERTFILE")
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    # Configure SSL if certificates are provided
    ssl_kwargs = {}

    if ssl_certfile and ssl_keyfile:
        if not os.path.exists(ssl_certfile):
            raise FileNotFoundError(f"SSL certificate file not found: {ssl_certfile}")
        if not os.path.exists(ssl_keyfile):
            raise FileNotFoundError(f"SSL key file not found: {ssl_keyfile}")
        ssl_kwargs["ssl_certfile"] = ssl_certfile
        ssl_kwargs["ssl_keyfile"] = ssl_keyfile
        print(f"Starting HTTPS server on {host}:{port}")
        print(f"SSL Certificate: {ssl_certfile}")
        print(f"SSL Key: {ssl_keyfile}")
    else:
        print(f"Starting HTTP server on {host}:{port}")
        if not ssl_certfile and not ssl_keyfile:
            print("Note: To enable HTTPS, set SSL_CERTFILE and SSL_KEYFILE environment variables")
        else:
            raise ValueError("Both SSL_CERTFILE and SSL_KEYFILE must be set to enable HTTPS")
    uvicorn.run(app, host=host, port=port, **ssl_kwargs)
