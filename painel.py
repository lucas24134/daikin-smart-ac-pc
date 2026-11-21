"""Painel flutuante do Daikin Smart AC (abre acima do relógio, como um flyout).

Desenhado inteiro num Canvas do tkinter: não precisa de bibliotecas extras.
O "controlador" (bandeja.pyw) fornece:
    .st            -> dict de status (DaikinAC.status()) ou None
    .erro          -> texto de erro ou None
    .atualizado_em -> datetime da última leitura ou None
    .executar(f)   -> roda f(ac) em segundo plano e depois atualiza
    .atualizar_async(), .abrir_janela_completa(), .abrir_configuracao()
"""

from __future__ import annotations

import ctypes
import math
import random
import time
import tkinter as tk
from typing import Any, Callable

from daikin_ac import FAIXA_TEMP

W, H = 360, 640  # tamanho lógico (multiplicado pela escala do Windows)

FUNDO = "#0f1e2d"
CARTAO = "#173047"
CARTAO2 = "#1f3d58"
LINHA = "#2a4a66"
TEXTO = "#eef4fa"
SUB = "#93abc2"
APAGADO = "#5d7690"
ACENTO = {"frio": "#3aa0ff", "calor": "#ff8a3d", "seco": "#2ec4b6",
          "ventilar": "#7cc45a", "auto": "#a78bfa"}

# Nomes iguais aos do app oficial Daikin Smart AC
NOMES_MODO = {"frio": "Resfriar", "calor": "Aquecer", "seco": "Desumid.",
              "ventilar": "Ventilar", "auto": "Auto"}
ICONE_MODO = {"frio": "❄", "calor": "☀", "seco": "💧", "ventilar": "≋", "auto": "A"}
NOMES_VENT = {"auto": "Auto", "silencioso": "Silencioso", "baixo": "Baixa",
              "medio_baixo": "Baixa-Média", "medio": "Média",
              "medio_alto": "Média-Alta", "alto": "Alta"}
ORDEM_MODO = ["frio", "calor", "seco", "ventilar", "auto"]
ORDEM_VENT = ["auto", "silencioso", "baixo", "medio_baixo", "medio", "medio_alto", "alto"]
PRESETS = [("nenhum", "Normal"), ("eco", "Eco"), ("turbo", "Turbo")]

def _gerar_vento() -> tuple[list, list]:
    """Traços e partículas fixos (mesma 'semente'), cada um com ritmo próprio."""
    rnd = random.Random(7)
    tracos = []
    for i in range(26):
        u = (i + rnd.uniform(-0.4, 0.4)) / 25
        tracos.append((min(max(u, 0.0), 1.0),        # posição ao longo da saída
                       rnd.random(),                  # fase inicial
                       rnd.uniform(0.008, 0.015),     # velocidade
                       rnd.uniform(24, 46),           # comprimento
                       rnd.uniform(1.1, 1.8)))        # espessura
    particulas = [(rnd.random(), rnd.random(), rnd.uniform(0.006, 0.011),
                   rnd.uniform(0.7, 1.2)) for _ in range(12)]
    return tracos, particulas


_TRACOS, _PARTICULAS = _gerar_vento()

ICONES = "Segoe MDL2 Assets"
G_POWER, G_REFRESH, G_FECHAR, G_MAIS, G_MENOS = "", "", "", "", ""


def escala_windows() -> float:
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:  # noqa: BLE001
        return 1.0


