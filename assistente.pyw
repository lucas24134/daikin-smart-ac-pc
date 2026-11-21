"""Abre o assistente de configuração do Daikin Smart AC (sem janela de console)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_assistente import main  # noqa: E402

main()
