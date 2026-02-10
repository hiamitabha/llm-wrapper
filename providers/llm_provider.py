"""
LLMProvider class for OpenAI-compatible API providers.
"""

import httpx
import json
import logging
import os
import time
from typing import AsyncGenerator, Optional, List, Dict
from fastapi import HTTPException


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

    def check_if_model_supported(self, model_name: str):
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
                status_code=500,
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
