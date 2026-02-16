"""
AnthropicProvider class for Anthropic (Claude) API with automatic format conversion.
Accepts OpenAI format requests and converts them to/from Anthropic Messages API format.
"""

import httpx
import json
import logging
import os
import time
from typing import AsyncGenerator, Optional, List, Dict
from fastapi import HTTPException


class AnthropicProvider:
    def __init__(self, name: str, base_url: str, api_key_env: str,
                 supported_models: List[str],
                 payload_extra_options: Dict):
        """Initialize the AnthropicProvider for Claude models"""
        self.name = name
        self.client = None
        self.base_url = base_url
        self.supported_models = supported_models
        self.payload_extra_options = payload_extra_options
        self.logger = logging.getLogger(name)
        self.api_key = os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(f"API Key for provider {name} is missing. "
                             f"Please either provide the API Key, or edit the config.json file to exclude the provider")

    def get_name(self) -> str:
        """Get the name of the provider"""
        return self.name

    def check_if_model_supported(self, model_name: str):
        """Check if a specific model is supported"""
        return model_name in self.supported_models

    def _convert_openai_to_anthropic(self, openai_payload: dict) -> dict:
        """Convert OpenAI format to Anthropic Messages API format"""
        messages = openai_payload.get("messages", [])

        # Extract system message if present
        system_content = None
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                filtered_messages.append({
                    "role": msg.get("role"),
                    "content": msg.get("content")
                })

        # Build Anthropic payload
        anthropic_payload = {
            "model": openai_payload.get("model"),
            "messages": filtered_messages,
            "max_tokens": openai_payload.get("max_tokens", 4096),  # Anthropic requires max_tokens
        }

        if system_content:
            anthropic_payload["system"] = system_content

        # Optional parameters
        if "temperature" in openai_payload:
            anthropic_payload["temperature"] = openai_payload["temperature"]
        if "top_p" in openai_payload:
            anthropic_payload["top_p"] = openai_payload["top_p"]
        if "stream" in openai_payload:
            anthropic_payload["stream"] = openai_payload["stream"]

        # Apply extra options from config
        if self.payload_extra_options:
            anthropic_payload.update(self.payload_extra_options)

        return anthropic_payload

    def _convert_anthropic_to_openai(self, anthropic_response: dict, model: str) -> dict:
        """Convert Anthropic response to OpenAI format"""
        content = ""
        if anthropic_response.get("content"):
            # Anthropic returns content as a list of content blocks
            for block in anthropic_response["content"]:
                if block.get("type") == "text":
                    content += block.get("text", "")

        openai_response = {
            "id": anthropic_response.get("id", "chatcmpl-" + str(int(time.time()))),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": self._map_stop_reason(anthropic_response.get("stop_reason"))
            }],
            "usage": {
                "prompt_tokens": anthropic_response.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": anthropic_response.get("usage", {}).get("output_tokens", 0),
                "total_tokens": (
                    anthropic_response.get("usage", {}).get("input_tokens", 0) +
                    anthropic_response.get("usage", {}).get("output_tokens", 0)
                )
            }
        }
        return openai_response

    def _map_stop_reason(self, anthropic_stop_reason: Optional[str]) -> str:
        """Map Anthropic stop_reason to OpenAI finish_reason"""
        mapping = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop",
        }
        return mapping.get(anthropic_stop_reason, "stop")

    def chat_completion(self, payload: dict, stream: bool = False):
        """Complete the chat using Anthropic API"""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }

        # Convert OpenAI format to Anthropic format
        anthropic_payload = self._convert_openai_to_anthropic(payload)

        if stream:
            return self._stream_completion(anthropic_payload, headers, payload.get("model"))
        else:
            return self._standard_completion(anthropic_payload, headers, payload.get("model"))

    def _standard_completion(self, payload: dict, headers: dict, model: str):
        """Standard (non-streaming) completion"""
        try:
            response = httpx.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
                timeout=300
            )
            response.raise_for_status()
            anthropic_response = response.json()

            # Convert back to OpenAI format
            return self._convert_anthropic_to_openai(anthropic_response, model)
        except httpx.HTTPStatusError as e:
            self.logger.error(f"Anthropic API Error: {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Anthropic API error: {e.response.text}"
            )
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing JSON response: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error parsing JSON response"
            )

    async def _stream_completion(self, payload: dict, headers: dict, model: str) -> AsyncGenerator[str, None]:
        """Streaming completion"""
        self.client = httpx.AsyncClient()
        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
                timeout=300
            ) as response:
                response.raise_for_status()

                # Track message state for proper OpenAI format
                message_id = f"chatcmpl-{int(time.time())}"

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue

                    # Anthropic SSE format: "event: <type>" followed by "data: <json>"
                    if line.startswith("event:"):
                        event_type = line.split(":", 1)[1].strip()
                        continue

                    if line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()

                        try:
                            data = json.loads(data_str)

                            # Handle different event types
                            if data.get("type") == "message_start":
                                # Send initial chunk
                                openai_chunk = {
                                    "id": message_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"role": "assistant", "content": ""},
                                        "finish_reason": None
                                    }]
                                }
                                yield f"data: {json.dumps(openai_chunk)}\n\n"

                            elif data.get("type") == "content_block_delta":
                                # Extract text delta
                                delta = data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text = delta.get("text", "")
                                    openai_chunk = {
                                        "id": message_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": text},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield f"data: {json.dumps(openai_chunk)}\n\n"

                            elif data.get("type") == "message_delta":
                                # Handle stop reason
                                stop_reason = data.get("delta", {}).get("stop_reason")
                                if stop_reason:
                                    openai_chunk = {
                                        "id": message_id,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {},
                                            "finish_reason": self._map_stop_reason(stop_reason)
                                        }]
                                    }
                                    yield f"data: {json.dumps(openai_chunk)}\n\n"

                            elif data.get("type") == "message_stop":
                                # End of stream
                                yield "data: [DONE]\n\n"

                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPError as e:
            self.logger.error(f"Anthropic streaming error: {str(e)}")
            error_chunk = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": f"Error: {str(e)}"},
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if self.client:
                await self.client.aclose()
