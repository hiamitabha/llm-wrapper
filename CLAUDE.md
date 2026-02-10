# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

llm-wrapper is a FastAPI-based proxy server for intercepting and routing LLM inference calls across multiple providers (XAI, Perplexity, Sambanova, Together AI, OpenAI, Parallel AI). It provides token-based authentication, rate limiting, and integration with Parallel AI monitors for web update tracking.

## Development Setup

```bash
# Create virtual environment
python3 -m venv ./venv
source ./venv/bin/activate

# Install dependencies
python3 -m pip install -r requirements.txt

# Initialize token database (first time only)
python3 tokens/manage_tokens.py list

# Start server
python3 llm-wrapper.py
```

## Key Commands

### Token Management
```bash
# Add a new authentication token
python3 tokens/manage_tokens.py add --username <username> --expiry "YYYY-MM-DD HH:MM:SS" --rate-limit <limit>

# List all tokens
python3 tokens/manage_tokens.py list

# Delete a token
python3 tokens/manage_tokens.py delete --token <token>
```

### Monitor Management
```bash
# Create a monitor (command-line)
python3 monitor/create_monitor.py --username <username> --query "<query>" --cadence <hourly|daily|weekly> --webhook_url <url> --event_types "monitor.event.detected"

# Export required API key first
export PARALLELAI_API_KEY="your-key-here"
```

### Running Tests
```bash
# Run test suite
python3 -m unittest tests/test-server.py
```

### Running in Background
```bash
# Using nohup
nohup python3 llm-wrapper.py &

# Using systemd (recommended for production)
systemctl start <service-name>
```

## Architecture

### Core Components

**llm-wrapper.py** - Main FastAPI application with:
- `LLMProvider` class: Handles requests to individual LLM providers (streaming & non-streaming)
- `AnalyticsLogger`: Logs requests to llm_proxy.log
- Token validation and rate limiting middleware
- Webhook endpoints for Parallel Monitor events
- Background worker for auto-deactivating expired monitors

**tokens/manage_tokens.py** - Authentication token management:
- SQLite database at `tokens/auth_tokens.db`
- Schema: token, username, expiry, request_count, rate_limit, last_request_date, lifetime_requests
- Tokens reset daily; rate limits apply per 24-hour period

**monitor/** - Parallel AI monitor integration:
- `create_monitor.py`: Creates monitors via Parallel API
- `manage_monitor_db.py`: Local SQLite database for tracking monitors and webhook events
- Monitors auto-deactivate after 24 hours
- Users are limited to one active monitor at a time (previous monitors auto-deactivated when creating new ones)

**html/** - Web interface:
- `index.html`: Landing page
- `create-monitor.html`: Web UI for creating monitors
- Payment success/error/cancel pages

### Configuration

**config.json** - Provider configuration with structure:
```json
{
  "provider_key": {
    "name": "Provider Name",
    "base_url": "https://api.provider.com/v1",
    "api_key_env": "ENV_VAR_NAME",
    "supported_models": ["model1", "model2"],
    "payload_extra_parameters": {
      // Provider-specific parameters injected into requests
    }
  }
}
```

**.env file** - Contains API keys referenced by `api_key_env` in config.json. Also supports:
- `SSL_CERTFILE` / `SSL_KEYFILE`: For HTTPS
- `SERVER_PORT`: Custom port (default: 8080)
- `MONITOR_WEBHOOK_URL`: Webhook URL for monitors
- `PARALLELAI_API_KEY`: Required for monitor functionality

### Request Flow

1. Client sends request to `/v1/chat/completions` with Bearer token
2. Token validated and rate limit checked against `tokens/auth_tokens.db`
3. Request model matched to provider in `config.json`
4. If model is "speed" and message contains update-related keywords, queries monitor database for unprocessed events
5. Otherwise, request proxied to appropriate provider with `payload_extra_parameters` merged in
6. Response returned (streaming or standard) in OpenAI-compatible format
7. Request count incremented in database

### Special Model: "speed"

When the model is "speed", the system checks if the user's message contains update-related keywords (e.g., "update", "latest", "recent news"). If so, it queries the local monitor database for unprocessed event groups and returns them formatted as a chat response. Otherwise, it proxies the request to the Parallel AI provider.

## Important Implementation Notes

### Provider-Specific Behavior

**Perplexity Sonar**: Response format differs in streaming mode. The `normalize_response()` method in `LLMProvider` handles conversion to OpenAI-compatible format by extracting the delta content from their specific response structure.

**XAI**: Supports search parameters that can be injected via `payload_extra_parameters` to include news searches in responses.

**Parallel AI**: Used for the "speed" model and monitor integration. Requires `PARALLELAI_API_KEY` environment variable.

### Database Schema

**tokens/auth_tokens.db**:
- Rate limiting resets daily based on `last_request_date`
- `lifetime_requests` tracks total requests across all time
- `request_count` resets to 0 when date changes

**monitor database** (in monitor/manage_monitor_db.py):
- `monitors` table: Tracks monitor_id, username, query, cadence, created_at, deactivated_at
- `event_groups` table: Stores webhook events with processed flag
- Users limited to one active monitor; creating new one deactivates previous

### Background Workers

`deactivate_expired_monitors_worker()`: AsyncIO task that runs every hour to auto-deactivate monitors older than 24 hours, both locally and on Parallel API.

### Error Handling

- Missing API keys raise `ValueError` on provider initialization
- Invalid tokens return 401 Unauthorized
- Rate limit exceeded returns 429 Too Many Requests
- Provider API errors are logged and re-raised as HTTPExceptions with original status codes

## Common Pitfalls

1. **load_dotenv() not finding .env**: On some systems, specify absolute path: `load_dotenv("/full/path/to/.env")`

2. **Commenting out providers in config.json**: JSON doesn't support comments. Delete the provider entry entirely if not needed.

3. **Token database not initialized**: Must run `python3 tokens/manage_tokens.py list` before first use to create the database schema.

4. **SSL certificates not readable**: Ensure the process user has read permissions on cert/key files specified in SSL_CERTFILE/SSL_KEYFILE.

5. **Monitor webhooks not working**: Verify `MONITOR_WEBHOOK_URL` is set and accessible from Parallel AI servers. Default is `https://knowledge.learnwitharobot.com/webhooks/parallel-monitor`.

## Environment Variables Reference

Required for each provider being used:
- `XAI_API_KEY`
- `PPLX_API_KEY`
- `SAMBANOVA_API_KEY`
- `TOGETHER_API_KEY`
- `OPENAI_API_KEY`
- `PARALLELAI_API_KEY` (required for monitor functionality)

Optional:
- `SSL_CERTFILE`: Path to SSL certificate for HTTPS
- `SSL_KEYFILE`: Path to SSL private key for HTTPS
- `SERVER_PORT`: Server port (default: 8080)
- `MONITOR_WEBHOOK_URL`: Custom webhook URL for monitors
