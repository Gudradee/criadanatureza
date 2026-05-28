# Deploy no Render

Este guia te leva do código local ao app rodando em produção.

## Antes de começar

Você vai precisar de:

- Conta no [GitHub](https://github.com) (gratuita)
- Conta no [Render](https://render.com) (gratuita)
- Git instalado localmente (já tem, está usando)
- Um valor aleatório para `CDN_SECRET_KEY` — gere com:
  ```powershell
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- Uma senha forte para o admin (ex.: gerador de senhas do navegador)
- *(Opcional)* Domínio próprio — pode comprar depois e configurar a qualquer momento

---

## Etapa 1 — Subir o código pro GitHub

Se o repositório ainda não está no GitHub:

```powershell
cd "C:\Users\Gusta\Downloads\criadanatureza-main\criadanatureza-main"
git status                # confirma que você está num repo git
git add -A
git commit -m "Preparado para deploy no Render"
```

Crie um repositório vazio no GitHub (sem README, sem .gitignore — já temos os nossos). Copie a URL e:

```powershell
git remote add origin https://github.com/SEU_USUARIO/criadanatureza.git
git branch -M main
git push -u origin main
```

> Se já existe remoto e branch, é só `git push`.

---

## Etapa 2 — Criar o serviço no Render

1. Acesse [dashboard.render.com](https://dashboard.render.com)
2. Clique em **New +** → **Blueprint**
3. Em **Connect a repository**, autorize o GitHub e selecione o repo
4. O Render lê automaticamente o [render.yaml](render.yaml) do repo
5. Confirme a criação do serviço **cdn-app**

Nesse momento o Render começa o primeiro build. Vai falhar logo — porque ainda faltam as env vars secretas. Tudo bem.

---

## Etapa 3 — Configurar as variáveis secretas

No painel do serviço **cdn-app**:

1. **Settings** → **Environment** → **Add Environment Variable**
2. Adicione **duas variáveis** (que estão como `sync: false` no render.yaml):

   | Key | Value |
   |---|---|
   | `CDN_SECRET_KEY` | (cole o valor que você gerou com `secrets.token_hex(32)`) |
   | `ADMIN_PASSWORD` | (a senha forte que você escolheu para o admin) |

3. Clique em **Save Changes** — o Render dispara um novo deploy automaticamente

> As outras env vars (`DATABASE_PATH`, `UPLOADS_DIR`, `ADMIN_USERNAME`, `FLASK_DEBUG`) já vieram do render.yaml. Não precisa setar manualmente.

---

## Etapa 4 — Acompanhar o deploy

No painel, aba **Logs**. Você verá algo como:

```
==> Build successful
==> Starting service with 'gunicorn -w 2 -b 0.0.0.0:$PORT main:app'
[CDN] Admin 'admin' criado a partir do .env.
==> Your service is live 🎉
```

Quando aparecer **Your service is live**, abra a URL que o Render mostra no topo do painel (algo tipo `https://cdn-app.onrender.com`).

Vai cair na tela de login. Use:

- **Usuário**: `admin`
- **Senha**: a `ADMIN_PASSWORD` que você setou

---

## Etapa 5 — Configurar seu domínio (opcional, faça quando comprar)

Quando tiver o domínio:

1. **Settings** → **Custom Domain** → **Add Custom Domain**
2. Digite seu domínio (ex.: `app.criadanatureza.com.br`)
3. O Render mostra os registros DNS que você precisa criar no painel do seu registrador (Registro.br, GoDaddy, etc.):
   - `CNAME` apontando para `cdn-app.onrender.com`
   - Ou `A` record para um IP específico
4. Aguarde a propagação DNS (até 1h) — o Render gera o certificado HTTPS automaticamente

---

## Sobre o teste grátis de 2 dias

Antes de assinar o Starter ($7/mês), você pode rodar no **Free** com algumas limitações:

### O que mudar no render.yaml para o teste grátis

Edite [render.yaml](render.yaml) **antes** de criar o Blueprint:

1. Troque `plan: starter` por `plan: free`
2. **Delete inteiro** o bloco `disks:` (das linhas que começam com `disks:` até o `sizeGB: 1`)
3. **Delete** as env vars `DATABASE_PATH` e `UPLOADS_DIR` (sem disco persistente, o app usa os defaults locais que ficam dentro do container)

### Limitações do plano Free

- **Banco e imagens são apagados** sempre que o serviço dorme ou faz deploy novo. É volátil.
- App **dorme após 15 min** de inatividade → cold start de 30-60s na próxima requisição
- Útil só pra ver UI funcionando, **não** pra dados reais

### Upgrade pro Starter (quando quiser)

1. Reverta o render.yaml pro estado original (com `disks:` e as env vars de path)
2. **Commit + push** — o Render aplica
3. No painel do serviço: **Settings** → **Instance Type** → **Starter**
4. **Settings** → **Disks** → **Add Disk** (se o render.yaml ainda não tiver criado):
   - Name: `cdn-data`
   - Mount Path: `/data`
   - Size: `1 GB`
5. **Redeploy manual** (botão **Manual Deploy** no topo)

Pronto. A partir daí o `cdn.db` vive em `/data/cdn.db` e persiste pra sempre.

---

## Variáveis de ambiente — referência completa

| Variável | Origem | Valor em produção |
|---|---|---|
| `CDN_SECRET_KEY` | Setado manualmente | (hex 64 caracteres, segredo) |
| `ADMIN_USERNAME` | render.yaml | `admin` |
| `ADMIN_PASSWORD` | Setado manualmente | (senha forte, segredo) |
| `DATABASE_PATH` | render.yaml (Starter) | `/data/cdn.db` |
| `UPLOADS_DIR` | render.yaml (Starter) | `/data/uploads` |
| `FLASK_DEBUG` | render.yaml | `0` |
| `PYTHON_VERSION` | render.yaml | `3.11.9` |
| `PORT` | Setado pelo Render automaticamente | (dinâmico) |

---

## Operação do dia-a-dia

### Atualizar o código

```powershell
git add -A
git commit -m "Descrição da mudança"
git push
```

Render detecta o push, faz build e deploy. Você acompanha pelo dashboard ou pelo terminal de Logs.

### Ver os logs

No dashboard do serviço → aba **Logs** (tempo real).

### Backup do banco

No painel do serviço → aba **Shell** (abre um terminal no container):

```bash
ls /data
# baixe via "Download" do painel de Disks, ou:
sqlite3 /data/cdn.db ".backup '/data/backup-$(date +%F).db'"
```

Pra puxar pra sua máquina, use o painel de Disks → **Download File**.

### Restaurar a senha do admin

Se esquecer a senha:

1. **Settings** → **Environment**
2. Atualize `ADMIN_PASSWORD` com a nova senha
3. **Manual Deploy** — o `_sync_admin()` reseta a senha no próximo boot

---

## Solução de problemas

| Sintoma | Provável causa | Como resolver |
|---|---|---|
| Build falha em "pip install" | Versão do Python errada | Confirme `PYTHON_VERSION` = `3.11.9` |
| App sobe mas erro 500 ao logar | `CDN_SECRET_KEY` faltando ou no placeholder | Setar no Environment |
| "service waking up" toda hora | Está no plano Free | Upgrade pro Starter |
| Imagens de produtos somem | Sem persistent disk OU `UPLOADS_DIR` aponta pra lugar errado | Verificar disk montado + env var |
| Banco "esquece" tudo após deploy | Sem persistent disk OU `DATABASE_PATH` aponta pra lugar errado | Verificar disk montado + env var |
