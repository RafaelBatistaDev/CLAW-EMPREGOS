#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome do Script  : scrapers_extras_pe.py
Descrição       : Scrapers adicionais para fontes de vagas de Pernambuco.
                  Inclui: Jobrapido.
Autor           : recifecrypto
Versão          : 1.2.0
Compatibilidade : Fedora Kinoite / Silverblue / COSMIC (Atomic)
                  Python 3.11+ | Mesmo venv/Distrobox do job_hunter.py

Notas de compatibilidade
─────────────────────────
| Scraper      | Tipo HTML | Risco de bloqueio | Observação               |
|--------------|-----------|-------------------|--------------------------|
| Jobrapido    | SSR       | Médio             | Parâmetros de busca URL  |
"""

# ─────────────────────────────────────────────
# 1. IMPORTS
# ─────────────────────────────────────────────
import json
import logging
import re
import sys
import time
from abc import abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("\033[1;31m[ERRO]\033[0m Dependências ausentes. Execute:")
    print("  pip install requests beautifulsoup4 --break-system-packages")
    sys.exit(1)

# ─────────────────────────────────────────────
# 2. CONSTANTES
# ─────────────────────────────────────────────
USER_HOME       = Path.home()
REQUEST_TIMEOUT = 15

HEADERS_HTTP: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────────────────────
# 3. CORES
# ─────────────────────────────────────────────
class Color:
    G = "\033[1;32m"; B = "\033[1;34m"; Y = "\033[1;33m"
    R = "\033[1;31m"; C = "\033[1;36m"; N = "\033[0m"

# ─────────────────────────────────────────────
# 4. LOG
# ─────────────────────────────────────────────
logger = logging.getLogger("job_hunter")

def log(m: str)     -> None: logger.info(f"{Color.B}[INFO]{Color.N}    {m}")
def success(m: str) -> None: logger.info(f"{Color.G}[OK]{Color.N}      {m}")
def warn(m: str)    -> None: logger.warning(f"{Color.Y}[AVISO]{Color.N}  {m}")
def error(m: str)   -> None: logger.error(f"{Color.R}[ERRO]{Color.N}   {m}")
def debug(m: str)   -> None: logger.debug(f"{Color.C}[DEBUG]{Color.N}  {m}")

# ─────────────────────────────────────────────
# 5. IMPORTA BASE — usa job_hunter se disponível
# ─────────────────────────────────────────────
try:
    from job_hunter import Vaga, BaseScraper   # type: ignore
    from scrapers_pe import StaticUrlScraper   # type: ignore
except ImportError:
    import hashlib
    from abc import ABC, abstractmethod

    @dataclass
    class Vaga:  # type: ignore[no-redef]
        titulo:        str
        empresa:       str
        localizacao:   str
        url:           str
        plataforma:    str
        descricao:     str = ""
        salario:       str = ""
        data_postagem: str = ""
        data_busca:    str = field(
            default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        )
        id_unico:  str = field(default="", init=False)
        categoria: str = field(default="", init=False)

        def __post_init__(self) -> None:
            raw = f"{self.titulo.lower()}{self.empresa.lower()}{self.plataforma}"
            self.id_unico = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

        def to_dict(self) -> dict:
            return asdict(self)

    class BaseScraper(ABC):  # type: ignore[no-redef]
        nome: str = "Base"

        def __init__(
            self,
            keywords:    list[str],
            localizacao: str,
            max_vagas:   int   = 20,
            delay:       float = 2.0,
        ) -> None:
            self.keywords    = keywords
            self.localizacao = localizacao
            self.max_vagas   = max_vagas
            self.delay       = delay
            self.session     = requests.Session()
            self.session.headers.update(HEADERS_HTTP)

        def _get(
            self, url: str, params: dict | None = None
        ) -> requests.Response | None:
            time.sleep(self.delay)
            debug(f"GET {url} | params={params}")
            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp
            except requests.exceptions.Timeout:
                warn(f"[{self.nome}] Timeout ({REQUEST_TIMEOUT}s): {url}")
            except requests.exceptions.HTTPError as e:
                warn(f"[{self.nome}] HTTP {e.response.status_code}: {url}")
            except requests.exceptions.ConnectionError:
                error(f"[{self.nome}] Sem conexão: {url}")
            except requests.exceptions.RequestException as e:
                error(f"[{self.nome}] Erro: {e}")
            return None

        @abstractmethod
        def buscar(self) -> list[Vaga]: ...

    class StaticUrlScraper(BaseScraper):  # type: ignore[no-redef]
        nome: str       = "StaticUrl"
        URLS: list[str] = []

        @abstractmethod
        def _extrair(self, soup: BeautifulSoup, url: str) -> list[Vaga]: ...

        def buscar(self) -> list[Vaga]:
            vagas: list[Vaga] = []
            for url in self.URLS:
                resp = self._get(url)
                if not resp:
                    continue
                soup        = BeautifulSoup(resp.text, "html.parser")
                encontradas = self._extrair(soup, url)[: self.max_vagas]
                if encontradas:
                    success(f"[{self.nome}] {len(encontradas)} vagas → {url}")
                else:
                    warn(f"[{self.nome}] Sem vagas (seletor pode ter mudado) → {url}")
                vagas.extend(encontradas)
            return vagas


# ═══════════════════════════════════════════════════════════════
# SCRAPER 13 — Jobrapido
# ═══════════════════════════════════════════════════════════════

class JobrapidoScraper(BaseScraper):
    """
    Coleta vagas do Jobrapido para Pernambuco/Recife.

    URL base  : https://br.jobrapido.com/?w={kw}&l=recife
    Motor     : SSR — HTML com paginação e filtro por localização
    Filtro    : Parâmetros de URL (w=keyword, l=localidade)
    """

    nome     = "Jobrapido"
    BASE_URL = "https://br.jobrapido.com"
    HOST     = "https://br.jobrapido.com"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []

        for kw in self.keywords:
            resp = self._get(
                self.BASE_URL,
                params={
                    "w": kw,
                    "l": "Recife",
                    "r": "25",  # raio em km
                },
            )
            if not resp:
                continue

            soup  = BeautifulSoup(resp.text, "html.parser")
            cards = (
                soup.select("article.js_result, .result, li.result")
                or soup.select("[class*='job-card'], [class*='jobCard']")
                or soup.select("div[data-job-id], li[data-id]")
            )

            if not cards:
                debug(
                    f"[Jobrapido] Sem cards para '{kw}'. "
                    f"HTML: {soup.title.get_text() if soup.title else 'sem título'}"
                )
                continue

            for card in cards[: self.max_vagas]:
                try:
                    titulo_el  = card.select_one(
                        "h2 a, h3 a, .title a, [class*='title'] a, [itemprop='title']"
                    )
                    empresa_el = card.select_one(
                        "[itemprop='hiringOrganization'], .company, [class*='company']"
                    )
                    local_el   = card.select_one(
                        "[itemprop='addressLocality'], .location, [class*='location']"
                    )
                    salario_el = card.select_one(
                        "[itemprop='baseSalary'], .salary, [class*='salary']"
                    )
                    data_el    = card.select_one(
                        "time[datetime], [class*='date'], [class*='data']"
                    )

                    if not titulo_el:
                        continue

                    href = titulo_el.get("href", "")
                    url  = href if href.startswith("http") else f"{self.HOST}{href}"

                    data_post = ""
                    if data_el:
                        data_post = data_el.get("datetime") or data_el.get_text(strip=True)

                    vagas.append(Vaga(
                        titulo        = titulo_el.get_text(strip=True),
                        empresa       = empresa_el.get_text(strip=True) if empresa_el else "N/D",
                        localizacao   = local_el.get_text(strip=True) if local_el else "Recife - PE",
                        url           = url,
                        plataforma    = "Jobrapido",
                        salario       = salario_el.get_text(strip=True) if salario_el else "",
                        data_postagem = data_post,
                    ))

                except (AttributeError, KeyError) as e:
                    debug(f"[Jobrapido] Erro no card: {e}")

        if vagas:
            success(f"[Jobrapido] {len(vagas)} vagas coletadas.")
        else:
            warn("[Jobrapido] Sem vagas — verifique parâmetros de URL e seletores.")

        return vagas


# ═══════════════════════════════════════════════════════════════
# REGISTRO — SCRAPERS_EXTRAS_PE
# Mesclado com SCRAPERS_PE em scrapers_pe.py
# ═══════════════════════════════════════════════════════════════

SCRAPERS_EXTRAS_PE: dict[str, type[BaseScraper]] = {
    "jobrapido":  JobrapidoScraper,
}


# ═══════════════════════════════════════════════════════════════
# TESTE STANDALONE
# Uso: python3 scrapers_extras_pe.py --scraper jobrapido
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.DEBUG, format="%(message)s")

    parser = argparse.ArgumentParser(description="Testar scrapers extras PE individualmente.")
    parser.add_argument(
        "--scraper", "-s",
        choices=list(SCRAPERS_EXTRAS_PE.keys()),
        default="jobrapido",
        help="Qual scraper testar (padrão: jobrapido)",
    )
    parser.add_argument(
        "--max", "-m",
        type=int,
        default=5,
        help="Máximo de vagas por plataforma (padrão: 5)",
    )
    args = parser.parse_args()

    KEYWORDS = ["Porteiro", "Vigia", "Fiscal de Loja", "Prevenção de Perdas"]
    LOCAL    = "Recife, PE"

    cls     = SCRAPERS_EXTRAS_PE[args.scraper]
    scraper = cls(keywords=KEYWORDS, localizacao=LOCAL, max_vagas=args.max, delay=1.5)

    print(f"\n{'═' * 60}")
    print(f"  Testando: {cls.__name__}")
    print(f"{'═' * 60}\n")

    vagas = scraper.buscar()

    print(f"\n{'─' * 60}")
    print(f"  Total: {len(vagas)} vagas")
    print(f"{'─' * 60}")

    for i, v in enumerate(vagas, 1):
        print(f"\n[{i}] {v.titulo}")
        print(f"    Empresa   : {v.empresa}")
        print(f"    Local     : {v.localizacao}")
        print(f"    Salário   : {v.salario or 'N/D'}")
        print(f"    Postado em: {v.data_postagem or 'N/D'}")
        print(f"    URL       : {v.url}")