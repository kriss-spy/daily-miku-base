#!/usr/bin/env python3
"""
Configure Namecheap DNS for Vercel deployment
Sets up dailymiku.dev to point to daily-miku-base.vercel.app
"""

import os
from dotenv import load_dotenv
from namecheap import NamecheapClient

# Load environment variables
load_dotenv()


def setup_vercel_dns():
    """Configure DNS records for Vercel"""

    # Initialize Namecheap client
    nc = NamecheapClient(
        api_user=os.getenv("NAMECHEAP_API_USER"),
        api_key=os.getenv("NAMECHEAP_API_KEY"),
        username=os.getenv("NAMECHEAP_USERNAME"),
        client_ip=os.getenv("NAMECHEAP_CLIENT_IP"),
        sandbox=False,  # Production mode
    )

    domain = "dailymiku.dev"

    print(f"🔍 Checking current DNS records for {domain}...")
    try:
        current_records = nc.domains.dns.get_hosts(domain)
        print("\n📋 Current DNS Records:")
        for record in current_records:
            rec_type = record.get("Type", record.get("@Type", "?"))
            rec_name = record.get("Name", record.get("@Name", "?"))
            rec_addr = record.get("Address", record.get("@Address", "?"))
            print(f"  {rec_type:6} {rec_name:15} → {rec_addr}")
    except Exception as e:
        print(f"⚠️  Could not fetch current records: {e}")
        current_records = []

    print("\n🔧 Configuring DNS for Vercel...")
    print(f"   Domain: {domain}")
    print("   Target: cname.vercel-dns.com")

    # Configure DNS for Vercel
    # Vercel requires:
    # - A record for apex domain: 76.76.21.21
    # - CNAME for www: cname.vercel-dns.com
    hosts = [
        {"HostName": "@", "RecordType": "A", "Address": "76.76.21.21", "TTL": "1799"},
        {
            "HostName": "www",
            "RecordType": "CNAME",
            "Address": "cname.vercel-dns.com",
            "TTL": "1799",
        },
    ]

    try:
        nc.domains.dns.set_hosts(domain, hosts)
        print("\n✅ DNS records updated successfully!")
        print("\n📝 New DNS Configuration:")
        print("  A      @               → 76.76.21.21")
        print("  CNAME  www             → cname.vercel-dns.com")

        print("\n⏳ DNS propagation can take 5-30 minutes")
        print(f"   You can check status with: dig {domain}")
        print("\n🎯 Next Steps:")
        print("   1. Wait for DNS propagation")
        print("   2. Verify in Vercel dashboard that the domain is active")
        print(f"   3. Test: https://{domain}")

    except Exception as e:
        print(f"\n❌ Error updating DNS: {e}")
        print("\n💡 Manual Setup Instructions:")
        print(
            f"   1. Go to Namecheap dashboard: https://ap.www.namecheap.com/domains/domaincontrolpanel/{domain}"
        )
        print("   2. Set A record: @ → 76.76.21.21")
        print("   3. Set CNAME record: www → cname.vercel-dns.com")
        return False

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Vercel DNS Configuration for dailymiku.dev")
    print("=" * 60)

    success = setup_vercel_dns()

    if success:
        print("\n" + "=" * 60)
        print("✨ Configuration complete!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("⚠️  Please configure DNS manually")
        print("=" * 60)
