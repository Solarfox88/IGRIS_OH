"""Setup script for Ollama (local LLM)."""

from __future__ import annotations

import platform
import subprocess
import sys


def check_ollama_installed() -> bool:
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def install_ollama() -> bool:
    system = platform.system()
    print(f"Installing Ollama on {system}...")

    if system == "Windows":
        print("Download Ollama from: https://ollama.com/download/windows")
        print("Or run: winget install Ollama.Ollama")
        return False
    elif system == "Linux":
        try:
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                timeout=120,
            )
            return result.returncode == 0
        except Exception as e:
            print(f"Installation failed: {e}")
            return False
    elif system == "Darwin":
        print("Download Ollama from: https://ollama.com/download/mac")
        print("Or run: brew install ollama")
        return False
    return False


def pull_model(model: str = "phi4-mini") -> bool:
    print(f"Pulling model: {model}...")
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            timeout=600,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Failed to pull model: {e}")
        return False


RECOMMENDED_MODELS = {
    "phi4-mini": {
        "size": "n/a",
        "description": "Default consigliato: leggero con buon ragionamento",
        "recommended": True,
    },
    "mistral": {
        "size": "4.1 GB",
        "description": "Alternativa bilanciata per i5 + 16GB RAM",
        "recommended": True,
    },
    "codellama:7b": {
        "size": "3.8 GB",
        "description": "Specialized for code generation",
        "recommended": True,
    },
    "llama3.2:3b": {
        "size": "2.0 GB",
        "description": "Fastest option, good for simple tasks",
        "recommended": False,
    },
    "deepseek-coder:6.7b": {
        "size": "3.8 GB",
        "description": "Strong coding model",
        "recommended": False,
    },
    "phi3:mini": {
        "size": "2.3 GB",
        "description": "Microsoft Phi-3, good reasoning",
        "recommended": False,
    },
    "qwen2.5-coder:7b": {
        "size": "4.7 GB",
        "description": "Alibaba coding model, strong performance",
        "recommended": True,
    },
}


def setup() -> None:
    print("=" * 60)
    print("  IGRIS - Ollama Setup")
    print("=" * 60)
    print()

    if check_ollama_installed():
        print("[OK] Ollama is installed")
    else:
        print("[!] Ollama not found")
        if not install_ollama():
            print("\nPlease install Ollama manually:")
            print("  https://ollama.com/download")
            sys.exit(1)

    print("\nRecommended models for your hardware (i5-1035G1 + 16GB RAM):")
    print()
    for name, info in RECOMMENDED_MODELS.items():
        rec = " [RECOMMENDED]" if info["recommended"] else ""
        print(f"  {name:25s} {info['size']:8s}  {info['description']}{rec}")

    print("\nPulling recommended models...")
    for model in ["phi4-mini", "mistral", "qwen2.5-coder:7b"]:
        if pull_model(model):
            print(f"  [OK] {model}")
        else:
            print(f"  [FAIL] {model}")

    print("\nSetup complete! Start Ollama with: ollama serve")


if __name__ == "__main__":
    setup()
