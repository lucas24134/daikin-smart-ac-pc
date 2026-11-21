"""Ícone do Daikin Smart AC na bandeja do Windows (ao lado do relógio).

- Clique esquerdo: abre o painel (temperatura, modo, ventilador, swing...)
- Clique direito: menu rápido
- Passe o mouse: estado atual e temperatura do quarto
"""

from __future__ import annotations

import ctypes
import queue
import socket
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))
INTERVALO_S = 10  # atualização do estado (a integração oficial usa 10 s)

# Nitidez em telas com escala (125%, 150%...): precisa vir antes do Tk
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

import tkinter as tk  # noqa: E402


def _erro_fatal(texto: str) -> None:
    import os

    pasta = (Path(os.environ.get("APPDATA", str(Path.home()))) / "DaikinSmartAC"
             if getattr(sys, "frozen", False) else PASTA)
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "erro.log").write_text(texto, encoding="utf-8")
    except OSError:
        pass
    from tkinter import messagebox

    raiz = tk.Tk()
    raiz.withdraw()
    messagebox.showerror("Daikin Smart AC - bandeja", texto)
    raiz.destroy()


try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    from pystray import Menu, MenuItem as Item

    from daikin_ac import (
        MODOS,
        VENTILADOR,
        DaikinAC,
        DaikinError,
        abrir_app,
        carregar_config,
    )
    from painel import Painel
except SystemExit as exc:
    _erro_fatal(f"{exc}\n\nRode o INSTALAR.bat (etapa 1 do assistente).")
    sys.exit(1)
except Exception:  # noqa: BLE001
    _erro_fatal("Faltam componentes. Rode o INSTALAR.bat (etapa 1 do assistente).\n\n"
                + traceback.format_exc())
    sys.exit(1)

NOMES_MODO = {"frio": "Resfriar", "calor": "Aquecer", "seco": "Desumidificar",
              "ventilar": "Ventilar", "auto": "Auto"}
NOMES_VENT = {"auto": "Auto", "silencioso": "Silencioso", "baixo": "Baixa",
              "medio_baixo": "Baixa-Média", "medio": "Média",
              "medio_alto": "Média-Alta", "alto": "Alta"}
CORES = {"frio": (0, 120, 215), "calor": (220, 90, 20), "seco": (0, 150, 140),
         "ventilar": (90, 140, 60), "auto": (120, 80, 200)}
CINZA = (120, 120, 120)
VERMELHO = (200, 40, 40)


def _fonte(tamanho: int):  # noqa: ANN202
    for nome in ("segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def desenhar_icone(cor: tuple[int, int, int], texto: str) -> "Image.Image":
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 63, 63), radius=14, fill=cor)
    fonte = _fonte(38 if len(texto) <= 2 else 26)
    caixa = d.textbbox((0, 0), texto, font=fonte)
    x = (64 - (caixa[2] - caixa[0])) / 2 - caixa[0]
    y = (64 - (caixa[3] - caixa[1])) / 2 - caixa[1]
    d.text((x, y), texto, font=fonte, fill="white")
    return img


