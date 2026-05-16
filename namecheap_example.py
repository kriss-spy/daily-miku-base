#!/usr/bin/env python3
"""Namecheap API - Working Example"""

import os
from dotenv import load_dotenv
from namecheap import NamecheapClient

# Load environment variables
load_dotenv()

# Create client (must use NamecheapClient directly, not create_client_from_env)
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

# Get domain list
print("📋 Your Domains:")
print("-" * 60)

try:
    result = nc.domains.get_list()
    domains = result.get("domains", [])

    if domains:
        for domain in domains:
            print(f"🌐 {domain['Name']}")
            print(f"   Expires: {domain['Expires'].strftime('%Y-%m-%d')}")
            print(f"   Auto-renew: {domain['AutoRenew']}")
            print(f"   WhoisGuard: {domain['WhoisGuard']}")
            print()

        print(f"Total: {len(domains)} domain(s)")
    else:
        print("No domains found.")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback

    traceback.print_exc()

# Example: Check domain availability
print()
print("-" * 60)
print("🔍 Example: Check Domain Availability")
print("-" * 60)

try:
    check_result = nc.domains.check("example-test-12345.com")
    domains_checked = check_result.get("domains", [])

    for domain in domains_checked:
        status = "✅ Available" if domain["available"] else "❌ Taken"
        print(f"{status}: {domain['domain']}")

except Exception as e:
    print(f"❌ Error: {e}")

# Example: Get DNS records for a domain
print()
print("-" * 60)
print("🌐 Example: DNS Records for dailymiku.dev")
print("-" * 60)

try:
    dns_records = nc.dns.get("dailymiku.dev")

    if dns_records:
        for record in dns_records:
            print(
                f"{record.get('Type', 'N/A'):6} {record.get('Name', '@'):20} → {record.get('Address', 'N/A')}"
            )
    else:
        print("No DNS records found or error retrieving records")

except Exception as e:
    print(f"❌ Error: {e}")

print()
print("=" * 60)
print("Setup complete! You can now use the Namecheap API.")
print("=" * 60)
