# llm-wrapper
llm-wrapper is built to intercept calls for inference on Large Language Models (LLMs) and re-route the calls to customized cloud providers with customized options and parameters. In essence, you hack the LLM inference API call made by your application, without actually touching the application.

An instance of llm-wrapper is running at: http://knowledge.learnwitharobot.com

# Reasons to use llm-wrapper
llm-wrapper can be useful in the following scenarios:

1. Re-routing LLM calls with specific parameters without touching the application. Most applications have an interface where you can input an OpenAI API compatible cloud provider, and API Key, and usually a LLM model name for running LLM inference. The app then routes calls to the provided LLM provider when it requires to do inference. You might want to adjust specific parameters of the LLM call, but then you would need to change the app software/code, which you might not have access to, or might not understand. llm-wrapper is used to hack the LLM inference call, and then re-route with the needed parameters without much added latency. Please see the use case for Vector robot's Wirepod server as a reference for this use case.
2. Applying rate limits to your LLM inference calls. Typically apps don't set rate limits on the number of LLM inference queries they will issue. Cloud providers allow you to set coarse expense limits such as the amount of money you want to spend in a week or a month. llm-wrapper can be useful to set rate limits on per token granularity, so you can manage exactlty how much inference you want to do.
3. Routing LLM Inference calls across multiple providers. You can implement your own version of Openrouter.ai by routing inference calls across different cloud providers depending on which provider is cheap, has maximum uptime, or is delivering the lowest latency to your request.

4. Parsing the response to generate the final response in OpenAI API compatible format. As an example, for some vendors such as Perplexity Sonar who provide details on citations and search channels, the results need to be morphed to be compliant with other Open API AI compatible providers. 

Note that items 2 and 3 are in the works and are not available yet.

# Using llm-wrapper
After cloning the code from this git repository, please follow the following steps. These steps have been tried and tested on python 3.10

1. Install dependencies:
   
   `python3 -m venv ./venv`
   
   `source ./venv/bin/activate`
   
   `python3 -m pip install -r requirements.txt`
2. Edit the config file. The default config file is set up for XAI, and Perplexity Sonar, and is designed to issue a LLM inference call with additional search for the latest news. The relevant lines in the config file are as follows:
   
```"payload_extra_parameters": {
            "search_parameters": {
                "mode": "on",
                "sources": [{"type": "news"}]
            }
        }
```

Anything added for the key `payload_extra_parameters` is updated in the LLM inference request.

You can also modify the `base_url` to point to your preferred LLM provider (make sure they are OpenAI supported), or `supported_models` to choose a different model you want to use for LLM inference. The `api_key_env` specifies the name of the API_KEY environment variable. As an example, for the provider XAI, the name of the environment varaiable is set to XAI_API_KEY

3. Edit the  .env file which specifies the API Keys for all the providers. You need to get your own API key for each provider. As an example for XAI, you can get the API KEY at the URL https://console.x.ai/
 Currently the .env file looks like:

```
# Insert your XAI API Key below
XAI_API_KEY="<Insert your XAI APi Key here"
# Insert your Perplexity API Key below
PPLX_API_KEY="<Insert your Perplexity Sonar API Key here>"
# Insert your Anthropic API Key below
ANTHROPIC_API_KEY="<Insert your Anthropic API Key here>"
```

You can get your Anthropic API key at: https://console.anthropic.com/

4. Before starting the server for the first time, create the token database (this only needs to be done once):

`python3 tokens/manage_tokens.py list`

This command will initialize the database file at `tokens/auth_tokens.db` with the required schema. You can then use the same script to add or manage tokens as needed.

To add a new token use:
`python3 tokens/manage_tokens.py add --username <username> --expiry <expiry date> --rate-limit <rate-limit>`

You can now see the token with `python3 tokens/manage_tokens.py list`

5. Now start the server using:

`python3 llm-wrapper.py`

