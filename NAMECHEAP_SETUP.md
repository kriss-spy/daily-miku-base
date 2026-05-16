# Namecheap API Setup - Complete

## ✅ Installation Complete

The `namecheap-python` package has been installed and configured successfully!

## 📝 Configuration

Your credentials are stored in `.env`:

```bash
NAMECHEAP_API_KEY=89af0d7d31cb412da7de4b661b492047
NAMECHEAP_USERNAME=k39spy
NAMECHEAP_API_USER=k39spy
NAMECHEAP_CLIENT_IP=139.180.216.187
```

## 🚀 Quick Start

### Basic Usage

```python
import os
from dotenv import load_dotenv
from namecheap import NamecheapClient

# Load credentials
load_dotenv()

# Create client
nc = NamecheapClient(
    api_user=os.getenv("NAMECHEAP_API_USER"),
    api_key=os.getenv("NAMECHEAP_API_KEY"),
    username=os.getenv("NAMECHEAP_USERNAME"),
    client_ip=os.getenv("NAMECHEAP_CLIENT_IP"),
    sandbox=False  # Use production API
)

# List domains
result = nc.domains.get_list()
for domain in result['domains']:
    print(f"{domain['Name']} - expires {domain['Expires']}")
```

### Check Domain Availability

```python
result = nc.domains.check(["example.com", "coolsite.io"])
for domain in result:
    if domain['available']:
        print(f"✅ {domain['domain']} is available!")
```

### Get Domain Info

```python
info = nc.domains.get_info("dailymiku.dev")
print(info)
```

## 📁 Example Files

- `namecheap_quickstart.py` - Simple example showing your domains
- `namecheap_example.py` - More comprehensive examples
- `test_direct.py` - Direct API test (no library wrapper)

Run the quickstart:
```bash
source .venv/bin/activate && python namecheap_quickstart.py
```

## 🌐 Your Domains

You currently have 2 domains:

1. **bridge39.online**
   - Expires: 2026-09-13
   - Auto-renew: Enabled
   - WhoisGuard: Enabled

2. **dailymiku.dev**
   - Expires: 2026-11-26
   - Auto-renew: Disabled ⚠️
   - WhoisGuard: Enabled

## ⚠️ Important Notes

1. **Use NamecheapClient directly** - Don't use `create_client_from_env()`, it has issues with sandbox mode detection

2. **Username is lowercase** - Make sure to use `k39spy` not `K39spy`

3. **IP Whitelisting** - Your VPN IP (139.180.216.187) is whitelisted. If your VPN changes, update it at:
   https://ap.www.namecheap.com/settings/tools/apiaccess/

4. **Production vs Sandbox** - Always set `sandbox=False` for real operations

## 📚 Resources

- [Namecheap API Documentation](https://www.namecheap.com/support/api/intro/)
- [namecheap-python GitHub](https://github.com/adriangalilea/namecheap-python)
- [Your API Settings](https://ap.www.namecheap.com/settings/tools/apiaccess/)

## 🔧 Troubleshooting

If you get "API Key is invalid" errors:
1. Check that API access is ON in Namecheap settings
2. Verify your IP (139.180.216.187) is whitelisted
3. Make sure you're using `sandbox=False`
4. Use `NamecheapClient` directly, not `create_client_from_env()`
