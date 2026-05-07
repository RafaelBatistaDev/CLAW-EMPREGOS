# 🤖 Job Hunter Bot v1.0.0

Bot de busca de vagas de emprego em múltiplas plataformas.
Salva resultados em **JSON** e **CSV** com deduplicação automática.

## Plataformas Suportadas

    python app.py

# Ou matar tudo que usa a 5000 de uma vez
fuser -k 5000/tcp

# Depois sobe normalmente
python app.py


/var/home/recifecrypto/Onedrive/Projetos/CLAW\ -\ Empregos/.venv/bin/python app.py
/var/home/recifecrypto/OneDrive/Projetos/CLAW\ -\ Empregos/.venv/bin/python /var/home/recifecrypto/OneDrive/Projetos/CLAW\ -\ Empregos/app.py


    python app.py
    Após executar, o terminal deve mostrar uma mensagem indicando que o servidor está rodando, geralmente em http://127.0.0.1:5000/ ou http://localhost:5000/.
    4.
Abra seu navegador e vá para http://localhost:5000/.

| Plataforma | Método         | Status        |
|------------|----------------|---------------|
| Gupy       | API pública    | ✅ Estável    |
| LinkedIn   | Guest endpoint | ✅ Funcional  |
| Indeed BR  | HTML scraping  | ⚠️ Frágil*   |
| InfoJobs   | HTML scraping  | ⚠️ Frágil*   |
> *Sites que fazem scraping HTML podem quebrar quando o site atualiza seu layout.

---

## Instalação no Fedora Kinoite/COSMIC

### Opção 1 — Distrobox (recomendado)

```bash
# Criar container de desenvolvimento
distrobox create --name dev-python --image registry.fedoraproject.org/fedora:latest
distrobox enter dev-python

# Dentro do container
pip install -r requirements.txt
python3 job_hunter.py
```

### Opção 2 — venv local

```bash
python3 -m venv ~/.venvs/job_hunter
source ~/.venvs/job_hunter/bin/activate
pip install -r requirements.txt
python3 job_hunter.py
```

### Opção 3 — pip direto no sistema (não recomendado no Kinoite)

```bash
pip install requests beautifulsoup4 lxml --break-system-packages
```

---

## Configuração

Edite `config_vagas.json` antes de rodar:

```json
{
  "keywords": ["sua profissão", "sua área"],
  "localizacao": "Recife, PE",
  "max_vagas_por_plataforma": 20,
  "delay_entre_requisicoes": 2.5,
  "plataformas": ["gupy", "linkedin", "indeed", "infojobs"]
}
```

---

## Uso

```bash
# Básico — usa config_vagas.json
python3 job_hunter.py

# Configuração alternativa
python3 job_hunter.py --config outra_config.json

# Sobrescrever via CLI
python3 job_hunter.py --keywords "python" "django" --local "São Paulo"
python3 job_hunter.py --plataformas gupy linkedin
python3 job_hunter.py --max 30

# Ver ajuda
python3 job_hunter.py --help
```

---

## Saída

Os resultados ficam em `vagas/` com timestamp:

```
vagas/
├── vagas_20250501_143022.json   ← Estruturado com metadados
└── vagas_20250501_143022.csv    ← Abre direto no LibreOffice/Excel
```

Log em: `~/.local/log/job_hunter_YYYYMMDD_HHMMSS.log`

---

- **instaloader**: `pip install instaloader` — monitora perfis/hashtags com login
- **Playwright**: navegador headless com login completo
- **Manual**: seguir `#vagas` `#emprego` `#tech` no app

---

## Automatizar com systemd (rodar diariamente)

```bash
# ~/.config/systemd/user/job_hunter.service
[Unit]
Description=Job Hunter Bot

[Service]
Type=oneshot
WorkingDirectory=/caminho/para/job_hunter
ExecStart=/usr/bin/python3 job_hunter.py
Environment=HOME=%h

# ~/.config/systemd/user/job_hunter.timer
[Unit]
Description=Rodar Job Hunter diariamente

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now job_hunter.timer
systemctl --user status job_hunter.timer
```
