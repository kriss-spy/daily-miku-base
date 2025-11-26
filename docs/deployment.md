# Deployment Guide

## Overview

daily-miku-base is deployed using:

- **Vercel** — Frontend + Python API backend
- **GitHub Actions** — Daily scheduled tasks (email, fetch)
- **Raindrop.io CDN** — Image hosting (no local storage)
- **Namecheap DNS** — Domain management for `dailymiku.dev`

## Prerequisites

- GitHub repository pushed and up-to-date
- Vercel account (free tier is sufficient)
- Domain `dailymiku.dev` registered on Namecheap
- Raindrop.io test token

## 1. Vercel Setup

### Connect Repository

1. Go to [vercel.com](https://vercel.com) and sign in
2. Click "Add New Project"
3. Import your GitHub repository: `kriss-spy/daily-miku-base`
4. Configure project settings:
   - **Framework Preset**: Other (or Python if available)
   - **Root Directory**: `./`
   - **Build Command**: Leave empty (no build needed for API-only)
   - **Output Directory**: Leave empty

### Configure Python Runtime

Create `vercel.json` in project root:

```json
{
  "builds": [
    {
      "src": "api/**/*.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "/api/$1"
    },
    {
      "src": "/(.*)",
      "dest": "/api/index.py"
    }
  ]
}
```

### Set Environment Variables

In Vercel dashboard → Project Settings → Environment Variables:

```
RAINDROP_TOKEN=your_raindrop_token_here
RAINDROP_TAG=daily-miku
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@example.com
```

### Deploy

```bash
# Install Vercel CLI (optional, for local testing)
npm install -g vercel

# Deploy from CLI
vercel --prod

# Or push to GitHub main branch (auto-deploys)
git push origin main
```

## 2. Domain Configuration

### Namecheap DNS Setup

1. Log into Namecheap
2. Go to Domain List → `dailymiku.dev` → Manage
3. Navigate to "Advanced DNS" tab
4. Add/update DNS records:

**For Vercel:**

```
Type: CNAME
Host: @
Value: cname.vercel-dns.com.
TTL: Automatic

Type: CNAME
Host: www
Value: cname.vercel-dns.com.
TTL: Automatic
```

### Vercel Domain Setup

1. In Vercel project dashboard → Settings → Domains
2. Add domain: `dailymiku.dev`
3. Add domain: `www.dailymiku.dev` (optional)
4. Vercel will verify DNS configuration
5. SSL certificate is provisioned automatically (Let's Encrypt)

**DNS propagation** takes 5-60 minutes.

## 3. API Structure

Organize your Python API in the `api/` directory:

```
api/
├── index.py          # Main entry point (routes)
├── raindrop.py       # Raindrop API client
├── utils.py          # Helper functions
└── requirements.txt  # Dependencies
```

**Example `api/index.py`**:

```python
from http.server import BaseHTTPRequestHandler
from datetime import datetime
import json
from .raindrop import get_daily_miku

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        
        # Route: /image/YYYY-MM-DD
        if path.startswith('/image/'):
            date = path.split('/')[2]
            return self.serve_image(date)
        
        # Route: /api/image/YYYY-MM-DD
        elif path.startswith('/api/image/'):
            date = path.split('/')[3]
            return self.serve_json(date)
        
        # Route: / or /YYYY-MM-DD
        else:
            return self.serve_html(path)
    
    def serve_image(self, date):
        # Redirect to Raindrop CDN URL
        data = get_daily_miku(date)
        if data:
            self.send_response(307)
            self.send_header('Location', data['imageUrl'])
            self.end_headers()
        else:
            self.send_error(404, 'Image not found')
    
    def serve_json(self, date):
        data = get_daily_miku(date)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
```

**Create `api/requirements.txt`**:

```
requests>=2.31.0
python-dotenv>=1.0.0
```

## 4. GitHub Actions (Daily Tasks)

Create `.github/workflows/daily-email.yml`:

```yaml
name: daily-miku-base Email

on:
  schedule:
    - cron: '0 8 * * *'  # 8 AM UTC daily
  workflow_dispatch:  # Manual trigger

jobs:
  send-email:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install requests python-dotenv
      
      - name: Send daily email
        env:
          RAINDROP_TOKEN: ${{ secrets.RAINDROP_TOKEN }}
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
          EMAIL_TO: ${{ secrets.EMAIL_TO }}
        run: |
          python -m src.daily_miku.main send-email
```

**Add secrets** in GitHub repo → Settings → Secrets and variables → Actions:

- `RAINDROP_TOKEN`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
- `EMAIL_FROM`, `EMAIL_TO`

## 5. Testing Deployment

### Test API Endpoints

```bash
# Test JSON API
curl https://dailymiku.dev/api/image/2025-11-26

# Test image redirect
curl -I https://dailymiku.dev/image/2025-11-26

# Test web page
curl https://dailymiku.dev/2025-11-26
```

### Test GitHub Action

1. Go to GitHub repo → Actions tab
2. Select "daily-miku-base Email" workflow
3. Click "Run workflow" → "Run workflow" (manual trigger)
4. Check email delivery

## 6. Monitoring & Logs

### Vercel Logs

- Dashboard → Project → Deployments → Click deployment → Function Logs
- View real-time logs for API requests

### GitHub Actions Logs

- Repo → Actions → Click workflow run → View logs

### Uptime Monitoring (Optional)

Use a service like:

- **UptimeRobot** (free, checks every 5 min)
- **Better Uptime**
- **Cronitor**

Add monitor for: `https://dailymiku.dev/api/image/today`

## 7. Performance Optimization

### Caching

Add cache headers in API responses:

```python
self.send_header('Cache-Control', 'public, max-age=86400')  # 24 hours
```

### CDN

Vercel automatically uses CDN for static assets and API responses.

### Rate Limiting

Implement rate limiting to protect Raindrop.io API:

```python
from functools import lru_cache
from datetime import datetime

@lru_cache(maxsize=100)
def get_daily_miku(date: str):
    # Cached for lifetime of function
    pass
```

## 8. Rollback & Recovery

### Rollback Deployment

In Vercel dashboard:

1. Go to Deployments
2. Find previous working deployment
3. Click "..." → "Promote to Production"

### Backup

- **Code**: Stored in GitHub (already backed up)
- **Images**: Stored on Raindrop.io CDN
- **Environment variables**: Export from Vercel settings periodically

## Troubleshooting

**"Function invocation failed"**:

- Check Vercel function logs
- Verify environment variables are set
- Check Python dependencies in `api/requirements.txt`

**Domain not resolving**:

- Verify DNS records in Namecheap
- Wait for DNS propagation (up to 48 hours, usually <1 hour)
- Use `dig dailymiku.dev` to check DNS

**Images not loading**:

- Check Raindrop.io API is accessible
- Verify `RAINDROP_TOKEN` is valid
- Check if bookmarks are tagged correctly

**GitHub Action fails**:

- Check secrets are configured in repo settings
- Verify Python script runs locally first
- Check action logs for specific error messages

## Cost Estimate

- **Vercel**: Free tier (100GB bandwidth, 100 hours function time)
- **GitHub Actions**: Free tier (2,000 minutes/month)
- **Domain**: $10-15/year (Namecheap)
- **Raindrop.io**: Free tier (permanent copy requires PRO: $28/year)

**Total**: ~$0-1/month (assuming free tiers sufficient)
