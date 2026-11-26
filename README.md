# Discord VPN

Usa a **Proton VPN Free (WireGuard)** somente no Discord. O resto do PC continua na conexão normal.

## Como funciona
- Um núcleo (mihomo) cria um adaptador de rede (TUN) e manda para o túnel WireGuard da Proton **apenas** os processos `Discord.exe` (e PTB/Canary). Voz (UDP) e chat passam pela VPN.
- O programa fica na bandeja do Windows. Se a VPN cair, o Discord fica sem rede (não vaza seu IP real).
- IPv6 do Discord é bloqueado (o túnel é IPv4), então ele usa IPv4 pela VPN.

## Gerar o .exe no GitHub
1. Crie um repositório e envie estes arquivos (mantendo `.github/workflows/build.yml`).
2. Aba **Actions** → o build roda sozinho a cada push. Baixe o `DiscordVPN.exe` em *Artifacts*.
3. Para publicar em **Releases**: `git tag v1.0.0 && git push origin v1.0.0`.

## Configurar a Proton (v1.1: vários servidores)
1. Em account.protonvpn.com → **Downloads → WireGuard configuration**.
2. Plataforma **Windows**. Crie e baixe **3 a 5** `.conf` de servidores **Free** diferentes (ex.: os de menor carga).
3. Na bandeja: **Adicionar .conf (Proton)…** e selecione todos de uma vez.
4. O programa mede a latência de cada um e usa o melhor para o seu PC. Para refazer a medição: **Testar servidores e usar o melhor**.

## Usar
1. Coloque o `DiscordVPN.exe` numa pasta fixa (ex.: `C:\Programas\DiscordVPN`) e execute (pede admin uma vez).
2. Selecione os `.conf` quando pedir.
3. Pronto: ele registra a inicialização com o Windows (tarefa agendada, sem UAC), conecta a VPN e só então abre o Discord.
4. No Discord, desative **Configurações → Configurações do Windows → Abrir Discord**, para ele não abrir antes da VPN.

Menu da bandeja: conectar/desconectar, abrir Discord, **Diagnóstico** (mostra quantas conexões do Discord passam pela VPN), trocar o `.conf`, opções de inicialização.

## Avisos
- Todo o tráfego do PC passa pelo adaptador TUN (o que não é Discord sai direto), com pequeno custo de desempenho.
- Antivírus podem alertar (exe do PyInstaller + núcleo de proxy). Se acontecer, adicione exceção na pasta.
- Logs do núcleo: `%APPDATA%\DiscordVPN\core\core.log`.
