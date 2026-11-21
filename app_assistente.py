"""Assistente de configuração do Daikin Smart AC (3 etapas).

1. Instalar componentes  (bibliotecas + atalho na Área de Trabalho)
2. Buscar o IP do ar     (salva em config.json)
3. Device Key            (testa a conexão e salva em config.json)

Não depende das bibliotecas externas para abrir: elas são instaladas na etapa 1.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

CONGELADO = bool(getattr(sys, "frozen", False))  # rodando como DaikinSmartAC.exe
PASTA = Path(sys.executable).resolve().parent if CONGELADO else Path(__file__).resolve().parent
if CONGELADO:
    import os as _os

    PASTA_DADOS = Path(_os.environ.get("APPDATA", str(Path.home()))) / "DaikinSmartAC"
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
else:
    PASTA_DADOS = PASTA
CONFIG = PASTA_DADOS / "config.json"  # mesmo arquivo que daikin_ac.py usa
SEM_JANELA = 0x08000000  # CREATE_NO_WINDOW


def _rodar_interno(*args: str) -> tuple[int, str]:
    """No .exe não existe 'python': executa os comandos dentro do próprio app."""
    import contextlib
    import io

    if args[:1] in (("-c",), ("-m",)):
        return 0, "Componentes já incluídos no app."
    if args[:1] == ("daikin_ac.py",):
        import daikin_ac

        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
            try:
                codigo = daikin_ac.main(list(args[1:]))
            except SystemExit as exc:
                codigo = exc.code if isinstance(exc.code, int) else 1
            except Exception as exc:  # noqa: BLE001
                print(f"Erro: {exc}")
                codigo = 1
        return codigo or 0, saida.getvalue().strip()
    return 1, f"Comando não suportado: {args}"


def python_console() -> str:
    """python.exe ao lado do pythonw.exe (mesma instalação)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        alt = exe.with_name("python.exe")
        if alt.exists():
            return str(alt)
    return str(exe)


