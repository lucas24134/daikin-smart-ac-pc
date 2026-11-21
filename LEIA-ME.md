# Daikin Smart AC no PC

Controle local do ar-condicionado Daikin Smart AC (Brasil) pelo Windows,
sem passar pela nuvem. Usa a biblioteca oficial `pyiotdevice` da Daikin Brasil
(a mesma da integração Home Assistant), que fala com o aparelho por HTTP
criptografado (AES) na porta **15914** da rede local.

## Virar um app do Windows (DaikinSmartAC.exe)

Dê duplo clique em **`CRIAR_EXE.bat`** (uma vez só, precisa do Python já
instalado pelo `INSTALAR.bat`). Ele cria o **`DaikinSmartAC.exe`** com ícone
próprio:

- Abre sem nenhuma janela de cmd; dá para abrir e fechar quando quiser.
- Se já estiver aberto, abrir de novo só mostra o painel.
- **Não precisa de Python**: para compartilhar, mande só o `DaikinSmartAC.exe`.
  Na primeira vez ele abre o assistente (atalho, IP e Device Key).
- As configurações ficam em `%APPDATA%\DaikinSmartAC\config.json`.

## 1. Instalar (1 clique)

Dê duplo clique em **`INSTALAR.bat`**. Ele instala o Python (via winget) se
o PC não tiver e abre o **assistente de configuração**, com 3 etapas:

1. **Instalar** — bibliotecas + atalho "Daikin Smart AC" na Área de Trabalho;
2. **Buscar IP** — acha o ar na rede e salva em `config.json` (ou digite o IP);
3. **Device Key** — cole a chave do app, ele testa a conexão e salva.

No final, clique em **Concluir**: o ícone do ar aparece ao lado do relógio.
Para reconfigurar, abra `assistente.pyw` de novo (ou menu do ícone → Configurar…).

## Ícone na barra de tarefas (bandeja)

- **Clique** no ícone: abre o **painel** acima do relógio — desenho do ar com
  animação (a aleta abre e o vento sai quando liga), temperatura grande com
  slider e botões −/+, e blocos de Modo, Ventilador, Eco/Turbo e Swing.
  Fecha ao clicar fora ou apertar Esc.
- **Botão direito**: menu rápido com ligar/desligar, temperatura ±1, modo,
  ventilador, Eco/Turbo, swing, janela completa, configurar e sair.
- **Passe o mouse**: estado, modo, temperatura alvo e do quarto.
- O número no ícone é a temperatura alvo; a cor indica o modo
  (azul = frio, laranja = calor, cinza = desligado, vermelho = sem conexão).
- Se não aparecer, clique na setinha **^** perto do relógio e arraste o ícone
  para a barra.
- Abrir com o Windows: marque a opção no final do assistente
  (ou `python daikin_ac.py bandeja-windows on|off`).

## 2. Obter a Device Key

No celular, app **Daikin Smart AC** → **Menu → Integrações → Home Assistant** →
escolha o SSID do aparelho (`DAIKINXXXXXX`) → **Enviar**. Copie a chave exibida.

O IP do ar pode ser achado com `python daikin_ac.py descobrir` ou na lista de
dispositivos do roteador. O PC precisa estar na mesma rede que o ar.

## 3. Usar

### Janela gráfica
Dê duplo clique em **`ABRIR.bat`** (recomendado) ou em `daikin_gui.pyw`, preencha
IP e Device Key e clique em **Conectar e salvar**. A tela se atualiza a cada 10 s.

### Linha de comando
```bash
python daikin_ac.py configurar --ip 192.168.0.50 --chave SUA_DEVICE_KEY
python daikin_ac.py status
python daikin_ac.py ligar
python daikin_ac.py desligar
python daikin_ac.py modo frio            # auto | seco | frio | calor | ventilar
python daikin_ac.py temp 23
python daikin_ac.py ventilador medio     # auto | alto | medio_alto | medio | medio_baixo | baixo | silencioso
python daikin_ac.py swing on             # opcional: --coanda on/off
python daikin_ac.py preset eco           # nenhum | eco | turbo
python daikin_ac.py bruto                # JSON cru do aparelho (diagnóstico)
```

A configuração fica em `config.json` (contém a Device Key — não compartilhe).
Também é possível usar as variáveis de ambiente `DAIKIN_IP` e `DAIKIN_CHAVE`.

## Regras do aparelho (iguais às do app/integração oficial)
- Temperatura: frio 18–32 °C, calor 10–30 °C, auto 18–30 °C; não se aplica a seco/ventilar.
- No modo seco o ventilador fica em auto.
- Com Turbo ativo não é possível mudar temperatura nem ventilador.
- Eco/Turbo só com o ar ligado.

## Como o protocolo foi identificado
Análise estática do APK `in.co.iotalabs.dmb.smartac` (endpoints locais
`:15914/acstatus`, `/device`, payload `{"port1": {...}}`) confirmada pelo código
aberto da integração oficial `github.com/daikin-br/ha-custom-integration` e da
biblioteca `github.com/daikin-br/pyiotdevice`.