def area_de_trabalho(raiz: tk.Misc) -> tuple[int, int, int, int]:
    """Área útil da tela (sem a barra de tarefas), em pixels."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]

        r = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        return r.l, r.t, r.r, r.b
    except Exception:  # noqa: BLE001
        return 0, 0, raiz.winfo_screenwidth(), raiz.winfo_screenheight() - 48


def num(v: Any) -> str:
    """Formata número sem casas desnecessárias (27.0 -> 27, 27.5 -> 27.5)."""
    if isinstance(v, (int, float)):
        return f"{v:g}"
    return str(v)


def misturar(c1: str, c2: str, t: float) -> str:
    """Mistura duas cores #rrggbb (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class Painel(tk.Toplevel):
    def __init__(self, raiz: tk.Tk, controlador: Any) -> None:
        super().__init__(raiz)
        self.ctl = controlador
        self.s = escala_windows()
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=FUNDO)
        self.c = tk.Canvas(self, width=self.S(W), height=self.S(H), bg=FUNDO,
                           highlightthickness=0, bd=0)
        self.c.pack()
        self.visivel = False
        self.escondido_em = 0.0
        self.folha: str | None = None        # "modo" | "vent" | "preset" | None
        self.temp_previa: int | None = None  # valor do slider antes de enviar
        self._envio_temp: str | None = None
        self._toast = ("", SUB)
        self._toast_id: str | None = None
        self._fase = 0
        self._arrastando = False
        self._cantos_ok = False
        self._intensidade = 0.0     # 0 = desligado (aleta fechada), 1 = ligado (vento total)
        self._conforto_t = 0.0      # 0 = vento para baixo, 1 = Conforto (aleta para cima)
        self._geo_vento = (74, 286, 210, 290)
        self._transicionando = False
        self.bind("<Escape>", lambda _e: self.esconder())
        self.bind("<FocusOut>", lambda _e: self.after(150, self._checar_foco))

    # ------------------------------------------------------------ utilidades
    def S(self, v: float) -> int:  # noqa: N802
        return int(round(v * self.s))

    def F(self, tam: float, peso: str = "normal", familia: str = "Segoe UI"):  # noqa: N802
        return (familia, -self.S(tam), peso)

    def ret(self, x1, y1, x2, y2, r, **kw):  # noqa: ANN001, ANN201
        x1, y1, x2, y2, r = map(self.S, (x1, y1, x2, y2, r))
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.c.create_polygon(pts, smooth=True, **kw)

    def txt(self, x, y, texto, tam=12, cor=TEXTO, peso="normal", anchor="nw",  # noqa: ANN001, ANN201
            familia="Segoe UI", **kw):
        return self.c.create_text(self.S(x), self.S(y), text=texto, fill=cor,
                                  font=self.F(tam, peso, familia), anchor=anchor, **kw)

    def clicavel(self, tag: str, acao: Callable[[], None]) -> None:
        self.c.tag_bind(tag, "<Button-1>", lambda _e: acao())
        self.c.tag_bind(tag, "<Enter>", lambda _e: self.c.configure(cursor="hand2"))
        self.c.tag_bind(tag, "<Leave>", lambda _e: self.c.configure(cursor=""))

    # ------------------------------------------------------------ estado
    @property
    def st(self) -> dict | None:
        return self.ctl.st

    def ligado(self) -> bool:
        return bool(self.st and self.st.get("ligado"))

    def acento(self) -> str:
        if not self.ligado():
            return APAGADO
        return ACENTO.get(self.st.get("modo"), ACENTO["frio"])

    def faixa(self) -> tuple[int, int]:
        modo = (self.st or {}).get("modo", "frio")
        return FAIXA_TEMP.get(modo, (16, 32))

    def temp_ajustavel(self) -> bool:
        return self.ligado() and self.st.get("modo") not in ("seco", "ventilar") \
            and not self.st.get("turbo")

    # ------------------------------------------------------------ mostrar
    def alternar(self) -> None:
        if self.visivel:
            self.esconder()
        elif time.monotonic() - self.escondido_em > 0.4:
            self.mostrar()

    def mostrar(self) -> None:
        self.folha = None
        self.render()
        esq, topo, dir_, base = area_de_trabalho(self)
        w, h = self.S(W), self.S(H)
        x = dir_ - w - self.S(12)
        y_final = base - h - self.S(12)
        self.geometry(f"{w}x{h}+{x}+{y_final + self.S(24)}")
        self.deiconify()
        self.lift()
        self._ajustar_janela()
        self.visivel = True
        self._deslizar(x, y_final, passo=0)
        self.focus_force()
        self._animar()
        self.ctl.atualizar_async()

    def _deslizar(self, x: int, y_final: int, passo: int) -> None:
        total = 6
        if passo > total or not self.visivel:
            return
        t = passo / total
        desloc = int(self.S(24) * (1 - t) ** 2)
        self.geometry(f"+{x}+{y_final + desloc}")
        self.after(16, lambda: self._deslizar(x, y_final, passo + 1))

    def _ajustar_janela(self) -> None:
        """Cantos arredondados (Windows 11) e trazer para frente."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            if not self._cantos_ok:
                pref = ctypes.c_int(2)  # DWMWCP_ROUND
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
                cor = ctypes.c_int(0x004E3C2C)  # borda sutil (COLORREF 0x00BBGGRR)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(cor), 4)
                self._cantos_ok = True
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001
            pass

    def esconder(self) -> None:
        if not self.visivel:
            return
        self.visivel = False
        self.escondido_em = time.monotonic()
        self.withdraw()

    def _checar_foco(self) -> None:
        if self.visivel and not self._arrastando and self.focus_get() is None:
            self.esconder()

    # ------------------------------------------------------------ animação
    def _animar(self) -> None:
        """Faz o vento 'correr' para baixo continuamente."""
        if not self.visivel:
            return
        self._fase += 1
        if self._intensidade > 0 and self.st:
            self.c.delete("vento")
            self._desenhar_vento()
            if self.c.find_withtag("marco_vento"):
                self.c.tag_lower("vento", "marco_vento")
        self.after(40, self._animar)

    def _iniciar_transicao(self) -> None:
        """Liga/desliga animado: aleta abre/fecha e o vento aparece/some."""
        if self._transicionando:
            return
        self._transicionando = True
        self._passo_transicao()

    def _alvo_conforto(self) -> float:
        return 1.0 if self.ligado() and (self.st or {}).get("conforto") else 0.0

    def _passo_transicao(self) -> None:
        """Anima juntos: ligar/desligar (intensidade) e Conforto (aleta para cima)."""
        alvo = 1.0 if self.ligado() else 0.0
        alvo_c = self._alvo_conforto()
        passo = 0.08

        def aproximar(atual: float, destino: float) -> float:
            if abs(atual - destino) <= passo:
                return destino
            return atual + (passo if destino > atual else -passo)

        if not self.visivel:
            self._intensidade, self._conforto_t = alvo, alvo_c
        else:
            self._intensidade = aproximar(self._intensidade, alvo)
            self._conforto_t = aproximar(self._conforto_t, alvo_c)
        if self._intensidade == alvo and self._conforto_t == alvo_c:
            self._transicionando = False
            self.render()
            return
        self.render()
        self.after(30, self._passo_transicao)

    # ------------------------------------------------------------ desenho
    def render(self) -> None:
        c = self.c
        c.delete("all")
        st = self.st
        alvo_int = 1.0 if self.ligado() else 0.0
        alvo_c = self._alvo_conforto()
        if not self.visivel:
            # ao abrir o painel já mostra o estado certo
            self._intensidade, self._conforto_t = alvo_int, alvo_c
        elif (self._intensidade != alvo_int or self._conforto_t != alvo_c) \
                and not self._transicionando:
            self.after(0, self._iniciar_transicao)
        ac = self.acento()

        # Cabeçalho
        self.txt(24, 18, "Daikin Smart AC", 17, peso="bold")
        quando = self.ctl.atualizado_em.strftime("%H:%M") if self.ctl.atualizado_em else "--:--"
        sub = f"Atualizado às {quando}" if st else (self.ctl.erro or "Conectando…")
        self.txt(24, 44, sub[:48], 11, SUB)
        self.txt(300, 24, G_REFRESH, 13, SUB, familia=ICONES, tags=("btn_atualizar",))
        self.txt(330, 24, G_FECHAR, 12, SUB, familia=ICONES, tags=("btn_fechar",))
        self.clicavel("btn_atualizar", self._clicar_atualizar)
        self.clicavel("btn_fechar", self.esconder)

        # Cartão
        self.ret(12, 76, 348, 592, 18, fill=CARTAO, outline=LINHA)

        if not st:
            self.txt(180, 300, "Sem conexão com o ar", 15, SUB, anchor="center")
            self.txt(180, 328, (self.ctl.erro or "")[:60], 10, APAGADO, anchor="center",
                     width=self.S(290), justify="center")
            self.txt(180, 380, "Configurar…", 12, ACENTO["frio"], anchor="center",
                     tags=("lnk_config",))
            self.clicavel("lnk_config", self.ctl.abrir_configuracao)
            self._rodape()
            return

        # Título do aparelho + botão liga/desliga
        self.txt(32, 94, "Ar-condicionado", 15, peso="bold")
        tipo = "Somente Frio" if st.get("somente_frio") else None
        if tipo:  # "Tipo de AC" do app oficial
            self.txt(280, 98, tipo, 9, SUB, anchor="ne")
        amb = st.get("temp_ambiente")
        estado = "Ligado" if self.ligado() else "Desligado"
        info = f"{estado} · {NOMES_MODO.get(st.get('modo'), '?')}"
        if amb is not None:
            info += f" · {num(amb)} °C no ambiente"
        self.txt(32, 118, info, 11, SUB)
        self._botao_power(310, 108)

        # Ilustração do aparelho + vento
        self._desenhar_aparelho(40, 150, 320, 220)

        # Temperatura grande
        alvo = self.temp_previa if self.temp_previa is not None else st.get("temp_alvo")
        texto_t = f"{alvo}" if isinstance(alvo, (int, float)) else "--"
        cor_t = TEXTO if self.temp_ajustavel() else SUB
        idt = self.txt(32, 296, texto_t, 54, cor_t, familia="Segoe UI Light")
        x2 = c.bbox(idt)[2] / self.s
        self.txt(x2 + 4, 312, "°C", 15, cor_t)
        if amb is not None:
            self.txt(328, 318, f"Quarto  {num(amb)} °C", 11, SUB, anchor="ne")

        # Slider
        self._slider(alvo, 386)

        # Blocos
        self._blocos(436)

        if self.folha:
            self._desenhar_folha()
        self._rodape()

    def _botao_power(self, cx: float, cy: float) -> None:
        r = 21
        x1, y1, x2, y2 = (self.S(cx - r), self.S(cy - r), self.S(cx + r), self.S(cy + r))
        if self.ligado():
            self.c.create_oval(x1 - self.S(4), y1 - self.S(4), x2 + self.S(4), y2 + self.S(4),
                               fill=misturar(self.acento(), CARTAO, 0.7), outline="",
                               tags=("btn_power",))
            self.c.create_oval(x1, y1, x2, y2, fill=self.acento(), outline="", tags=("btn_power",))
            cor = "white"
        else:
            self.c.create_oval(x1, y1, x2, y2, fill=CARTAO2, outline=LINHA,
                               width=self.S(1.5), tags=("btn_power",))
            cor = SUB
        self.txt(cx, cy, G_POWER, 15, cor, anchor="center", familia=ICONES, tags=("btn_power",))
        self.clicavel("btn_power", self._clicar_power)

    def _desenhar_aparelho(self, x1: float, y1: float, x2: float, y2: float) -> None:
        """Aparelho em estilo 'vidro': translúcido, contorno fino e visor escuro."""
        t = self._intensidade  # 0 = desligado ... 1 = ligado
        modo = (self.st or {}).get("modo")
        branco = "#ffffff"
        vidro = misturar(CARTAO, branco, 0.035 + 0.035 * t)
        contorno = misturar(CARTAO, branco, 0.20 + 0.22 * t)
        alt = 66
        # corpo translúcido + reflexo suave no topo
        self.ret(x1, y1, x2, y1 + alt, 11, fill=vidro, outline=contorno, width=self.S(1.2))
        self.c.create_line(self.S(x1 + 14), self.S(y1 + 3), self.S(x2 - 14), self.S(y1 + 3),
                           fill=misturar(CARTAO, branco, 0.10 + 0.10 * t), width=self.S(1))
        # visor escuro com modo + temperatura
        vx1, vy1, vx2, vy2 = x2 - 80, y1 + 13, x2 - 18, y1 + 35
        self.ret(vx1, vy1, vx2, vy2, 6, fill=misturar(CARTAO, "#000000", 0.42),
                 outline=misturar(CARTAO, branco, 0.10))
        if t > 0.3 and self.st:
            alvo = self.temp_previa if self.temp_previa is not None else self.st.get("temp_alvo")
            brilho = min(1.0, (t - 0.3) / 0.7)
            self.txt(vx1 + 11, (vy1 + vy2) / 2, ICONE_MODO.get(modo, ""), 10,
                     misturar(CARTAO, "#9fd2ff" if modo != "calor" else "#ffb37a", brilho),
                     anchor="w", familia="Segoe UI Symbol")
            self.txt(vx2 - 9, (vy1 + vy2) / 2, f"{alvo}", 11,
                     misturar(CARTAO, branco, brilho), anchor="e", peso="bold")
        # grade da saída de ar
        gy1, gy2 = y1 + 46, y1 + 58
        self.ret(x1 + 12, gy1, x2 - 12, gy2, 3, fill=misturar(CARTAO, "#000000", 0.55),
                 outline="")
        for i in range(1, 30):
            xx = x1 + 12 + i * (x2 - x1 - 24) / 30
            self.c.create_line(self.S(xx), self.S(gy1 + 1), self.S(xx), self.S(gy2 - 1),
                               fill=misturar(CARTAO, branco, 0.06), width=self.S(1))
        # aleta: fechada cobre a grade; aberta vira uma lâmina fina inclinada
        # Conforto (Coanda): a aleta gira para CIMA, joga o ar no teto e ele se espalha
        c = self._conforto_t * t
        dobradica = gy2 + 1
        ponta_normal = dobradica - 13 * (1 - t) + 7 * t
        ponta = ponta_normal + (dobradica - 6 - ponta_normal) * c
        pts = [x1 + 12, dobradica, x2 - 12, dobradica,
               x2 - 12 - 4 * t, ponta, x1 + 12 + 4 * t, ponta]
        self.c.create_polygon([self.S(v) for v in pts],
                              fill=misturar(misturar(vidro, misturar(CARTAO, branco, 0.16), t),
                                            misturar(CARTAO, branco, 0.30), c),
                              outline=misturar(contorno, misturar(CARTAO, branco, 0.45), t),
                              width=self.S(1))
        # geometria usada pelo vento animado
        self._geo_vento = (x1 + 34, x2 - 34, max(ponta_normal, dobradica) + 3, y2 + 70)
        if c > 0.5:  # indicação discreta, como o ícone do app (ar passa por cima)
            self.txt((x1 + x2) / 2, y1 - 8, "Conforto · ar espalhado pelo teto", 8,
                     misturar(CARTAO, "#bfe3ff", c), anchor="center")
        if t > 0.02:
            self._desenhar_vento()
        self.c.create_line(0, 0, 0, 0, fill="", tags=("marco_vento",))  # camada do vento

    def _desenhar_vento(self) -> None:
        """Vento como traços brancos suaves que descem e se dissipam (+ partículas)."""
        t = self._intensidade
        xa, xb, y0, y_lim = self._geo_vento
        meio, larg = (xa + xb) / 2, xb - xa
        modo = (self.st or {}).get("modo")
        branco = misturar("#ffffff", ACENTO.get(modo, ACENTO["frio"]), 0.10)
        c = self._conforto_t
        percurso = (y_lim - y0) * (0.45 + 0.55 * t) * (1 - 0.2 * c)

        def ponto(u: float, s: float) -> tuple[float, float]:
            x0 = xa + u * larg
            # normal: leque para baixo
            abre = (x0 - meio) / larg * 0.95
            xn, yn = x0 + abre * s, y0 + s
            if c <= 0:
                return xn, yn
            # Conforto: o ar sai para os lados rente ao "teto" e só depois desce, em arco
            lado = (u - 0.5) * 2  # -1 (esquerda) ... 1 (direita)
            sinal = 1 if lado >= 0 else -1
            xc = x0 + lado * s * 0.75 + sinal * s * 0.12
            yc = y0 + s * 0.10 + max(0.0, s - 42) * 0.55  # sai quase reto, depois desce
            return xn + (xc - xn) * c, yn + (yc - yn) * c

        for u, fase0, vel, comp, larg_tr in _TRACOS:
            p = (fase0 + self._fase * vel) % 1.0
            vis = t * (math.sin(math.pi * p) ** 1.3) * 0.62
            if vis < 0.03:
                continue
            s_ini = p * percurso
            s_len = comp * (0.6 + 0.4 * t)
            # Afinamento suave: camadas centradas, cada uma mais curta, grossa e clara
            # (ponta fina e apagada, meio mais forte), como um risco de vento.
            camadas = [(1.00, 0.6, 0.10, 4.2),   # halo bem suave
                       (1.00, 0.7, 0.45, 1.0),
                       (0.66, 0.9, 0.75, 1.0),
                       (0.34, 1.0, 1.00, 1.0)]
            for frac, esp, forca, mult in camadas:
                meio_s = s_ini + s_len / 2
                a = meio_s - s_len * frac / 2
                b = meio_s + s_len * frac / 2
                xa_, ya_ = ponto(u, a)
                xm_, ym_ = ponto(u, (a + b) / 2)
                xb_, yb_ = ponto(u, b)
                self.c.create_line(self.S(xa_), self.S(ya_), self.S(xm_), self.S(ym_),
                                   self.S(xb_), self.S(yb_), smooth=True,
                                   fill=misturar(CARTAO, branco, min(1.0, vis * forca)),
                                   width=max(1, self.S(larg_tr * esp * mult)),
                                   capstyle="round", tags=("vento",))

        for u, fase0, vel, raio in _PARTICULAS:
            p = (fase0 + self._fase * vel) % 1.0
            vis = t * math.sin(math.pi * p) * 0.55
            if vis < 0.05:
                continue
            x, y = ponto(u, p * percurso * 1.05)
            r = raio * self.s
            self.c.create_oval(self.S(x) - r, self.S(y) - r, self.S(x) + r, self.S(y) + r,
                               fill=misturar(CARTAO, branco, vis), outline="",
                               tags=("vento",))

    def _slider(self, alvo: Any, y: float) -> None:
        mn, mx = self.faixa()
        ativo = self.temp_ajustavel()
        x0, x1 = 78, 282
        cor_trilho = LINHA
        cor_ativo = self.acento() if ativo else APAGADO
        # botões - e +
        for cx, glifo, tag, delta in ((40, G_MENOS, "btn_menos", -1), (320, G_MAIS, "btn_mais", +1)):
            self.c.create_oval(self.S(cx - 17), self.S(y - 17), self.S(cx + 17), self.S(y + 17),
                               fill=CARTAO2, outline=LINHA, tags=(tag,))
            self.txt(cx, y, glifo, 11, TEXTO if ativo else APAGADO, anchor="center",
                     familia=ICONES, tags=(tag,))
            self.clicavel(tag, lambda d=delta: self._passo_temp(d))
        # trilho com marcas
        self.c.create_line(self.S(x0), self.S(y), self.S(x1), self.S(y), fill=cor_trilho,
                           width=self.S(4), capstyle="round", tags=("trilho",))
        for t in range(mn, mx + 1):
            xx = x0 + (t - mn) * (x1 - x0) / max(1, mx - mn)
            alto = 7 if t % 2 == 0 else 4
            self.c.create_line(self.S(xx), self.S(y - 12 - alto), self.S(xx), self.S(y - 12),
                               fill=APAGADO, width=self.S(1), tags=("trilho",))
        self.txt(x0, y + 12, f"{mn}°", 9, APAGADO)
        self.txt(x1, y + 12, f"{mx}°", 9, APAGADO, anchor="ne")
        if isinstance(alvo, (int, float)):
            v = min(max(alvo, mn), mx)
            xk = x0 + (v - mn) * (x1 - x0) / max(1, mx - mn)
            self.c.create_line(self.S(x0), self.S(y), self.S(xk), self.S(y), fill=cor_ativo,
                               width=self.S(4), capstyle="round", tags=("trilho",))
            self.ret(xk - 6, y - 13, xk + 6, y + 13, 6, fill="white" if ativo else SUB,
                     outline="", tags=("trilho",))
        self._geo_slider = (x0, x1, mn, mx)
        self.c.tag_bind("trilho", "<Button-1>", self._arrastar)
        self.c.tag_bind("trilho", "<B1-Motion>", self._arrastar)
        self.c.tag_bind("trilho", "<ButtonRelease-1>", self._soltar)

    def _blocos(self, y: float) -> None:
        st = self.st
        ligado = self.ligado()
        extras = [nome for chave, nome in (("conforto", "Conforto"), ("eco", "Econo"),
                                           ("swing_vertical", "Oscilação"), ("turbo", "Potente"))
                  if st.get(chave)]
        valor_mais = extras[0] if len(extras) == 1 else (f"{len(extras)} ativos" if extras
                                                          else "Nenhum")
        timers = [t for t in (st.get("timer_ligar"), st.get("timer_desligar")) if t]
        valor_timer = "Ativo" if any(t["ativo"] for t in timers) else "Desligado"
        blocos = [
            ("modo", ICONE_MODO.get(st.get("modo"), "A"), "Modo",
             NOMES_MODO.get(st.get("modo"), "?")),
            ("vent", "✲", "Velocidade", NOMES_VENT.get(st.get("ventilador"), "?")),
            ("timer", "◷", "Timer", valor_timer),
            ("mais", "⋯", "Mais", valor_mais),
        ]
        larg, gap, x = 72, 8, 24
        for chave, glifo, rotulo, valor in blocos:
            selecionado = self.folha == chave or (chave == "mais" and extras) \
                or (chave == "timer" and valor_timer == "Ativo")
            fundo = misturar(self.acento(), CARTAO2, 0.78) if (selecionado and ligado) else CARTAO2
            tag = f"bloco_{chave}"
            self.ret(x, y, x + larg, y + 84, 14, fill=fundo,
                     outline=self.acento() if (self.folha == chave) else "", tags=(tag,))
            cor_g = self.acento() if ligado else APAGADO
            self.txt(x + 12, y + 12, glifo, 15, cor_g, familia="Segoe UI Symbol", tags=(tag,))
            self.txt(x + 12, y + 42, rotulo, 9, SUB, tags=(tag,))
            self.txt(x + 12, y + 58, valor, 10, TEXTO if ligado else APAGADO, peso="bold",
                     tags=(tag,), width=self.S(larg - 16))
            self.clicavel(tag, lambda c=chave: self._clicar_bloco(c))
            x += larg + gap

        # Linhas extras (como no app): firmware e janela completa
        self.c.create_line(self.S(28), self.S(y + 102), self.S(332), self.S(y + 102),
                           fill=LINHA, width=self.S(1))
        self.txt(32, y + 114, "Janela completa", 11, TEXTO, tags=("lnk_janela",))
        self.txt(328, y + 114, "›", 13, SUB, anchor="ne", tags=("lnk_janela",))
        self.clicavel("lnk_janela", self.ctl.abrir_janela_completa)

    def _modos_disponiveis(self) -> list[str]:
        if (self.st or {}).get("somente_frio"):
            return [m for m in ORDEM_MODO if m != "calor"]  # "Somente Frio": sem Aquecer
        return ORDEM_MODO

    def _linhas_folha(self) -> tuple[str, list[tuple[str, str, bool, str]]]:
        """(título, [(chave, texto, marcado, tipo)]) — tipo: escolha | chave | info."""
        st = self.st
        if self.folha == "modo":
            return "Modo", [(k, f"{ICONE_MODO[k]}   {NOMES_MODO[k]}", k == st.get("modo"),
                             "escolha") for k in self._modos_disponiveis()]
        if self.folha == "vent":
            return "Velocidade", [(k, NOMES_VENT[k], k == st.get("ventilador"), "escolha")
                                  for k in ORDEM_VENT]
        if self.folha == "mais":
            linhas = []
            if st.get("tem_conforto"):
                linhas.append(("conforto", "Conforto", bool(st.get("conforto")), "chave"))
            linhas.append(("eco", "Econo", bool(st.get("eco")), "chave"))
            if st.get("tem_swing", True):
                linhas.append(("oscilacao", "Oscilação", bool(st.get("swing_vertical")), "chave"))
            linhas.append(("potente", "Potente", bool(st.get("turbo")), "chave"))
            return "Mais", linhas
        # timer: mostra o que o aparelho informa (programar pelo PC: próxima versão)
        linhas = []
        for chave, nome in (("timer_ligar", "Ligar"), ("timer_desligar", "Desligar")):
            t = st.get(chave)
            if t is None:
                texto = f"{nome}: não informado pelo aparelho"
            else:
                texto = f"{nome}: {'ativo' if t['ativo'] else 'desligado'}"
            linhas.append((chave, texto, bool(t and t["ativo"]), "info"))
        linhas.append(("nota", "Programar o timer pelo PC: em breve", False, "info"))
        return "Timer", linhas

    def _desenhar_folha(self) -> None:
        titulo, linhas = self._linhas_folha()
        altura_linha = 38
        y0 = 590 - 48 - altura_linha * len(linhas)
        fundo_f = misturar(CARTAO, "#000000", 0.18)
        self.ret(20, y0, 340, 586, 16, fill=fundo_f, outline=LINHA, tags=("folha",))
        self.txt(36, y0 + 14, titulo, 13, peso="bold", tags=("folha",))
        self.txt(324, y0 + 16, G_FECHAR, 10, SUB, anchor="ne", familia=ICONES,
                 tags=("folha_fechar",))
        self.clicavel("folha_fechar", self._fechar_folha)
        y = y0 + 44
        for chave, nome, marcado, tipo in linhas:
            tag = f"op_{chave}"
            meio = y + (altura_linha - 4) / 2
            destaque = marcado and tipo == "escolha"
            self.ret(28, y, 332, y + altura_linha - 4, 10,
                     fill=misturar(self.acento(), fundo_f, 0.75) if destaque else fundo_f,
                     outline="", tags=(tag,))
            cor = SUB if tipo == "info" and chave == "nota" else TEXTO
            self.txt(42, meio, nome, 12 if tipo != "info" else 11, cor, anchor="w",
                     familia="Segoe UI Symbol" if self.folha == "modo" else "Segoe UI",
                     tags=(tag,))
            if tipo == "escolha" and marcado:
                self.txt(318, meio, "✓", 12, self.acento(), anchor="e", tags=(tag,))
            elif tipo == "chave":
                self._interruptor(296, meio, marcado, tag)
            if tipo != "info":
                self.clicavel(tag, lambda c=chave: self._escolher(c))
            y += altura_linha

    def _interruptor(self, x: float, cy: float, ligado: bool, tag: str) -> None:
        """Interruptor estilo Windows 11 (liga/desliga)."""
        cor = self.acento() if ligado and self.ligado() else LINHA
        self.ret(x, cy - 10, x + 36, cy + 10, 10, fill=cor if ligado else "",
                 outline=cor if ligado else SUB, width=self.S(1.2), tags=(tag,))
        cx = x + 26 if ligado else x + 10
        r = 6
        self.c.create_oval(self.S(cx - r), self.S(cy - r), self.S(cx + r), self.S(cy + r),
                           fill="white" if ligado else SUB, outline="", tags=(tag,))

    def _rodape(self) -> None:
        texto, cor = self._toast
        if texto:
            self.txt(180, 614, texto[:70], 10, cor, anchor="center")
        else:
            fw = (self.st or {}).get("firmware")
            self.txt(180, 614, f"Controle local · porta 15914" + (f" · fw {fw}" if fw else ""),
                     9, APAGADO, anchor="center")

    # ------------------------------------------------------------ ações
    def toast(self, texto: str, erro: bool = True) -> None:
        self._toast = (texto, "#ff8a80" if erro else "#9be7a5")
        if self._toast_id:
            self.after_cancel(self._toast_id)
        self._toast_id = self.after(4500, self._limpar_toast)
        if self.visivel:
            self.render()

    def _limpar_toast(self) -> None:
        self._toast = ("", SUB)
        self._toast_id = None
        if self.visivel:
            self.render()

    def _otimista(self, **campos: Any) -> None:
        """Atualiza a tela na hora; o estado real chega logo depois."""
        if self.st:
            self.st.update(campos)
        self.render()

    def _clicar_atualizar(self) -> None:
        self.ctl.atualizar_async()

    def _clicar_power(self) -> None:
        if self.ligado():
            self._otimista(ligado=False)
            self.ctl.executar(lambda ac: ac.desligar())
        else:
            self._otimista(ligado=True)
            self.ctl.executar(lambda ac: ac.ligar())

    def _exige_ligado(self) -> bool:
        if not self.ligado():
            self.toast("Ligue o ar primeiro.")
            return False
        return True

    def _clicar_bloco(self, chave: str) -> None:
        if chave == "modo":  # escolher modo também liga o ar
            self.folha = None if self.folha == "modo" else "modo"
            self.render()
            return
        if chave == "timer":  # só leitura por enquanto
            self.folha = None if self.folha == chave else chave
            self.render()
            return
        if not self._exige_ligado():
            return
        if chave == "vent" and self.st.get("modo") == "seco":
            self.toast("No modo Desumid. a velocidade fica em Auto.")
            return
        self.folha = None if self.folha == chave else chave
        self.render()

    def _fechar_folha(self) -> None:
        self.folha = None
        self.render()

    def _escolher(self, chave: str) -> None:
        folha = self.folha
        if folha == "modo":
            self.folha = None
            self._otimista(modo=chave, ligado=True)
            self.ctl.executar(lambda ac: ac.definir_modo(chave))
        elif folha == "vent":
            self.folha = None
            self._otimista(ventilador=chave)
            self.ctl.executar(lambda ac: ac.definir_ventilador(chave))
        elif folha == "mais":  # interruptores: a folha continua aberta
            self._alternar_extra(chave)

    def _alternar_extra(self, chave: str) -> None:
        st = self.st
        if not self._exige_ligado():
            return
        if chave == "conforto":
            novo = not st.get("conforto")
            if novo and st.get("turbo"):
                self.toast("Desative o Potente para usar o Conforto.")
                return
            if novo:
                self._otimista(conforto=True, swing_vertical=False)
            else:
                self._otimista(conforto=False)
            self.ctl.executar(lambda ac: ac.definir_conforto(novo))
        elif chave == "oscilacao":
            novo = not st.get("swing_vertical")
            if novo and st.get("conforto"):
                self.toast("Desative o Conforto para usar a Oscilação.")
                return
            self._otimista(swing_vertical=novo)
            self.ctl.executar(lambda ac: ac.definir_swing(novo))
        elif chave == "eco":  # Econo e Potente não ficam ligados juntos
            preset = "nenhum" if st.get("eco") else "eco"
            self._otimista(eco=preset == "eco", turbo=False)
            self.ctl.executar(lambda ac: ac.definir_preset(preset))
        elif chave == "potente":
            if not st.get("turbo") and st.get("conforto"):
                self.toast("Desative o Conforto para usar o Potente.")
                return
            preset = "nenhum" if st.get("turbo") else "turbo"
            self._otimista(turbo=preset == "turbo", eco=False)
            self.ctl.executar(lambda ac: ac.definir_preset(preset))

    def _motivo_temp_bloqueada(self) -> str:
        if not self.ligado():
            return "Ligue o ar primeiro."
        if self.st.get("turbo"):
            return "Desative o Potente para mudar a temperatura."
        return f"O modo {NOMES_MODO.get(self.st.get('modo'), '')} não usa temperatura."

    def _passo_temp(self, delta: int) -> None:
        if not self.temp_ajustavel():
            self.toast(self._motivo_temp_bloqueada())
            return
        base = self.temp_previa if self.temp_previa is not None else self.st.get("temp_alvo")
        if not isinstance(base, (int, float)):
            return
        mn, mx = self.faixa()
        self.temp_previa = int(min(max(base + delta, mn), mx))
        self.render()
        self._agendar_envio_temp()

    def _arrastar(self, evento: tk.Event) -> None:
        if not self.temp_ajustavel():
            if str(evento.type) == "ButtonPress" or evento.type == tk.EventType.ButtonPress:
                self.toast(self._motivo_temp_bloqueada())
            return
        self._arrastando = True
        x0, x1, mn, mx = self._geo_slider
        x = evento.x / self.s
        frac = min(max((x - x0) / (x1 - x0), 0), 1)
        valor = round(mn + frac * (mx - mn))
        if valor != self.temp_previa:
            self.temp_previa = valor
            self.render()

    def _soltar(self, _evento: tk.Event) -> None:
        if self._arrastando:
            self._arrastando = False
            self._agendar_envio_temp()

    def _agendar_envio_temp(self) -> None:
        if self._envio_temp:
            self.after_cancel(self._envio_temp)
        self._envio_temp = self.after(700, self._enviar_temp)

    def _enviar_temp(self) -> None:
        self._envio_temp = None
        valor = self.temp_previa
        if valor is None:
            return
        self.temp_previa = None
        self._otimista(temp_alvo=valor)
        self.ctl.executar(lambda ac: ac.definir_temperatura(valor))
