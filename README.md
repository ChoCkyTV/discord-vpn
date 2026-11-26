# Discord VPN

## Usar
1. Coloque o `DiscordVPN.exe` numa pasta fixa (ex.: `C:\Programas\DiscordVPN`) e execute (pede admin uma vez).
2. Selecione o `.conf` quando pedir.
3. Pronto: ele registra a inicialização com o Windows (tarefa agendada, sem UAC), conecta a VPN e só então abre o Discord.
4. No Discord, desative **Configurações → Configurações do Windows → Abrir Discord**, para ele não abrir antes da VPN.

Menu da bandeja: conectar/desconectar, abrir Discord, **Diagnóstico** (mostra quantas conexões do Discord passam pela VPN), trocar o `.conf`, opções de inicialização.

## Avisos
- Todo o tráfego do PC passa pelo adaptador TUN (o que não é Discord sai direto), com pequeno custo de desempenho.
- Antivírus podem alertar (exe do PyInstaller + núcleo de proxy). Se acontecer, adicione exceção na pasta.
- Logs do núcleo: `%APPDATA%\DiscordVPN\core\core.log`.

## Arquivo .conf da PROTON VPN

1. Entrar na sua conta Proton
Abra account.protonvpn.com e faça login com a conta Free.
No menu da esquerda, clique em Downloads. https://account.protonvpn.com/downloads

2. Criar a configuração WireGuard
Role a página até a seção WireGuard configuration.
Em Name, dê um nome qualquer, por exemplo discord.
Em Select platform, escolha Windows.
Nas opções (NetShield, Moderate NAT, NAT-PMP, VPN Accelerator), deixe tudo como está.
Em Select a server to connect to, escolha um servidor Free. Eles aparecem marcados como Free, em poucos países. Escolha o mais perto de você para ter menos latência na voz.
Clique em Create e depois em Download. Vai baixar um arquivo .conf, algo como discord-US-FREE-1.conf.

Não confirmei que toda conta Free permite gerar esse arquivo. Se a página não mostrar servidores Free ou der erro ao criar, me avise.

3. Guardar o arquivo

Mova o .conf para uma pasta sua, como C:\Programas\DiscordVPN.
Ele contém sua chave privada. Não envie para ninguém e não suba no GitHub. O .gitignore do projeto já bloqueia arquivos .conf.

4. Usar no programa

Execute o DiscordVPN.exe e aceite o pedido de administrador.
Na primeira vez, abre uma janela pedindo o arquivo. Se não abrir, clique com o botão direito no ícone da bandeja (perto do relógio) e vá em Importar .conf WireGuard (Proton)….
Selecione o .conf e confirme.
O ícone fica amarelo (conectando) e depois verde (ativa). Nesse momento ele abre o Discord sozinho.

5. Conferir se funcionou

Com o Discord aberto, clique com o botão direito no ícone da bandeja e abra Diagnóstico (conexões do Discord).
A janela deve mostrar as conexões "pela VPN" com número maior que zero e "diretas" zeradas, ou quase.

Se der problema

Ícone vermelho: abra %APPDATA%\DiscordVPN\core\core.log (cole isso na barra do Explorer) e me mande as últimas linhas.
Arquivo recusado: o programa mostra qual campo está faltando. Baixe o .conf de novo na Proton.
Trocar de servidor depois: gere outro .conf na Proton e importe de novo pelo menu da bandeja. Ele substitui o anterior e reconecta.
