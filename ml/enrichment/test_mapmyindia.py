import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()
STATIC_KEY = os.getenv("MAPPLS_STATIC_KEY")
if not STATIC_KEY:
    raise ValueError("MAPPLS_STATIC_KEY missing in .env")

LAT, LNG = 12.9716, 77.5946

def reverse_geocode():
    url = "https://search.mappls.com/search/address/rev-geocode"
    params = {"lat": LAT, "lng": LNG, "access_token": STATIC_KEY}
    r = httpx.get(url, params=params, timeout=20)
    print("\nReverse Geocode:", r.status_code)
    print(r.text[:1000])
    return r

def nearby():
    url = "https://search.mappls.com/search/places/nearby/json"
    params = {
        "keywords": "bus stop",
        "refLocation": f"{LAT},{LNG}",
        "radius": 1000,
        "region": "IND",
        "sortBy": "dist:asc",
        "page": 1,
        "access_token": STATIC_KEY,
    }
    r = httpx.get(url, params=params, timeout=20)
    print("\nNearby:", r.status_code)
    print(r.text[:1000])
    return r

if __name__ == "__main__":
    reverse_geocode()
    nearby()