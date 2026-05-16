#!/usr/bin/env python3
"""Test Namecheap API connection"""

import os
from dotenv import load_dotenv
from namecheap import NamecheapClient

# Load environment variables
load_dotenv()


def test_connection():
    """Test Namecheap API connection"""
    try:
        # Initialize Namecheap client (must use NamecheapClient directly)
        nc = NamecheapClient(
            api_user=os.getenv("NAMECHEAP_API_USER"),
            api_key=os.getenv("NAMECHEAP_API_KEY"),
            username=os.getenv("NAMECHEAP_USERNAME"),
            client_ip=os.getenv("NAMECHEAP_CLIENT_IP"),
            sandbox=False,  # Production mode
        )

        print("✅ Namecheap client initialized")
        print(f"   Username: {os.getenv('NAMECHEAP_USERNAME')}")
        print(f"   Client IP: {os.getenv('NAMECHEAP_CLIENT_IP')}")
        print(f"   Sandbox mode: False")
        print()

        # Test API by listing domains
        print("🔍 Fetching your domains...")
        result = nc.domains.get_list()
        domains = result.get("domains", [])

        if domains:
            print(f"✅ Successfully connected! Found {len(domains)} domain(s):")
            print()
            for domain in domains:
                print(f"📌 {domain['Name']}")
                print(f"   Created: {domain['Created'].strftime('%Y-%m-%d')}")
                print(f"   Expires: {domain['Expires'].strftime('%Y-%m-%d')}")
                print(f"   Auto-renew: {domain['AutoRenew']}")
                print(f"   WhoisGuard: {domain['WhoisGuard']}")
                print()
        else:
            print("✅ Successfully connected! No domains found in your account.")

        return True

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print()
        print("💡 Troubleshooting tips:")
        print("   1. Verify your API key is correct")
        print("   2. Check that your IP (139.180.216.187) is whitelisted")
        print("   3. Ensure API access is enabled in your Namecheap account")
        print("   4. Visit: https://ap.www.namecheap.com/settings/tools/apiaccess/")
        return False


if __name__ == "__main__":
    test_connection()