This will start the llm wrapper on your localhost at http://0.0.0.0:8080 and use it as your API Key

6. Now on your app which needs to do LLM Inference, you can set the parameters for LLM inference as:
API URL: http://localhost:8080/v1
API Key: <Token created using Step 4>
Model Name: <Choose one of the models from the `supported_models` section of config.json

# API Format Support

llm-wrapper supports both OpenAI and Anthropic API formats:

## OpenAI API Format
Most providers (XAI, Perplexity, Sambanova, Together AI, OpenAI) use the OpenAI-compatible API format. Your application sends requests in OpenAI format, and they're passed through directly.

## Anthropic API Format (Claude Models)
For Claude models from Anthropic, llm-wrapper automatically handles the conversion:

1. **Your app sends requests in OpenAI format** (standard `/v1/chat/completions` endpoint)
2. llm-wrapper converts the request to Anthropic's Messages API format
3. The request is sent to Anthropic's API
4. Anthropic's response is converted back to OpenAI format
5. Your app receives the response in OpenAI format

This means you can use Claude models with any application that supports OpenAI API format, without modifying your application code.

### Supported Claude Models
- `claude-3-5-sonnet-20241022` (recommended)
- `claude-3-5-haiku-20241022`
- `claude-3-opus-20240229`
- `claude-3-sonnet-20240229`
- `claude-3-haiku-20240307`

### Example Usage
```bash
curl -X POST "http://localhost:8080/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ],
    "stream": true
  }'
```

The system automatically detects that this is a Claude model and handles the format conversion transparently.

# Enabling HTTPS

To serve the API over HTTPS instead of HTTP, you need SSL/TLS certificates. The server supports HTTPS via environment variables.

## Steps to Enable HTTPS:

1. **Obtain SSL Certificates:**
   
   You have several options:
   
   **Option A: Use Let's Encrypt (Recommended for Production)**
   ```bash
   # Install certbot
   sudo apt-get update
   sudo apt-get install certbot
   
   # Obtain certificates (replace your-domain.com with your actual domain)
   sudo certbot certonly --standalone -d your-domain.com
   ```
   
   This creates certificates at:
   - Certificate: `/etc/letsencrypt/live/your-domain.com/fullchain.pem`
   - Private Key: `/etc/letsencrypt/live/your-domain.com/privkey.pem`

   **Option B: Use Self-Signed Certificates (For Testing/Development)**
   ```bash
   # Generate self-signed certificate (valid for 365 days)
   openssl req -x509 -newkey rsa:4096 -nodes \
     -out cert.pem -keyout key.pem \
     -days 365 -subj "/CN=your-domain.com"
   ```

   **Option C: Use Existing Certificates**
   - Ensure you have a certificate file (`.pem`, `.crt`, or `.cert`)
   - Ensure you have the corresponding private key file (`.pem`, `.key`)

2. **Set Environment Variables:**
   
   Add to your `.env` file or export in your shell:
   ```bash
   export SSL_CERTFILE="/path/to/your/certificate.pem"
   export SSL_KEYFILE="/path/to/your/private-key.pem"
   export SERVER_PORT="443"  # Optional: default HTTPS port (or use 8080)
   ```

   Or add to `.env`:
   ```
   SSL_CERTFILE=/etc/letsencrypt/live/your-domain.com/fullchain.pem
   SSL_KEYFILE=/etc/letsencrypt/live/your-domain.com/privkey.pem
   SERVER_PORT=443
   ```

3. **Start the Server:**
   
   ```bash
   python3 llm-wrapper.py
   ```
   
   The server will detect the SSL certificates and start in HTTPS mode. You should see:
   ```
   Starting HTTPS server on 0.0.0.0:443
   SSL Certificate: /path/to/certificate.pem
   SSL Key: /path/to/private-key.pem
   ```

