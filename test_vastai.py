"""
Script di test standalone per verificare la connessione Vast.ai.
Esegui con: python test_vastai.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx

VAST_API_BASE = "https://console.vast.ai/api/v0"

# Leggi la chiave direttamente dal config.json
CONFIG_PATH = Path(".igris/config.json")


def get_api_key() -> str:
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        key = data.get("vastai", {}).get("api_key", "")
        if key:
            return key
    # Fallback a variabile d'ambiente
    import os
    return os.environ.get("VASTAI_API_KEY", os.environ.get("VAST_API_KEY", ""))


async def test_vastai_connection():
    api_key = get_api_key()

    if not api_key:
        print("❌ Vast.ai API key non trovata in .igris/config.json né in variabili d'ambiente")
        return

    print(f"✅ API key trovata: {api_key[:8]}...{api_key[-4:]}")
    params = {"api_key": api_key}
    print()

    # Test 1: autenticazione
    print("1️⃣  Test autenticazione...")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{VAST_API_BASE}/users/current/", params=params)
        if resp.status_code == 200:
            user = resp.json()
            balance = user.get("credit", user.get("balance", 0))
            print(f"   ✅ Autenticato come: {user.get('username', '?')} | Credito: ${float(balance):.2f}")
        else:
            print(f"   ❌ Auth fallita: {resp.status_code}")
            print(f"   Risposta: {resp.text[:300]}")
            return
    print()

    # Test 2: ricerca RTX 4090
    print("2️⃣  Ricerca offerte RTX 4090 (max $0.50/h)...")
    query = json.dumps({
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "gpu_name": {"eq": "RTX 4090"},
        "num_gpus": {"eq": 1},
        "static_ip": {"eq": True},
        "direct_port_count": {"gte": 1},
        "reliability2": {"gte": 0.95},
        "dph_total": {"lte": 0.50},
        "order": [["dph_total", "asc"]],
        "type": "on-demand",
    })
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{VAST_API_BASE}/bundles/", params={**params, "q": query})
        data = resp.json()
        offers = data.get("offers", [])
        if offers:
            print(f"   ✅ {len(offers)} offerte disponibili:")
            for o in offers[:5]:
                print(f"      id={o['id']} | ${o.get('dph_total', '?'):.3f}/h | {o.get('geolocation', '?')} | VRAM:{o.get('gpu_ram', '?')}GB")
        else:
            print(f"   ⚠️  Nessuna RTX 4090 trovata sotto $0.50/h")
            # Prova senza filtro prezzo
            q2 = json.dumps({"gpu_name": {"eq": "RTX 4090"}, "rentable": {"eq": True}, "order": [["dph_total", "asc"]]})
            resp2 = await client.get(f"{VAST_API_BASE}/bundles/", params={**params, "q": q2})
            d2 = resp2.json()
            o2 = d2.get("offers", [])
            if o2:
                print(f"   ℹ️  Prezzi attuali RTX 4090 (senza filtro budget):")
                for o in o2[:3]:
                    print(f"      ${o.get('dph_total', '?'):.3f}/h @ {o.get('geolocation', '?')}")
    print()

    # Test 3: istanze attive
    print("3️⃣  Istanze attive (costi in corso)...")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{VAST_API_BASE}/instances/", params={**params, "owner": "me"})
        data = resp.json()
        instances = data.get("instances", [])
        if instances:
            print(f"   ⚠️  {len(instances)} istanze attive (stai pagando!):")
            for i in instances:
                print(f"      id={i['id']} | {i.get('actual_status')} | ${i.get('dph_total', '?'):.3f}/h")
        else:
            print("   ✅ Nessuna istanza attiva — zero costi in corso")
    print()
    print("✅ Test completato!")


if __name__ == "__main__":
    asyncio.run(test_vastai_connection())
