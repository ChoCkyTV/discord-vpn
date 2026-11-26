# Discord VPN

Usa a **Proton VPN Free** somente no Discord, com **login automático**. O resto do PC continua na conexão normal.

## Como funciona
- Você entra com usuário e senha da Proton (a senha **não é salva**; fica só a sessão).
- O programa pede à Proton os **3 melhores servidores Free** para a sua localização (validados por ping) e usa o de menor latência.
- Um núcleo (mihomo) cria um adaptador de rede e manda para o túnel **apenas** `Discord.exe` (e PTB/Canary). Voz e chat passam pela VPN.
- Se a VPN cair, o Discord fica sem rede (não vaza seu IP real). O IPv6 do Discord é bloqueado.
- As rotas vencem em 7 dias; o programa renova sozinho em segundo plano (usa a sessão, sem pedir a senha).
- Inicia com o Windows (tarefa agendada, sem UAC), conecta a VPN e só depois abre o Discord.

## Usar
1. Coloque o `DiscordVPN.exe` numa pasta fixa (ex.: `C:\Programas\DiscordVPN`) e execute (pede admin uma vez).
2. Na primeira vez abre a janela de login. Entre com a conta Proton e aguarde 1 a 2 minutos.
3. No Discord, desative **Configurações → Configurações do Windows → Abrir Discord**.

Se tiver 2FA, digite o código de 6 dígitos do app autenticador (chaves de segurança FIDO2 não funcionam). Se a Proton pedir captcha, entre uma vez em account.proton.me no navegador e tente de novo. Também dá para importar `.conf` manualmente (menu Mais opções).

## Licenças
O login usa o helper `proton-confgen`, GPL-3.0, de https://github.com/bezumiya/GoLiveBypass (commit fixado no `build.yml`), baseado em https://github.com/hatemosphere/protonvpn-wg-confgen. O .exe inclui esse programa e o mihomo (GPL-3.0); o código-fonte está nesses links.

## Avisos
- Cliente não oficial: o helper se identifica como o app Linux da Proton. A Proton pode bloquear versões antigas (o programa avisa para atualizar).
- Antivírus podem alertar (exe do PyInstaller + núcleo de proxy). Crie exceção na pasta se acontecer.
- Logs: `%APPDATA%\DiscordVPN\core\core.log`.
