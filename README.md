# 🚔 Hype Police Discord Bot

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![discord.py](https://img.shields.io/badge/Library-discord.py-5865F2)
![Status](https://img.shields.io/badge/Status-Em%20Desenvolvimento-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

Bot desenvolvido para automação e gerenciamento operacional de
servidores Discord com estrutura hierárquica, atendimento interno e
registro de ocorrências.

Projetado com foco em organização, escalabilidade e facilidade de
manutenção.

------------------------------------------------------------------------

## 📌 Sobre o Projeto

O **Hype Police Bot** foi criado para auxiliar comunidades estruturadas
(RP policial, organizações administrativas e equipes operacionais)
oferecendo ferramentas completas de controle interno e automação.

O sistema utiliza arquitetura modular baseada em **Cogs**, permitindo
expansão rápida e manutenção simples.

------------------------------------------------------------------------

## ⚙️ Funcionalidades

### 🎫 Sistema de Tickets

-   Criação automática de canais de atendimento\
-   Controle de acesso por cargos\
-   Possibilidade de assumir tickets\
-   Organização por categorias configuráveis\
-   Fluxo estruturado de suporte

------------------------------------------------------------------------

### 📋 Sistema de Registros Operacionais

-   Registro de prisões / ocorrências\
-   Armazenamento organizado\
-   Logs automáticos em canais específicos\
-   Estrutura padronizada para controle interno

------------------------------------------------------------------------

### 🛠️ Painel Administrativo

-   Controle de permissões hierárquicas\
-   Configuração centralizada\
-   Gerenciamento de atendimentos e registros

------------------------------------------------------------------------

### ⚡ Arquitetura Modular

-   Separação por Cogs\
-   Sistema de permissões independente\
-   Configuração externa via JSON\
-   Fácil personalização

------------------------------------------------------------------------

## 🧠 Tecnologias Utilizadas

-   Python 3.10+
-   discord.py
-   JSON para configuração
-   Variáveis de ambiente (.env)
-   Estrutura modular com Cogs

------------------------------------------------------------------------

## 📁 Estrutura do Projeto

    📦 hype-police-discord
     ┣ 📂 cogs
     ┃ ┣ admin_panel.py
     ┃ ┣ tickets.py
     ┃ ┣ prisao.py
     ┣ 📂 utils
     ┃ ┣ config.py
     ┃ ┣ perm.py
     ┃ ┣ timeutils.py
     ┣ main.py
     ┣ config.json
     ┣ requirements.txt
     ┣ discloud.config
     ┗ README.md

------------------------------------------------------------------------

## 🚀 Instalação

### 1️⃣ Clonar repositório

    git clone https://github.com/seuusuario/Discord-bot-Police.git
    cd Discord-bot-Police

------------------------------------------------------------------------

### 2️⃣ Instalar dependências

    pip install -r requirements.txt

------------------------------------------------------------------------

### 3️⃣ Criar arquivo .env

Crie um arquivo `.env` na raiz:

    DISCORD_TOKEN=seu_token_aqui

------------------------------------------------------------------------

### 4️⃣ Executar o bot

    python main.py

------------------------------------------------------------------------

## 🔐 Segurança

⚠️ Nunca compartilhe seu token do Discord\
⚠️ O `.env` não deve ser versionado\
⚠️ Sempre utilize `.env.example` como modelo

------------------------------------------------------------------------

## ☁️ Deploy

O projeto possui suporte para deploy via:

-   Discloud\
-   VPS Linux\
-   Docker (planejado)

------------------------------------------------------------------------

## 📊 Roadmap

-   [ ] Sistema de ranking automático\
-   [ ] Banco de dados persistente\
-   [ ] Painel Web administrativo\
-   [ ] Dashboard de estatísticas\
-   [ ] Logs avançados\
-   [ ] Sistema de auditoria

------------------------------------------------------------------------

## 🤝 Contribuição

Contribuições são bem-vindas!

1.  Fork o projeto\
2.  Crie sua branch\
3.  Commit suas alterações\
4.  Abra um Pull Request

------------------------------------------------------------------------

## 📜 Licença

Este projeto está sob a licença MIT.

------------------------------------------------------------------------

## 👨‍💻 Autor

Desenvolvido por **Jhonatan Matos Schmitt**

------------------------------------------------------------------------

# ⭐ Se este projeto te ajudou, considere dar uma estrela no repositório!
