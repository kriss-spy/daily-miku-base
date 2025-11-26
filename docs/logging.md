# Structured Logging & Error Handling

## Overview

The daily-miku-base API includes comprehensive structured logging and error handling to help with monitoring, debugging, and production observability.

## Features

### 1. JSON Structured Logging

All logs are output as JSON for easy parsing and ingestion into log management systems (ELK stack, Datadog, etc.).

**Example log output:**

```json
{
  "timestamp": "2025-11-26T14:30:45.123456+00:00",
  "level": "INFO",
  "logger": "daily_miku",
  "message": "Request started",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "method": "GET",
  "path": "/api/today",
  "client": "192.168.1.1"
}
```

### 2. Request Tracking

Every HTTP request gets a unique request ID for tracing across logs and responses. This helps correlate errors with user requests.

**Middleware tracking:**

- Request start: logs method, path, client IP, and request ID
- Request completion: logs status code
- Request errors: captures exception type and details

### 3. Enhanced Error Responses

Error responses now include:

- `detail`: The error message
- `request_id`: Unique request ID for debugging
- `path`: The requested path
- `error_type`: Type of exception (for unhandled errors)

**Example error response:**

```json
{
  "detail": "No daily miku found for 2025-12-31",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "path": "/api/image/2025-12-31"
}
```

### 4. API Endpoint Logging

Key endpoints log important events:

- Cache hits/misses for Raindrop API
- Successful image retrievals
- API failures and errors

## Configuration

### Log Level

Set the log level via the `LOG_LEVEL` environment variable (default: `INFO`):

```bash
export LOG_LEVEL=DEBUG   # For verbose logging during development
export LOG_LEVEL=WARNING # For production (less noise)
```

Supported levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### Log Output

Logs are written to stdout and can be captured by container orchestration systems (Docker, Kubernetes).

**Local development:**

```bash
python -m uvicorn src.daily_miku.server:app --reload
```

Logs will appear in the terminal as formatted JSON.

**Docker:**

```bash
docker run -e LOG_LEVEL=INFO daily-miku-api
```

## Request ID Usage

Request IDs appear in:

1. **All logs** for that request
2. **Error responses** for tracing
3. **HTTP headers** (X-Request-ID) - can be added in middleware if needed

**Example debugging workflow:**

```bash
# See a request ID in an error response
curl https://www.dailymiku.dev/api/image/2025-12-31
# Response: {"detail": "...", "request_id": "550e8400-e29b-41d4-a716-446655440000"}

# Search logs for that request ID
# This shows all logs from that request: startup, API calls, response, etc.
grep "550e8400-e29b-41d4-a716-446655440000" logs.json
```

## Caching Logs

The Raindrop API client logs cache operations:

**Cache hit:**

```json
{
  "timestamp": "...",
  "level": "DEBUG",
  "message": "Cache hit for raindrops:daily-miku:50:0:-created",
  "request_id": "..."
}
```

**Cache miss (fetching from API):**

```json
{
  "timestamp": "...",
  "level": "DEBUG",
  "message": "Cache miss for raindrops:daily-miku:50:0:-created, fetching from API"
}
```

**Successful fetch:**

```json
{
  "timestamp": "...",
  "level": "INFO",
  "message": "Fetched 42 raindrops with tag 'daily-miku'",
  "request_id": "..."
}
```

## Integration with Log Management Systems

### Datadog

Configure Datadog agent to ingest JSON logs:

```yaml
logs:
  - type: file
    path: /var/log/app.log
    service: daily-miku
    source: python
    parser: json
```

### ELK Stack

Filebeat + Logstash will automatically parse JSON logs:

```yaml
filebeat.inputs:
- type: log
  enabled: true
  paths:
    - /var/log/app.log
  json.message_key: message
```

### CloudWatch

In AWS, container logs are automatically captured from stdout. CloudWatch Insights can query JSON fields:

```
fields timestamp, level, message, request_id
| filter level = "ERROR"
| stats count() by error_type
```

## Error Handling

### HTTP Exceptions

HTTP exceptions (e.g., 404, 422) include:

- Original error detail
- Request ID for tracing
- Path information

### Unhandled Exceptions

Unhandled exceptions are caught and return:

- Generic "Internal server error" message (security best practice)
- Request ID for debugging
- Error type for diagnostics
- Full exception logged server-side

**Example unhandled error response:**

```json
{
  "detail": "Internal server error",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "path": "/api/today",
  "error_type": "ValueError"
}
```

## Best Practices

1. **Always include request IDs in support tickets** - helps debugging
2. **Monitor ERROR level logs** - indicates issues needing attention
3. **Use DEBUG in development** - shows cache hits/misses and API calls
4. **Archive logs** - rotate and compress old logs after 30 days
5. **Alert on ERROR patterns** - set up monitoring for repeated errors

## Performance Considerations

- JSON formatting has minimal overhead (~2% per request)
- Request ID generation uses UUID (very fast)
- Logging to stdout doesn't block request processing
- No database writes for logs (stdout only)

## Future Enhancements

Possible additions:

- Log rotation and file archiving
- Metrics export (Prometheus `/metrics` endpoint)
- Error aggregation and alerting
- Request duration tracking
- Custom correlation IDs for distributed tracing
