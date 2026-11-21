"""Janela simples para controlar o Daikin Smart AC pelo PC.

Abra com duplo clique (arquivo .pyw não mostra console) ou:
    python daikin_gui.pyw
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk

# Garante que daikin_ac.py seja encontrado mesmo se aberto de outra pasta
sys.path.insert(0, str(Path(__file__).resolve().parent))
if getattr(sys, "frozen", False):  # no .exe, logs ficam em %APPDATA%\DaikinSmartAC
    _pasta_log = Path(os.environ.get("APPDATA", str(Path.home()))) / "DaikinSmartAC"
    _pasta_log.mkdir(parents=True, exist_ok=True)
    LOG_ERRO = _pasta_log / "erro.log"
else:
    LOG_ERRO = Path(__file__).resolve().with_name("erro.log")


def _mostrar_erro_fatal(texto: str) -> None:
    """Sem console (.pyw), erros sumiriam: grava em erro.log e mostra janela."""
    try:
        LOG_ERRO.write_text(texto, encoding="utf-8")
    except OSError:
        pass
    raiz = tk.Tk()
    raiz.withdraw()
    messagebox.showerror(
        "Daikin Smart AC - erro ao abrir",
        f"{texto}\n\nPython usado: {sys.executable}\n"
        f"Detalhes salvos em: {LOG_ERRO}",
    )
    raiz.destroy()


try:
    from daikin_ac import (
        MODOS,
        PRESETS,
        VENTILADOR,
        DaikinAC,
        DaikinError,
        carregar_config,
        descobrir,
        salvar_config,
    )
except SystemExit as exc:  # daikin_ac sai com mensagem se faltar pyiotdevice
    _mostrar_erro_fatal(
        f"{exc}\n\nDica: rode o INSTALAR.bat de novo, ou no cmd:\n"
        f'"{sys.executable}" -m pip install -r requirements.txt'
    )
    sys.exit(1)
except Exception:  # noqa: BLE001
    _mostrar_erro_fatal(traceback.format_exc())
    sys.exit(1)

INTERVALO_MS = 10_000  # atualização automática (a integração oficial usa 10 s)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Daikin Smart AC")
        self.resizable(False, False)
        self.ac: DaikinAC | None = None
        self._ocupado = False
        self._atualizando_tela = False

        cfg = carregar_config()
        self.var_ip = tk.StringVar(value=cfg.get("ip", ""))
        self.var_chave = tk.StringVar(value=cfg.get("chave", ""))
        self.var_status = tk.StringVar(value="Desconectado")
        self.var_ambiente = tk.StringVar(value="-- °C")
        self.var_alvo = tk.IntVar(value=24)
        self.var_modo = tk.StringVar(value="frio")
        self.var_vent = tk.StringVar(value="auto")
        self.var_preset = tk.StringVar(value="nenhum")
        self.var_swing = tk.BooleanVar(value=False)
        self.var_ligado = tk.BooleanVar(value=False)

        self._montar()
        if self.var_ip.get() and self.var_chave.get():
            self.conectar()

    # ------------------------------------------------------------------ UI
    def _montar(self) -> None:
        pad = {"padx": 6, "pady": 4}

        conn = ttk.LabelFrame(self, text="Conexão")
        conn.grid(row=0, column=0, sticky="ew", **pad)
        ttk.Label(conn, text="IP:").grid(row=0, column=0, sticky="e")
        ttk.Entry(conn, textvariable=self.var_ip, width=18).grid(row=0, column=1, **pad)
        ttk.Button(conn, text="Descobrir", command=self.descobrir).grid(row=0, column=2, **pad)
        ttk.Label(conn, text="Device Key:").grid(row=1, column=0, sticky="e")
        ttk.Entry(conn, textvariable=self.var_chave, width=32, show="•").grid(
            row=1, column=1, columnspan=2, sticky="ew", **pad
        )
        ttk.Button(conn, text="Conectar e salvar", command=self.salvar_e_conectar).grid(
            row=2, column=1, columnspan=2, sticky="e", **pad
        )

        info = ttk.Frame(self)
        info.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Label(info, text="Ambiente:").pack(side="left")
        ttk.Label(info, textvariable=self.var_ambiente, font=("Segoe UI", 16, "bold")).pack(
            side="left", padx=8
        )
        ttk.Label(info, textvariable=self.var_status, foreground="gray").pack(side="right")

        ctl = ttk.LabelFrame(self, text="Controle")
        ctl.grid(row=2, column=0, sticky="ew", **pad)

        self.btn_power = ttk.Button(ctl, text="Ligar", width=12, command=self.alternar_energia)
        self.btn_power.grid(row=0, column=0, columnspan=3, **pad)

        ttk.Label(ctl, text="Temperatura:").grid(row=1, column=0, sticky="e")
        tframe = ttk.Frame(ctl)
        tframe.grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Button(tframe, text="−", width=3, command=lambda: self.ajustar_temp(-1)).pack(side="left")
        ttk.Label(tframe, textvariable=self.var_alvo, width=4, anchor="center",
                  font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Button(tframe, text="+", width=3, command=lambda: self.ajustar_temp(+1)).pack(side="left")
        ttk.Label(tframe, text="°C").pack(side="left", padx=4)

        ttk.Label(ctl, text="Modo:").grid(row=2, column=0, sticky="e")
        cb_modo = ttk.Combobox(ctl, textvariable=self.var_modo, values=list(MODOS),
                               state="readonly", width=14)
        cb_modo.grid(row=2, column=1, sticky="w", **pad)
        cb_modo.bind("<<ComboboxSelected>>",
                     lambda _e: self.executar(lambda ac: ac.definir_modo(self.var_modo.get())))

        ttk.Label(ctl, text="Ventilador:").grid(row=3, column=0, sticky="e")
        cb_vent = ttk.Combobox(ctl, textvariable=self.var_vent, values=list(VENTILADOR),
                               state="readonly", width=14)
        cb_vent.grid(row=3, column=1, sticky="w", **pad)
        cb_vent.bind("<<ComboboxSelected>>",
                     lambda _e: self.executar(lambda ac: ac.definir_ventilador(self.var_vent.get())))

        ttk.Label(ctl, text="Preset:").grid(row=4, column=0, sticky="e")
        cb_pre = ttk.Combobox(ctl, textvariable=self.var_preset, values=list(PRESETS),
                              state="readonly", width=14)
        cb_pre.grid(row=4, column=1, sticky="w", **pad)
        cb_pre.bind("<<ComboboxSelected>>",
                    lambda _e: self.executar(lambda ac: ac.definir_preset(self.var_preset.get())))

        ttk.Checkbutton(
            ctl, text="Swing vertical", variable=self.var_swing,
            command=lambda: self.executar(lambda ac: ac.definir_swing(self.var_swing.get())),
        ).grid(row=5, column=1, sticky="w", **pad)

        ttk.Button(self, text="Atualizar", command=self.atualizar).grid(
            row=3, column=0, sticky="e", **pad
        )

    # -------------------------------------------------------------- ações
    def salvar_e_conectar(self) -> None:
        salvar_config(self.var_ip.get().strip(), self.var_chave.get().strip())
        self.conectar()

    def conectar(self) -> None:
        try:
            self.ac = DaikinAC(self.var_ip.get(), self.var_chave.get())
        except DaikinError as exc:
            messagebox.showerror("Daikin", str(exc))
            return
        self.atualizar()
        self.after(INTERVALO_MS, self._loop)

    def _loop(self) -> None:
        if self.ac and not self._ocupado:
            self.atualizar()
        self.after(INTERVALO_MS, self._loop)

    def descobrir(self) -> None:
        self.var_status.set("Procurando na rede...")

        def tarefa() -> None:
            try:
                achados = descobrir()
            except DaikinError as exc:
                self.after(0, lambda: messagebox.showinfo("Daikin", str(exc)))
                self.after(0, lambda: self.var_status.set("Desconectado"))
                return
            def mostrar() -> None:
                if not achados:
                    messagebox.showinfo("Daikin", "Nenhum aparelho encontrado.")
                    self.var_status.set("Desconectado")
                    return
                self.var_ip.set(achados[0][1])
                lista = "\n".join(f"{ip}  —  {nome}" for nome, ip in achados)
                messagebox.showinfo("Daikin", f"Encontrado(s):\n{lista}")
                self.var_status.set("IP preenchido")
            self.after(0, mostrar)

        threading.Thread(target=tarefa, daemon=True).start()

    def alternar_energia(self) -> None:
        if self.var_ligado.get():
            self.executar(lambda ac: ac.desligar())
        else:
            self.executar(lambda ac: ac.ligar())

    def ajustar_temp(self, delta: int) -> None:
        novo = self.var_alvo.get() + delta
        self.var_alvo.set(novo)
        self.executar(lambda ac: ac.definir_temperatura(novo))

    def executar(self, acao) -> None:  # noqa: ANN001
        """Roda um comando numa thread e depois atualiza a tela."""
        if self._atualizando_tela:
            return
        if not self.ac:
            messagebox.showwarning("Daikin", "Conecte-se primeiro.")
            return
        ac = self.ac
        self._ocupado = True
        self.var_status.set("Enviando...")

        def tarefa() -> None:
            erro = None
            try:
                acao(ac)
            except DaikinError as exc:
                erro = str(exc)
            except Exception as exc:  # noqa: BLE001
                erro = f"Falha inesperada: {exc}"
            def fim() -> None:
                self._ocupado = False
                if erro:
                    messagebox.showerror("Daikin", erro)
                self.atualizar()
            self.after(0, fim)

        threading.Thread(target=tarefa, daemon=True).start()

    def atualizar(self) -> None:
        if not self.ac:
            return
        ac = self.ac

        def tarefa() -> None:
            try:
                st = ac.status()
                self.after(0, lambda: self._mostrar(st))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self.var_status.set(f"Offline: {exc}"[:60]))

        threading.Thread(target=tarefa, daemon=True).start()

    def _mostrar(self, st: dict) -> None:
        self._atualizando_tela = True
        try:
            self.var_ligado.set(st["ligado"])
            self.btn_power.configure(text="Desligar" if st["ligado"] else "Ligar")
            amb = st["temp_ambiente"]
            self.var_ambiente.set(f"{amb} °C" if amb is not None else "-- °C")
            if isinstance(st["temp_alvo"], (int, float)):
                self.var_alvo.set(int(st["temp_alvo"]))
            if st["modo"] in MODOS:
                self.var_modo.set(st["modo"])
            if st["ventilador"] in VENTILADOR:
                self.var_vent.set(st["ventilador"])
            self.var_preset.set("turbo" if st["turbo"] else "eco" if st["eco"] else "nenhum")
            self.var_swing.set(st["swing_vertical"])
            self.var_status.set(
                ("Ligado" if st["ligado"] else "Desligado") + f" · fw {st['firmware']}"
            )
        finally:
            self._atualizando_tela = False


def main() -> None:
    try:
        App().mainloop()
    except Exception:  # noqa: BLE001
        _mostrar_erro_fatal(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
