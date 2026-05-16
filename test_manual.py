#!/usr/bin/env python3
"""Test Namecheap with manual client creation"""

import os
from dotenv import load_dotenv
from namecheap import NamecheapClient

load_dotenv()

# Create client manually
nc = NamecheapClient(
    api_user=os.getenv("NAMECHEAP_API_USER"),
    api_key=os.getenv("NAMECHEAP_API_KEY"),
    username=os.getenv("NAMECHEAP_USERNAME"),
    client_ip=os.getenv("NAMECHEAP_CLIENT_IP"),
    sandbox=False,
    debug=True,
)

print("Testing API connection...")
print()

try:
    domains = nc.domains.get_list()
    print(f"✅ Success! Found {len(domains)} domain(s):")
    for domain in domains:
        print(f"  - {domain}")
except Exception as e:
    print(f"❌ Error: {e}")