class Bandeja:
    def __init__(self) -> None:
        self.st: dict | None = None
        self.erro: str | None = None
        self.atualizado_em: datetime | None = None
        self.ac: DaikinAC | None = None
        self._parar = threading.Event()
        self._trava_leitura = threading.Lock()
        self.fila: queue.Queue = queue.Queue()
        self._carregar_ac()

        # Tk roda na thread principal; o ícone roda em segundo plano
        self.raiz = tk.Tk()
        self.raiz.withdraw()
        self.painel = Painel(self.raiz, self)
        self.raiz.after(50, self._processar_fila)

        self.icone = pystray.Icon(
            "daikin_smart_ac", desenhar_icone(CINZA, "…"), "Daikin Smart AC", self._menu()
        )

    # ------------------------------------------------- ponte entre threads
    def na_ui(self, funcao) -> None:  # noqa: ANN001
        """Agenda funcao() na thread do Tk (seguro a partir de qualquer thread)."""
        self.fila.put(funcao)

    def _processar_fila(self) -> None:
        try:
            while True:
                funcao = self.fila.get_nowait()
                try:
                    funcao()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.raiz.after(50, self._processar_fila)

    # ----------------------------------------------------------- conexão
    def _carregar_ac(self) -> None:
        cfg = carregar_config()
        try:
            self.ac = DaikinAC(cfg.get("ip", ""), cfg.get("chave", ""))
            self.erro = None
        except DaikinError:
            self.ac = None
            self.erro = "Não configurado — abra Configurar…"

    def atualizar(self) -> None:
        with self._trava_leitura:
            if not self.ac:
                self._carregar_ac()
            if self.ac:
                try:
                    self.st = self.ac.status()
                    self.erro = None
                    self.atualizado_em = datetime.now()
                except Exception as exc:  # noqa: BLE001
                    self.st = None
                    self.erro = f"Ar offline: {exc}"[:100]
            self._redesenhar()

    def atualizar_async(self) -> None:
        threading.Thread(target=self.atualizar, daemon=True).start()

    def _redesenhar(self) -> None:
        st = self.st
        if not st:
            self.icone.icon = desenhar_icone(VERMELHO, "!")
            self.icone.title = f"Daikin Smart AC\n{self.erro or 'sem conexão'}"[:127]
        else:
            alvo = st["temp_alvo"]
            texto = str(alvo) if isinstance(alvo, (int, float)) else "--"
            cor = CORES.get(st["modo"], CINZA) if st["ligado"] else CINZA
            self.icone.icon = desenhar_icone(cor, texto)
            estado = "Ligado" if st["ligado"] else "Desligado"
            modo = NOMES_MODO.get(st["modo"], st["modo"])
            amb = st["temp_ambiente"]
            self.icone.title = (
                f"Daikin Smart AC — {estado}\n{modo} · alvo {alvo} °C"
                + (f"\nQuarto: {amb} °C" if amb is not None else "")
            )[:127]
        self.icone.update_menu()
        self.na_ui(self._render_painel)

    def _render_painel(self) -> None:
        if self.painel.visivel:
            self.painel.render()

    def _laco(self) -> None:
        while not self._parar.is_set():
            self.atualizar()
            self._parar.wait(INTERVALO_S)

    # ------------------------------------------------------------- ações
    def executar(self, funcao) -> None:  # noqa: ANN001
        """Roda funcao(ac) em segundo plano; erros vão para o painel ou notificação."""

        def corre() -> None:
            if not self.ac:
                self._avisar("Configure o ar primeiro (menu Configurar…).")
                return
            try:
                funcao(self.ac)
            except DaikinError as exc:
                self._avisar(str(exc))
            except Exception as exc:  # noqa: BLE001
                self._avisar(f"Falha: {exc}")
            self.atualizar()

        threading.Thread(target=corre, daemon=True).start()

    def _avisar(self, texto: str) -> None:
        if self.painel.visivel:
            self.na_ui(lambda: self.painel.toast(texto))
        else:
            self.icone.notify(texto[:250], "Daikin Smart AC")

    def _acao(self, funcao):  # noqa: ANN001, ANN202
        def handler(_icone=None, _item=None) -> None:  # noqa: ANN001
            self.executar(funcao)

        return handler

    def _alternar(self, ac: DaikinAC) -> None:
        if self.st and self.st["ligado"]:
            ac.desligar()
        else:
            ac.ligar()

    def _ajustar_temp(self, delta: int):  # noqa: ANN202
        def f(ac: DaikinAC) -> None:
            atual = ac.status()["temp_alvo"]
            if not isinstance(atual, (int, float)):
                raise DaikinError("Temperatura atual desconhecida.")
            ac.definir_temperatura(int(atual) + delta)

        return f

    def abrir_janela_completa(self) -> None:
        self.painel.esconder()
        abrir_app("janela")

    def abrir_configuracao(self) -> None:
        self.painel.esconder()
        abrir_app("configurar")

    def ouvir_outras_instancias(self, servidor: socket.socket) -> None:
        """Se o app for aberto de novo (atalho, .exe), mostra o painel deste."""

        def corre() -> None:
            while not self._parar.is_set():
                try:
                    conexao, _ = servidor.accept()
                except OSError:
                    return
                with conexao:
                    try:
                        pedido = conexao.recv(32)
                    except OSError:
                        continue
                if pedido.startswith(b"painel"):
                    self.na_ui(self._mostrar_painel)

        threading.Thread(target=corre, daemon=True).start()

    def _mostrar_painel(self) -> None:
        if not self.painel.visivel:
            self.painel.mostrar()

    def _alternar_painel(self, _icone=None, _item=None) -> None:  # noqa: ANN001
        self.na_ui(self.painel.alternar)

    def _sair(self, _icone=None, _item=None) -> None:  # noqa: ANN001
        self._parar.set()
        self.icone.stop()
        self.fila.put(self.raiz.destroy)  # encerra o mainloop na thread do Tk

    # -------------------------------------------------------------- menu
    def _menu(self) -> Menu:
        def info(_item) -> str:  # noqa: ANN001
            if not self.st:
                return self.erro or "Conectando…"
            amb = self.st["temp_ambiente"]
            return (f"Quarto: {amb} °C   ·   Alvo: {self.st['temp_alvo']} °C"
                    if amb is not None else f"Alvo: {self.st['temp_alvo']} °C")

        def texto_energia(_item) -> str:  # noqa: ANN001
            return "Desligar" if self.st and self.st["ligado"] else "Ligar"

        def ligado(_item=None) -> bool:  # noqa: ANN001
            return bool(self.st and self.st["ligado"])

        def modo_item(chave: str) -> Item:
            return Item(
                NOMES_MODO[chave],
                self._acao(lambda ac, c=chave: ac.definir_modo(c)),
                checked=lambda _i, c=chave: bool(self.st and self.st["ligado"]
                                                   and self.st["modo"] == c),
                radio=True,
                # ar "Somente Frio" não mostra Aquecer
                visible=(lambda _i: not (self.st or {}).get("somente_frio"))
                if chave == "calor" else True,
            )

        def vent_item(chave: str) -> Item:
            return Item(
                NOMES_VENT[chave],
                self._acao(lambda ac, c=chave: ac.definir_ventilador(c)),
                checked=lambda _i, c=chave: bool(self.st and self.st["ventilador"] == c),
                radio=True,
            )

        def estado(campo: str) -> bool:
            return bool(self.st and self.st.get(campo))

        def alternar_preset(campo: str, preset: str):  # noqa: ANN202
            # Econo e Potente não ficam ligados juntos (regra do app oficial)
            return self._acao(lambda ac: ac.definir_preset("nenhum" if estado(campo) else preset))

        mais = Menu(
            Item("Conforto", self._acao(lambda ac: ac.definir_conforto(not estado("conforto"))),
                 checked=lambda _i: estado("conforto"),
                 visible=lambda _i: bool(self.st and self.st.get("tem_conforto"))),
            Item("Econo", alternar_preset("eco", "eco"), checked=lambda _i: estado("eco")),
            Item("Oscilação",
                 self._acao(lambda ac: ac.definir_swing(not estado("swing_vertical"))),
                 checked=lambda _i: estado("swing_vertical")),
            Item("Potente", alternar_preset("turbo", "turbo"), checked=lambda _i: estado("turbo")),
        )

        return Menu(
            Item("Abrir painel", self._alternar_painel, default=True),
            Item(info, None, enabled=False),
            Menu.SEPARATOR,
            Item(texto_energia, self._acao(self._alternar)),
            Item("Temperatura  +1 °C", self._acao(self._ajustar_temp(+1)), enabled=ligado),
            Item("Temperatura  −1 °C", self._acao(self._ajustar_temp(-1)), enabled=ligado),
            Item("Modo", Menu(*(modo_item(m) for m in ("frio", "calor", "seco",
                                                       "ventilar", "auto") if m in MODOS))),
            Item("Velocidade", Menu(*(vent_item(v) for v in ("auto", "silencioso", "baixo",
                                                             "medio_baixo", "medio",
                                                             "medio_alto", "alto")
                                      if v in VENTILADOR)), enabled=ligado),
            Item("Mais", mais, enabled=ligado),
            Menu.SEPARATOR,
            Item("Abrir janela completa", lambda *_: self.na_ui(self.abrir_janela_completa)),
            Item("Configurar…", lambda *_: self.na_ui(self.abrir_configuracao)),
            Item("Atualizar agora", lambda *_: self.atualizar_async()),
            Item("Sair", self._sair),
        )

    def rodar(self) -> None:
        self.icone.run_detached()
        self.icone.visible = True
        threading.Thread(target=self._laco, daemon=True).start()
        self.raiz.mainloop()


PORTA_LOCAL = 47915  # só em 127.0.0.1: trava de instância única + "abrir painel"


def instancia_unica() -> socket.socket | None:
    """Impede dois ícones ao mesmo tempo. Devolve o servidor, ou None se já roda."""
    trava = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        trava.bind(("127.0.0.1", PORTA_LOCAL))
        trava.listen(4)
        return trava
    except OSError:
        trava.close()
        return None


def pedir_painel_ao_existente() -> None:
    """O app já está aberto: pede para ele mostrar o painel (como um app normal)."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_LOCAL), timeout=2) as conexao:
            conexao.sendall(b"painel")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    inicio_windows = "--inicio" in argv  # aberto junto com o Windows: fica só no ícone
    servidor = instancia_unica()
    if servidor is None:
        if not inicio_windows:
            pedir_painel_ao_existente()
        sys.exit(0)
    try:
        app = Bandeja()
        app.ouvir_outras_instancias(servidor)
        if app.ac is None:
            abrir_app("configurar")  # primeira vez: abre o assistente
        elif not inicio_windows:
            app.raiz.after(600, app._mostrar_painel)  # abriu pelo atalho: mostra o painel
        app.rodar()
    except Exception:  # noqa: BLE001
        _erro_fatal(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
