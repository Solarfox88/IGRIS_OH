"""Setup and utility script for Vast.ai GPU integration."""

from __future__ import annotations

import json
import subprocess
import sys


def check_vastai_cli() -> bool:
    try:
        result = subprocess.run(
            ["vastai", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def install_vastai_cli() -> bool:
    print("Installing Vast.ai CLI...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "vastai"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Installation failed: {e}")
        return False


def search_gpu_offers(gpu_type: str = "RTX_4090", max_cost: float = 0.50) -> list[dict]:
    """Search for available GPU instances on Vast.ai."""
    try:
        result = subprocess.run(
            [
                "vastai", "search", "offers",
                f"gpu_name={gpu_type}",
                f"dph<={max_cost}",
                "reliability>0.95",
                "inet_down>200",
                "--raw",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f"Search failed: {e}")
    return []


def rent_instance(
    offer_id: int,
    image: str = "pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime",
) -> int | None:
    """Rent a GPU instance. Returns instance ID."""
    try:
        result = subprocess.run(
            [
                "vastai", "create", "instance",
                str(offer_id),
                "--image", image,
                "--raw",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("new_contract")
    except Exception as e:
        print(f"Rent failed: {e}")
    return None


def destroy_instance(instance_id: int) -> bool:
    """Destroy a GPU instance."""
    try:
        result = subprocess.run(
            ["vastai", "destroy", "instance", str(instance_id)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def setup() -> None:
    print("=" * 60)
    print("  IGRIS - Vast.ai GPU Setup")
    print("=" * 60)
    print()
    print("Vast.ai provides on-demand GPU access for heavy computation.")
    print("RTX 4090 instances are available from ~$0.30/h")
    print()

    if check_vastai_cli():
        print("[OK] Vast.ai CLI installed")
    else:
        if install_vastai_cli():
            print("[OK] Vast.ai CLI installed")
        else:
            print("[!] Install manually: pip install vastai")

    print()
    print("Next steps:")
    print("1. Create account at https://vast.ai")
    print("2. Get API key from https://vast.ai/console/account/")
    print("3. Run: vastai set api-key YOUR_KEY")
    print("4. Add key to .igris/config.json under vastai.api_key")
    print()
    print("IGRIS will automatically rent RTX 4090 for heavy tasks")
    print("and destroy instances when done to minimize cost.")


if __name__ == "__main__":
    setup()
