#!/usr/bin/env python3
"""Direct Namecheap API test with debugging"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Get credentials
api_key = os.getenv("NAMECHEAP_API_KEY")
username = os.getenv("NAMECHEAP_USERNAME")
api_user = os.getenv("NAMECHEAP_API_USER")
client_ip = os.getenv("NAMECHEAP_CLIENT_IP")

print("=" * 60)
print("CREDENTIALS CHECK")
print("=" * 60)
print(f"API Key: {api_key[:10]}...{api_key[-10:]}")
print(f"Username: {username}")
print(f"API User: {api_user}")
print(f"Client IP: {client_ip}")
print()

# Make direct API call
url = "https://api.namecheap.com/xml.response"
params = {
    "ApiUser": api_user,
    "ApiKey": api_key,
    "UserName": username,
    "ClientIp": client_ip,
    "Command": "namecheap.domains.getList",
}

print("=" * 60)
print("MAKING API REQUEST")
print("=" * 60)
print(f"URL: {url}")
print(f"Command: {params['Command']}")
print()

response = requests.get(url, params=params)

print("=" * 60)
print("RESPONSE")
print("=" * 60)
print(f"Status Code: {response.status_code}")
print(f"Response:\n{response.text}")
