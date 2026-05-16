#!/usr/bin/env python3
"""Namecheap API - Quick Start Example"""

import os
from dotenv import load_dotenv
from namecheap import NamecheapClient

# Load environment variables
load_dotenv()

# Create client
nc = NamecheapClient(
    api_user=os.getenv("NAMECHEAP_API_USER"),
    api_key=os.getenv("NAMECHEAP_API_KEY"),
    username=os.getenv("NAMECHEAP_USERNAME"),
    client_ip=os.getenv("NAMECHEAP_CLIENT_IP"),
    sandbox=False,  # Production mode
)

print("✅ Connected to Namecheap API!")
print(f"   Username: {os.getenv('NAMECHEAP_USERNAME')}")
print(f"   Client IP: {os.getenv('NAMECHEAP_CLIENT_IP')}")
print()

# List your domains
print("📋 Your Domains:")
print("-" * 60)

result = nc.domains.get_list()
domains = result.get("domains", [])

for domain in domains:
    print(f"🌐 {domain['Name']}")
    print(f"   Expires: {domain['Expires'].strftime('%Y-%m-%d')}")
    print(f"   Auto-renew: {domain['AutoRenew']}")
    print(f"   WhoisGuard: {domain['WhoisGuard']}")
    print()

print(f"Total: {len(domains)} domain(s)")
print()
print("=" * 60)
print("✅ Setup complete! You can now use the Namecheap API.")
print("=" * 60)
