"""Controle local do Daikin Smart AC (Brasil) pelo PC.

Usa a biblioteca oficial `pyiotdevice` (a mesma da integração Home Assistant
da Daikin Brasil) para falar com o ar-condicionado pela rede local:
HTTP na porta 15914, payload criptografado com AES usando a "Device Key"
obtida no app (Menu -> Integrações -> Home Assistant).

Uso rápido:
    python daikin_ac.py configurar --ip 192.168.0.50 --chave SUA_DEVICE_KEY
    python daikin_ac.py status
    python daikin_ac.py ligar
    python daikin_ac.py modo frio
    python daikin_ac.py temp 23
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from pyiotdevice import get_thing_info, send_operation_data
except ImportError:  # pragma: no cover - mensagem amigável
    sys.exit(
        "Biblioteca 'pyiotdevice' não encontrada.\n"
        "Instale com:  python -m pip install -r requirements.txt"
    )

# Rodando como DaikinSmartAC.exe (PyInstaller) ou como scripts Python?
CONGELADO = bool(getattr(sys, "frozen", False))
PASTA_APP = Path(sys.executable).resolve().parent if CONGELADO else Path(__file__).resolve().parent
if CONGELADO:
    # o .exe pode ficar em qualquer lugar; dados do usuário vão para %APPDATA%
    PASTA_DADOS = Path(os.environ.get("APPDATA", str(Path.home()))) / "DaikinSmartAC"
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
else:
    PASTA_DADOS = PASTA_APP
CONFIG_PATH = PASTA_DADOS / "config.json"
COMMAND_SUFFIX = "BZ"  # constante usada pela integração oficial
MDNS_SERVICE = "_iota._tcp.local."

# Valores do aparelho <-> nomes em português
MODOS = {"auto": 1, "seco": 2, "frio": 3, "calor": 4, "ventilar": 6}
MODOS_INV = {v: k for k, v in MODOS.items()}

VENTILADOR = {
    "auto": 17,
    "alto": 7,
    "medio_alto": 6,
    "medio": 5,
    "medio_baixo": 4,
    "baixo": 3,
    "silencioso": 18,
}
VENTILADOR_INV = {v: k for k, v in VENTILADOR.items()}

# Faixas de temperatura (°C) por modo, iguais às da integração oficial
FAIXA_TEMP = {"frio": (18, 32), "calor": (10, 30), "auto": (18, 30)}

PRESETS = ("nenhum", "eco", "turbo")


class DaikinError(Exception):
    """Erro de comunicação ou de uso."""


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------
def carregar_config() -> dict[str, Any]:
    cfg = ler_config_arquivo()
    # Variáveis de ambiente têm prioridade
    if os.environ.get("DAIKIN_IP"):
        cfg["ip"] = os.environ["DAIKIN_IP"]
    if os.environ.get("DAIKIN_CHAVE"):
        cfg["chave"] = os.environ["DAIKIN_CHAVE"]
    return cfg


def ler_config_arquivo() -> dict[str, Any]:
    """Lê config.json sem aplicar variáveis de ambiente."""
    if CONFIG_PATH.exists():
        try:
            dados = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def gravar_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def salvar_config(ip: str, chave: str) -> None:
    """Atualiza IP/chave preservando automações já salvas."""
    cfg = ler_config_arquivo()
    cfg.update({"ip": ip, "chave": chave})
    gravar_config(cfg)


# --------------------------------------------------------------------------
# Atalhos do Windows (Área de Trabalho e inicialização automática)
# --------------------------------------------------------------------------
NOME_ATALHO = "Daikin Smart AC.lnk"


def _pasta_especial(qual: str) -> Path:
    if qual == "inicializar":
        return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    # Área de Trabalho real (funciona mesmo se estiver no OneDrive)
    import ctypes

    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
    return Path(buf.value)


NOME_ATALHO_BANDEJA = "Daikin Smart AC (bandeja).lnk"


def caminho_atalho(qual: str, nome: str = NOME_ATALHO) -> Path:
    return _pasta_especial(qual) / nome


def _pythonw() -> str:
    exe = Path(sys.executable)
    candidato = exe.with_name("pythonw.exe")
    return str(candidato if candidato.exists() else exe)


def comando_app(modo: str = "bandeja") -> list[str]:
    """Linha de comando que abre um modo do app.

    bandeja    -> ícone + painel (abre o painel na hora)
    inicio     -> ícone + painel, escondido (usado ao ligar o Windows)
    janela     -> janela completa
    configurar -> assistente de configuração
    """
    flags = {"bandeja": [], "inicio": ["--inicio"], "janela": ["--janela"],
             "configurar": ["--configurar"]}[modo]
    if CONGELADO:
        return [sys.executable, *flags]
    script = {"janela": "daikin_gui.pyw", "configurar": "assistente.pyw"}.get(modo, "bandeja.pyw")
    extra = ["--inicio"] if modo == "inicio" else []
    return [_pythonw(), str(PASTA_APP / script), *extra]


def abrir_app(modo: str) -> None:
    import subprocess

    subprocess.Popen(comando_app(modo), cwd=str(PASTA_APP))


def criar_atalho(qual: str, modo: str = "bandeja", nome: str = NOME_ATALHO) -> Path:
    """Cria atalho do Windows que abre o app (sem janela de console)."""
    import subprocess

    cmd = comando_app(modo)
    destino = caminho_atalho(qual, nome)
    destino.parent.mkdir(parents=True, exist_ok=True)
    args = " ".join(f'"{a}"' for a in cmd[1:])
    icone = PASTA_APP / "daikin.ico"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:DK_LNK);"
        "$s.TargetPath=$env:DK_EXE;$s.Arguments=$env:DK_ARGS;"
        "$s.WorkingDirectory=$env:DK_DIR;$s.Description='Daikin Smart AC';"
        "if($env:DK_ICO){$s.IconLocation=$env:DK_ICO};$s.Save()"
    )
    env = dict(
        os.environ,
        DK_LNK=str(destino),
        DK_EXE=cmd[0],
        DK_ARGS=args,
        DK_DIR=str(PASTA_APP),
        DK_ICO="" if CONGELADO or not icone.exists() else str(icone),
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        check=True,
        creationflags=0x08000000,  # sem janela de console
    )
    return destino


def remover_atalho(qual: str, nome: str = NOME_ATALHO) -> None:
    try:
        caminho_atalho(qual, nome).unlink()
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------
class DaikinAC:
    def __init__(self, ip: str, chave: str) -> None:
        if not ip or not chave:
            raise DaikinError(
                "IP e Device Key são obrigatórios. Rode primeiro:\n"
                "  python daikin_ac.py configurar --ip <IP> --chave <DEVICE_KEY>"
            )
        self.ip = ip.strip()
        self.chave = chave.strip()
        self._caps: dict[str, Any] | None = None  # capacidades (/device), lidas 1 vez

    # ---- leitura ----------------------------------------------------------
    def status_bruto(self) -> dict[str, Any]:
        dados = get_thing_info(self.ip, self.chave, "acstatus")
        if not isinstance(dados, dict) or not dados.get("port1"):
            raise DaikinError(
                f"Sem resposta válida do ar em {self.ip}:15914. "
                "Verifique o IP, a Device Key e se o PC está na mesma rede."
            )
        return dados

    def capacidades(self) -> dict[str, Any]:
        """O que o aparelho suporta (ex.: heat=0 -> 'Somente Frio'). Fica em cache."""
        if self._caps:
            return self._caps
        try:
            dados = get_thing_info(self.ip, self.chave, "device")
        except Exception:  # noqa: BLE001
            dados = None
        if isinstance(dados, dict) and dados:
            self._caps = dados
        return dados if isinstance(dados, dict) else {}

    def status(self) -> dict[str, Any]:
        p = self.status_bruto()["port1"]
        caps = self.capacidades()
        modo_val = p.get("mode")
        if modo_val in (0, 7):  # o aparelho também usa 0/7 para auto
            modo_val = 1

        def timer(prefixo: str) -> dict[str, Any] | None:
            if f"{prefixo}_timer_set" not in p:
                return None
            return {"ativo": p.get(f"{prefixo}_timer_set") == 1,
                    "valor": p.get(f"{prefixo}_timer_value")}

        return {
            "somente_frio": caps.get("heat") == 0,
            "tem_swing": caps.get("v_sw", 1) != 0,
            "conforto": p.get("coanda") == 1,
            "tem_conforto": "coanda" in p,
            "swing_horizontal": p.get("h_swing") == 1 if "h_swing" in p else None,
            "timer_ligar": timer("on"),
            "timer_desligar": timer("off"),
            "ligado": p.get("power") == 1,
            "modo": MODOS_INV.get(modo_val, f"desconhecido({p.get('mode')})"),
            "temp_alvo": p.get("temperature"),
            "temp_ambiente": (p.get("sensors") or {}).get("room_temp"),
            "ventilador": VENTILADOR_INV.get(p.get("fan"), f"desconhecido({p.get('fan')})"),
            "swing_vertical": p.get("v_swing") == 1,
            "coanda": p.get("coanda") == 1 if "coanda" in p else None,
            "eco": p.get("econo") == 1,
            "turbo": p.get("powerchill") == 1,
            "firmware": p.get("fw_ver", "desconhecido"),
        }

    # ---- escrita ----------------------------------------------------------
    def _enviar(self, **campos: Any) -> dict[str, Any]:
        payload = {"port1": dict(campos)}
        # No modo seco o aparelho exige ventilador em auto
        if payload["port1"].get("mode") == MODOS["seco"]:
            payload["port1"]["fan"] = VENTILADOR["auto"]
        resp = send_operation_data(
            self.ip, self.chave, json.dumps(payload), COMMAND_SUFFIX
        )
        if not isinstance(resp, dict) or not resp.get("port1"):
            raise DaikinError("O ar não confirmou o comando (sem resposta válida).")
        return resp

    def ligar(self) -> None:
        self._enviar(power=1)

    def desligar(self) -> None:
        self._enviar(power=0)

    def definir_modo(self, modo: str) -> None:
        modo = modo.lower()
        if modo == "desligado":
            self.desligar()
            return
        if modo not in MODOS:
            raise DaikinError(f"Modo inválido. Use: {', '.join(MODOS)}")
        if modo == "calor" and self.capacidades().get("heat") == 0:
            raise DaikinError("Este ar é 'Somente Frio': não tem modo Aquecer.")
        self._enviar(mode=MODOS[modo], power=1)

    def definir_temperatura(self, temp: float) -> None:
        st = self.status()
        if st["turbo"]:
            raise DaikinError("Não é possível mudar a temperatura com o Potente ativo.")
        if st["modo"] in ("seco", "ventilar"):
            raise DaikinError(f"O modo '{st['modo']}' não aceita temperatura.")
        minimo, maximo = FAIXA_TEMP.get(st["modo"], (10, 32))
        if not minimo <= temp <= maximo:
            raise DaikinError(
                f"No modo '{st['modo']}' a temperatura deve ficar entre {minimo} e {maximo} °C."
            )
        self._enviar(temperature=int(temp))

    def definir_ventilador(self, velocidade: str) -> None:
        if velocidade not in VENTILADOR:
            raise DaikinError(f"Velocidade inválida. Use: {', '.join(VENTILADOR)}")
        st = self.status()
        if st["modo"] == "seco":
            raise DaikinError("No modo seco o ventilador fica sempre em auto.")
        if st["turbo"]:
            raise DaikinError("Não é possível mudar a velocidade com o Potente ativo.")
        self._enviar(fan=VENTILADOR[velocidade])

    def definir_swing(self, ligado: bool, coanda: bool | None = None) -> None:
        if ligado and coanda is None and self.status().get("conforto"):
            # app oficial: "não é possível usar esta função com o Conforto ligado"
            raise DaikinError("Desative o Conforto para usar a Oscilação.")
        campos: dict[str, Any] = {"v_swing": 1 if ligado else 0}
        if coanda is not None:
            campos["coanda"] = 1 if coanda else 0
        self._enviar(**campos)

    def definir_conforto(self, ligado: bool) -> None:
        """'Conforto' do app oficial (coanda): direciona o ar para não bater em você."""
        st = self.status()
        if not st["ligado"]:
            raise DaikinError("Ligue o ar antes de ativar o Conforto.")
        if ligado and st["turbo"]:
            raise DaikinError("Desative o Potente para usar o Conforto.")
        if ligado:
            # Conforto (Coanda) fixa a aleta para cima: a oscilação sai (igual à integração oficial)
            self._enviar(coanda=1, v_swing=0)
        else:
            self._enviar(coanda=0)

    def definir_preset(self, preset: str) -> None:
        """nenhum | eco (Econo) | turbo (Potente). Econo e Potente não andam juntos."""
        preset = preset.lower()
        if preset not in PRESETS:
            raise DaikinError(f"Preset inválido. Use: {', '.join(PRESETS)}")
        st = self.status()
        if not st["ligado"]:
            raise DaikinError("Ligue o ar antes de ativar Econo/Potente.")
        if preset == "nenhum":
            self._enviar(powerchill=0, econo=0)
        elif preset == "eco":
            self._enviar(econo=1, powerchill=0)
        else:
            if st["conforto"]:
                raise DaikinError("Desative o Conforto para usar o Potente.")
            self._enviar(powerchill=1, econo=0)


# --------------------------------------------------------------------------
# Descoberta na rede (opcional, requer `zeroconf`)
# --------------------------------------------------------------------------
def descobrir(segundos: float = 4.0) -> list[tuple[str, str]]:
    try:
        import socket
        import time

        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError as exc:
        raise DaikinError(
            "Para descobrir automaticamente instale: python -m pip install zeroconf"
        ) from exc

    encontrados: dict[str, str] = {}

    class Ouvinte:
        def add_service(self, zc, tipo, nome):  # noqa: ANN001
            info = zc.get_service_info(tipo, nome, timeout=2000)
            if info and info.addresses:
                encontrados[nome] = socket.inet_ntoa(info.addresses[0])

        def update_service(self, zc, tipo, nome):  # noqa: ANN001
            self.add_service(zc, tipo, nome)

        def remove_service(self, zc, tipo, nome):  # noqa: ANN001
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, MDNS_SERVICE, Ouvinte())
        time.sleep(segundos)
    finally:
        zc.close()
    return sorted(encontrados.items())


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------
def imprimir_status(st: dict[str, Any]) -> None:
    print(f"Ligado ........: {'sim' if st['ligado'] else 'não'}")
    print(f"Modo ..........: {st['modo']}")
    print(f"Temp. alvo ....: {st['temp_alvo']} °C")
    print(f"Temp. ambiente : {st['temp_ambiente']} °C")
    print(f"Ventilador ....: {st['ventilador']}")
    print(f"Swing vertical : {'sim' if st['swing_vertical'] else 'não'}")
    if st["tem_conforto"]:
        print(f"Conforto ......: {'sim' if st['conforto'] else 'não'}")
    print(f"Econo .........: {'sim' if st['eco'] else 'não'}")
    print(f"Potente .......: {'sim' if st['turbo'] else 'não'}")
    print(f"Tipo de AC ....: {'Somente Frio' if st['somente_frio'] else 'Frio e Calor'}")
    for nome, chave in (("Timer ligar", "timer_ligar"), ("Timer deslig.", "timer_desligar")):
        if st[chave] is not None:
            t = st[chave]
            print(f"{nome:.<15}: {'ativo' if t['ativo'] else 'inativo'} (valor={t['valor']})")
    print(f"Firmware ......: {st['firmware']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Controle local do Daikin Smart AC")
    ap.add_argument("--ip", help="IP do ar (sobrepõe config.json)")
    ap.add_argument("--chave", help="Device Key (sobrepõe config.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("configurar", help="salva IP e Device Key em config.json")
    c.add_argument("--ip", dest="cfg_ip", required=True)
    c.add_argument("--chave", dest="cfg_chave", required=True)

    sub.add_parser("descobrir", help="procura aparelhos na rede (mDNS)")
    sub.add_parser("atalho", help="cria atalho na Área de Trabalho")
    bi = sub.add_parser("bandeja-windows", help="ícone da bandeja ao iniciar o Windows")
    bi.add_argument("valor", choices=["on", "off"])
    sub.add_parser("status", help="mostra o estado atual")
    sub.add_parser("bruto", help="mostra o JSON bruto do aparelho")
    sub.add_parser("ligar")
    sub.add_parser("desligar")
    m = sub.add_parser("modo")
    m.add_argument("valor", choices=[*MODOS, "desligado"])
    t = sub.add_parser("temp")
    t.add_argument("valor", type=float)
    v = sub.add_parser("ventilador")
    v.add_argument("valor", choices=list(VENTILADOR))
    s = sub.add_parser("swing")
    s.add_argument("valor", choices=["on", "off"])
    s.add_argument("--coanda", choices=["on", "off"])
    p = sub.add_parser("preset")
    p.add_argument("valor", choices=PRESETS)
    cf = sub.add_parser("conforto", help="Conforto (coanda) on/off")
    cf.add_argument("valor", choices=["on", "off"])

    args = ap.parse_args(argv)

    try:
        if args.cmd == "configurar":
            salvar_config(args.cfg_ip, args.cfg_chave)
            print(f"Configuração salva em {CONFIG_PATH}")
            return 0
        if args.cmd == "atalho":
            print(f"Atalho criado: {criar_atalho('desktop')}")
            return 0
        if args.cmd == "bandeja-windows":
            if args.valor == "on":
                caminho = criar_atalho("inicializar", "inicio", NOME_ATALHO_BANDEJA)
                print(f"Ícone da bandeja vai abrir com o Windows ({caminho})")
            else:
                remover_atalho("inicializar", NOME_ATALHO_BANDEJA)
                print("Ícone da bandeja não abre mais com o Windows")
            return 0
        if args.cmd == "descobrir":
            achados = descobrir()
            if not achados:
                print("Nenhum aparelho encontrado (tente informar o IP pelo roteador).")
            for nome, ip in achados:
                print(f"{ip}\t{nome}")
            return 0

        cfg = carregar_config()
        ac = DaikinAC(args.ip or cfg.get("ip", ""), args.chave or cfg.get("chave", ""))

        if args.cmd == "status":
            imprimir_status(ac.status())
        elif args.cmd == "bruto":
            print(json.dumps(ac.status_bruto(), indent=2, ensure_ascii=False))
            caps = ac.capacidades()
            if caps:
                print("\nCapacidades (/device):")
                print(json.dumps(caps, indent=2, ensure_ascii=False))
        elif args.cmd == "ligar":
            ac.ligar()
        elif args.cmd == "desligar":
            ac.desligar()
        elif args.cmd == "modo":
            ac.definir_modo(args.valor)
        elif args.cmd == "temp":
            ac.definir_temperatura(args.valor)
        elif args.cmd == "ventilador":
            ac.definir_ventilador(args.valor)
        elif args.cmd == "swing":
            coanda = None if args.coanda is None else args.coanda == "on"
            ac.definir_swing(args.valor == "on", coanda)
        elif args.cmd == "preset":
            ac.definir_preset(args.valor)
        elif args.cmd == "conforto":
            ac.definir_conforto(args.valor == "on")

        if args.cmd not in ("status", "bruto"):
            print("OK")
        return 0
    except DaikinError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