4. **Update Your API URLs:**
   
   Change your API endpoint from `http://` to `https://`:
   ```
   API URL: https://your-domain.com:443/v1
   ```

## Additional Considerations:

- **Firewall:** Ensure port 443 (or your chosen HTTPS port) is open in your firewall
- **Certificate Permissions:** Ensure the certificate files are readable by the process running the server
- **Certificate Renewal:** Let's Encrypt certificates expire every 90 days. Set up automatic renewal:
  ```bash
  # Add to crontab (runs twice daily)
  0 0,12 * * * certbot renew --quiet --deploy-hook "systemctl reload your-service"
  ```
- **Reverse Proxy:** For production, consider using a reverse proxy (nginx, Apache) with SSL termination instead of running SSL directly in uvicorn. This provides better performance and security features.

# Parallel Monitor Setup

This repo supports creating and managing Parallel Monitors to track web updates on topics you care about.

## Web UI (Recommended)

The easiest way to create a monitor is through the web interface:

1. Navigate to `http://your-server/create-monitor` in your browser
2. Enter your authentication token
3. Specify the topic you want to monitor (in natural language)
4. Select the monitoring frequency (hourly, daily, or weekly)
5. Click "Create Monitor"

The monitor will be automatically registered and associated with your username.

## Command Line (Offline Setup)

Alternatively, you can use the command-line script:

1. Export your API key:
`export PARALLEL_API_KEY="..."`

2. Create a monitor:

`python3 monitor/create_monitor.py --username "<username>" --query "Extract recent news about quantum in AI" --cadence daily --webhook_url "https://YOUR_DOMAIN/webhooks/parallel-monitor" --event_types "monitor.event.detected"`

## Configuration

### Webhook URL

The webhook URL is configurable via environment variable. Set it in your `.env` file or export it:

```bash
export MONITOR_WEBHOOK_URL="https://your-domain.com/webhooks/parallel-monitor"
```

If not set, it defaults to: `https://knowledge.learnwitharobot.com/webhooks/parallel-monitor`

### Querying Monitor Updates

Once monitors are set up, you can query for updates using the chat completions endpoint with:
- Model: `"speed"`
- Messages containing update-related keywords (e.g., "What are the latest updates?", "Show me recent news")

Example:
```bash
curl -X POST "http://your-server/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "speed",
    "messages": [{"role": "user", "content": "What are the latest updates?"}],
    "stream": true
  }'
```

For more details, see: https://docs.parallel.ai/monitor-api/monitor-quickstart

# Notes

1. config.json is set up with two providers: XAI and Perplexity Sonar. If you want to use one provider, just delete teh corresponding lines. Commenting out doesn't work in a json file
2. To make the server work in the background, the easiest way is to use nohup. So you can do:
   `nohup python3 llm-wrapper.py&`
and the server starts in the background and output is directed to nohup.out. This will ensure that the server keeps running even after you terminate your shell.
3. In some systems, load_dotenv() does not load from the .env file because it is usable to find the correct location of the .env file. If you run into an error where the script is unable to locate the API keys, it implies that the .env is not locaded correctly. Specify the exact file path to the .env file in load_dotenv(). e.g.
`load_dotenv("/home/amitabha/llm-wrapper/.env`
4. Another alternative is to create a service file and use:
   `systemctl start <service name>`
to start the service.

# Use case: Wirepod server for Vector robot

The Wirepod server for the Vector robot uses LLMs to answer questions that you ask to the Vector robot. In essence, the LLM serves as a knowledge bank. You can use the following screenshot as a reference on how to make Wirepod connect to the llm-wrapper for making inference calls.The following screenshot can be used for reference. Note: Use the token created in Step 4 as the API Key.
![Wirepod-use case](https://github.com/user-attachments/assets/f5dd3bde-3974-4a69-bd13-ae4ee8c2a818)

Now, you can ask Vector about news, and get a response from him. An example is available at: https://youtu.be/FTCZbYjh3oc

