"""Ponto de entrada do DaikinSmartAC.exe.

    DaikinSmartAC.exe                -> ícone na bandeja + painel
    DaikinSmartAC.exe --inicio       -> só o ícone (ao ligar o Windows)
    DaikinSmartAC.exe --janela       -> janela completa
    DaikinSmartAC.exe --configurar   -> assistente de configuração
    DaikinSmartAC.exe --cli status   -> comandos de daikin_ac.py
"""

import sys


def main() -> None:
    args = sys.argv[1:]
    if "--configurar" in args:
        from app_assistente import main as abrir
        abrir()
    elif "--janela" in args:
        from app_janela import main as abrir
        abrir()
    elif "--cli" in args:
        from daikin_ac import main as cli
        sys.exit(cli(args[args.index("--cli") + 1:]))
    else:
        from app_bandeja import main as abrir
        abrir(args)


if __name__ == "__main__":
    main()