def rodar(*args: str, timeout: int = 600) -> tuple[int, str]:
    """Executa python com argumentos e devolve (código, saída)."""
    import os

    if CONGELADO:
        return _rodar_interno(*args)

    proc = subprocess.run(
        [python_console(), *args],
        cwd=PASTA,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=SEM_JANELA,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def ler_config() -> dict:
    try:
        dados = json.loads(CONFIG.read_text(encoding="utf-8-sig"))  # aceita BOM (Bloco de Notas)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_config(**campos: str) -> None:
    cfg = ler_config()
    cfg.update(campos)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


class Assistente(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Daikin Smart AC - Configuração")
        self.resizable(False, False)
        cfg = ler_config()
        self.var_ip = tk.StringVar(value=cfg.get("ip", ""))
        self.var_chave = tk.StringVar(value=cfg.get("chave", ""))
        self.ok = {1: False, 2: bool(cfg.get("ip")), 3: False}
        self._montar()
        self.after(100, self._verificar_instalado)

    # ------------------------------------------------------------- tela
    def _montar(self) -> None:
        ttk.Label(self, text="Configuração do Daikin Smart AC",
                  font=("Segoe UI", 14, "bold")).grid(row=0, column=0, padx=12, pady=(12, 2), sticky="w")
        ttk.Label(self, text="Siga as etapas na ordem. Cada uma libera a próxima.",
                  foreground="gray").grid(row=0, column=0, padx=12, pady=(40, 6), sticky="w")

        # Etapa 1
        f1 = ttk.LabelFrame(self, text=" 1. Instalar componentes ")
        f1.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        ttk.Label(f1, text=("Cria o atalho \"Daikin Smart AC\" na Área de Trabalho."
                            if CONGELADO else
                            "Instala as bibliotecas e cria o atalho na Área de Trabalho."),
                  wraplength=420).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self.btn1 = ttk.Button(f1, text="Instalar", command=self.etapa1)
        self.btn1.grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.st1 = ttk.Label(f1, text="Pendente", foreground="gray")
        self.st1.grid(row=1, column=1, sticky="w")
        self.log = tk.Text(f1, height=5, width=60, font=("Consolas", 8), state="disabled")
        self.log.grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 8))

        # Etapa 2
        f2 = ttk.LabelFrame(self, text=" 2. IP do ar-condicionado ")
        f2.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        ttk.Label(f2, text="O PC precisa estar no mesmo Wi-Fi que o ar. Clique em Buscar "
                           "ou digite o IP (lista de dispositivos do roteador).",
                  wraplength=420).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=4)
        self.btn2 = ttk.Button(f2, text="Buscar IP", command=self.etapa2_buscar)
        self.btn2.grid(row=1, column=0, padx=8, pady=6)
        ttk.Label(f2, text="IP:").grid(row=1, column=1, sticky="e")
        self.ent_ip = ttk.Entry(f2, textvariable=self.var_ip, width=18)
        self.ent_ip.grid(row=1, column=2, padx=4)
        self.btn2s = ttk.Button(f2, text="Salvar IP", command=self.etapa2_salvar)
        self.btn2s.grid(row=1, column=3, padx=8)
        self.st2 = ttk.Label(f2, text="Pendente", foreground="gray")
        self.st2.grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))

        # Etapa 3
        f3 = ttk.LabelFrame(self, text=" 3. Device Key ")
        f3.grid(row=3, column=0, padx=12, pady=6, sticky="ew")
        ttk.Label(f3, text="No celular: app Daikin Smart AC → Menu → Integrações → "
                           "Home Assistant → escolha o ar → Enviar. Copie a chave e cole aqui.",
                  wraplength=420).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Label(f3, text="Chave:").grid(row=1, column=0, sticky="e", padx=(8, 0))
        self.ent_chave = ttk.Entry(f3, textvariable=self.var_chave, width=40)
        self.ent_chave.grid(row=1, column=1, padx=4, pady=6)
        self.btn3 = ttk.Button(f3, text="Testar e salvar", command=self.etapa3)
        self.btn3.grid(row=1, column=2, padx=8)
        self.st3 = ttk.Label(f3, text="Pendente", foreground="gray")
        self.st3.grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        fim = ttk.Frame(self)
        fim.grid(row=4, column=0, padx=12, pady=(6, 12), sticky="ew")
        self.var_iniciar = tk.BooleanVar(value=True)
        ttk.Checkbutton(fim, text="Abrir o ícone da bandeja junto com o Windows",
                        variable=self.var_iniciar).pack(side="left")
        self.btn_abrir = ttk.Button(fim, text="Concluir  ▶", command=self.abrir_controle)
        self.btn_abrir.pack(side="right")
        self._atualizar_estados()

    def _status(self, rotulo: ttk.Label, texto: str, cor: str) -> None:
        rotulo.configure(text=texto, foreground=cor)

    def _escrever_log(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _atualizar_estados(self) -> None:
        def estado(ativo: bool) -> str:
            return "normal" if ativo else "disabled"

        for w in (self.btn2, self.ent_ip, self.btn2s):
            w.configure(state=estado(self.ok[1]))
        for w in (self.ent_chave, self.btn3):
            w.configure(state=estado(self.ok[1] and self.ok[2]))
        self.btn_abrir.configure(state=estado(all(self.ok.values())))
        if self.ok[2] and self.var_ip.get():
            self._status(self.st2, f"✔ IP salvo: {self.var_ip.get()}", "green")

    def _em_segundo_plano(self, tarefa, fim) -> None:  # noqa: ANN001
        def corre() -> None:
            try:
                resultado = tarefa()
                erro = None
            except Exception as exc:  # noqa: BLE001
                resultado, erro = None, str(exc)
            self.after(0, lambda: fim(resultado, erro))

        threading.Thread(target=corre, daemon=True).start()

    # ----------------------------------------------------------- etapa 1
    def _verificar_instalado(self) -> None:
        def tarefa() -> bool:
            codigo, _ = rodar("-c", "import pyiotdevice, zeroconf, pystray, PIL", timeout=60)
            return codigo == 0

        def fim(instalado, _erro) -> None:  # noqa: ANN001
            if instalado:
                self.ok[1] = True
                self._status(self.st1, "✔ Componentes já instalados", "green")
                self.btn1.configure(text="Reinstalar")
                self._atualizar_estados()

        self._em_segundo_plano(tarefa, fim)

    def etapa1(self) -> None:
        self.btn1.configure(state="disabled")
        self._status(self.st1, "Instalando... (pode levar 1-2 minutos)", "blue")
        self._escrever_log("> pip install -r requirements.txt")

        def tarefa() -> tuple[int, str, int, str]:
            c1, s1 = rodar("-m", "pip", "install", "--disable-pip-version-check",
                           "-r", "requirements.txt")
            if c1 != 0:
                return c1, s1, -1, ""
            c2, s2 = rodar("daikin_ac.py", "atalho", timeout=60)
            return c1, s1, c2, s2

        def fim(res, erro) -> None:  # noqa: ANN001
            self.btn1.configure(state="normal")
            if erro:
                self._escrever_log(erro)
                self._status(self.st1, "✖ Erro inesperado (veja acima)", "red")
                return
            c1, s1, c2, s2 = res
            self._escrever_log("\n".join(s1.splitlines()[-6:]))
            if c1 != 0:
                self._status(self.st1, "✖ Falha ao instalar. Verifique a internet.", "red")
                return
            self._escrever_log(s2 if c2 == 0 else f"Atalho não criado: {s2}")
            self.ok[1] = True
            self.btn1.configure(text="Reinstalar")
            self._status(self.st1, "✔ Instalado" + ("" if c2 == 0 else " (sem atalho)"), "green")
            self._atualizar_estados()

        self._em_segundo_plano(tarefa, fim)

    # ----------------------------------------------------------- etapa 2
    def etapa2_buscar(self) -> None:
        self.btn2.configure(state="disabled")
        self._status(self.st2, "Procurando aparelhos na rede...", "blue")

        def tarefa() -> tuple[int, str]:
            return rodar("daikin_ac.py", "descobrir", timeout=60)

        def fim(res, erro) -> None:  # noqa: ANN001
            self.btn2.configure(state="normal")
            if erro:
                self._status(self.st2, f"✖ {erro}", "red")
                return
            codigo, saida = res
            achados = [l.split("\t") for l in saida.splitlines() if "\t" in l]
            if codigo != 0 or not achados:
                self._status(self.st2, "✖ Nenhum ar encontrado. Digite o IP manualmente "
                                        "(veja no roteador) e clique em Salvar IP.", "red")
                return
            ip = achados[0][0]
            if len(achados) > 1:
                ip = self._escolher(achados) or ip
            self.var_ip.set(ip)
            self.etapa2_salvar()

        self._em_segundo_plano(tarefa, fim)

    def _escolher(self, achados: list[list[str]]) -> str | None:
        lista = "\n".join(f"{i + 1}) {ip}  —  {nome}" for i, (ip, nome, *_) in enumerate(achados))
        janela = tk.Toplevel(self)
        janela.title("Escolha o aparelho")
        ttk.Label(janela, text=f"Mais de um ar encontrado:\n{lista}").pack(padx=12, pady=8)
        escolha = tk.StringVar(value=achados[0][0])
        cb = ttk.Combobox(janela, textvariable=escolha, state="readonly",
                          values=[a[0] for a in achados])
        cb.pack(padx=12)
        ttk.Button(janela, text="OK", command=janela.destroy).pack(pady=8)
        janela.grab_set()
        self.wait_window(janela)
        return escolha.get()

    def etapa2_salvar(self) -> None:
        ip = self.var_ip.get().strip()
        partes = ip.split(".")
        if len(partes) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in partes):
            self._status(self.st2, "✖ IP inválido. Exemplo: 192.168.0.50", "red")
            return
        gravar_config(ip=ip)
        self.ok[2] = True
        self._atualizar_estados()

    # ----------------------------------------------------------- etapa 3
    def etapa3(self) -> None:
        chave = self.var_chave.get().strip()
        if len(chave) < 8:
            self._status(self.st3, "✖ Cole a Device Key completa.", "red")
            return
        self.btn3.configure(state="disabled")
        self._status(self.st3, "Testando conexão com o ar...", "blue")
        ip = self.var_ip.get().strip()

        def tarefa() -> tuple[int, str]:
            return rodar("daikin_ac.py", "--ip", ip, "--chave", chave, "status", timeout=40)

        def fim(res, erro) -> None:  # noqa: ANN001
            self.btn3.configure(state="normal")
            if erro:
                self._status(self.st3, f"✖ {erro}", "red")
                return
            codigo, saida = res
            if codigo != 0:
                detalhe = saida.splitlines()[-1][:120] if saida else ""
                self._status(self.st3, f"✖ Não conectou. Confira a chave e o IP.\n{detalhe}", "red")
                return
            gravar_config(chave=chave)
            self.ok[3] = True
            amb = next((l.split(":", 1)[1].strip() for l in saida.splitlines()
                        if l.startswith("Temp. ambiente")), "")
            self._status(self.st3, f"✔ Conectado e salvo! Temperatura do ambiente: {amb}", "green")
            self._atualizar_estados()

        self._em_segundo_plano(tarefa, fim)

    # ------------------------------------------------------------- final
    def abrir_controle(self) -> None:
        codigo, saida = rodar("daikin_ac.py", "bandeja-windows",
                              "on" if self.var_iniciar.get() else "off", timeout=60)
        if codigo != 0:
            messagebox.showwarning("Daikin", f"Não consegui configurar o início com o Windows:\n{saida}")
        if CONGELADO:
            subprocess.Popen([sys.executable], cwd=PASTA)  # o próprio .exe abre o ícone
        else:
            exe = Path(python_console()).with_name("pythonw.exe")
            subprocess.Popen([str(exe if exe.exists() else python_console()),
                              str(PASTA / "bandeja.pyw")], cwd=PASTA)
        messagebox.showinfo(
            "Daikin Smart AC",
            "Pronto! O ícone do ar apareceu ao lado do relógio, na barra de tarefas.\n\n"
            "• Clique nele: liga/desliga\n"
            "• Botão direito: menu (temperatura, modo, ventilador...)\n\n"
            "Se não aparecer, clique na setinha ^ perto do relógio e arraste o "
            "ícone para a barra.",
        )
        self.destroy()


def main() -> None:
    try:
        Assistente().mainloop()
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror("Assistente Daikin", str(exc))


if __name__ == "__main__":
    main()
