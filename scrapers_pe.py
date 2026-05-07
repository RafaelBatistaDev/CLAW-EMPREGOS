#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome do Script  : scrapers_pe.py
Descrição       : Scrapers adicionais para fontes de vagas de Pernambuco.
                  Inclui: EmpregoPE, ComunidadeEmpregoPE,
                  InformeVagasPE (RSS/Blogspot), Google News RSS (Concursos).
Autor           : recifecrypto
Versão          : 1.2.0
Compatibilidade : Fedora Kinoite / Silverblue / COSMIC (Atomic)
                  Python 3.11+ | Mesmo venv/Distrobox do job_hunter.py
"""

# ─────────────────────────────────────────────
# 1. IMPORTS
# ─────────────────────────────────────────────
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
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
HEADERS_HTTP    = {
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
import logging
logger = logging.getLogger("job_hunter")

def log(m: str)     -> None: logger.info(f"{Color.B}[INFO]{Color.N}    {m}")
def success(m: str) -> None: logger.info(f"{Color.G}[OK]{Color.N}      {m}")
def warn(m: str)    -> None: logger.warning(f"{Color.Y}[AVISO]{Color.N}  {m}")
def error(m: str)   -> None: logger.error(f"{Color.R}[ERRO]{Color.N}   {m}")
def debug(m: str)   -> None: logger.debug(f"{Color.C}[DEBUG]{Color.N}  {m}")


# ═══════════════════════════════════════════════════════════════
# DATA CLASS — importado do job_hunter se usado como módulo,
# redefinido aqui para uso standalone em testes.
# ═══════════════════════════════════════════════════════════════
try:
    from job_hunter import Vaga, BaseScraper  # type: ignore
except ImportError:
    import hashlib

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
        data_coleta:   str = field(default_factory=lambda: datetime.now().isoformat())
        id_unico:      str = field(default="", init=False)
        categoria:     str = field(default="", init=False)

        def __post_init__(self) -> None:
            raw = f"{self.titulo.lower()}{self.empresa.lower()}{self.plataforma}"
            self.id_unico = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

        def to_dict(self) -> dict:
            return asdict(self)

    from abc import ABC, abstractmethod

    class BaseScraper(ABC):  # type: ignore[no-redef]
        nome: str = "Base"

        def __init__(
            self,
            keywords: list[str],
            localizacao: str,
            max_vagas: int = 20,
            delay: float = 2.0,
        ) -> None:
            self.keywords    = keywords
            self.localizacao = localizacao
            self.max_vagas   = max_vagas
            self.delay       = delay
            self.session     = requests.Session()
            self.session.headers.update(HEADERS_HTTP)

        def _get(self, url: str, params: dict | None = None) -> requests.Response | None:
            time.sleep(self.delay)
            debug(f"GET {url} | params={params}")
            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp
            except requests.exceptions.Timeout:
                warn(f"[{self.nome}] Timeout: {url}")
            except requests.exceptions.HTTPError as e:
                warn(f"[{self.nome}] HTTP {e.response.status_code}: {url}")
            except requests.exceptions.ConnectionError:
                error(f"[{self.nome}] Sem conexão: {url}")
            except requests.exceptions.RequestException as e:
                error(f"[{self.nome}] Erro: {e}")
            return None

        @abstractmethod
        def buscar(self) -> list[Vaga]: ...


# ═══════════════════════════════════════════════════════════════
# BASE — StaticUrlScraper
# ═══════════════════════════════════════════════════════════════

class StaticUrlScraper(BaseScraper):
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
# SCRAPER 3 — EmpregosPernambuco
# ═══════════════════════════════════════════════════════════════

class EmpregoPEScraper(BaseScraper):
    """Scraper para empregospernambuco.com.br/jobs (WordPress Job Manager)."""

    nome     = "EmpregoPE"
    BASE_URL = "https://empregospernambuco.com.br/jobs"

    # ── Seletores reais confirmados pelo debug ──────────────────
    _SELETORES_CARD: list[str] = [
        "li.job",
        "li.job-alt",
    ]

    # ── WordPress Job Manager usa search_keywords ───────────────
    _PARAMS_BUSCA: tuple[str, ...] = (
        "search_keywords",   # param real do WP Job Manager
        "q",                 # fallback genérico
    )

    def _detectar_cards(self, soup: BeautifulSoup) -> list:
        for seletor in self._SELETORES_CARD:
            cards = soup.select(seletor)
            if cards:
                debug(f"[EmpregoPE] Seletor ativo: '{seletor}' ({len(cards)} cards)")
                return cards
        return []

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []

        for keyword in self.keywords:
            log(f"[EmpregoPE] 🔎 '{keyword}'")
            cards: list         = []
            resp_ok             = None

            for param_key in self._PARAMS_BUSCA:
                resp_ok = self._get(self.BASE_URL, params={param_key: keyword})
                if not resp_ok:
                    continue

                soup  = BeautifulSoup(resp_ok.text, "html.parser")
                cards = self._detectar_cards(soup)

                if cards:
                    debug(f"[EmpregoPE] Param funcional: '{param_key}'")
                    break

            if not cards:
                warn(f"[EmpregoPE] Sem vagas para '{keyword}'.")
                continue

            antes = len(vagas)

            for card in cards[: self.max_vagas]:
                try:
                    # ── Título: dentro de div.job-title > a ────
                    titulo_el = (
                        card.select_one("div.job-title a")
                        or card.select_one("h1 a, h2 a, h3 a")
                        or card.select_one("a")
                    )
                    if not titulo_el:
                        continue

                    # ── Empresa: dentro de div.job-meta ────────
                    meta_el    = card.select_one("div.job-meta")
                    empresa_el = (
                        meta_el.select_one("[class*='company'], strong, span")
                        if meta_el else None
                    )

                    # ── Localização ─────────────────────────────
                    local_el = card.select_one(
                        "[class*='location'], [class*='local'], "
                        "div.job-meta [class*='loc']"
                    )

                    # ── Data: div.job-date ──────────────────────
                    data_el   = card.select_one("div.job-date, time[datetime]")
                    data_post = ""
                    if data_el:
                        data_post = (
                            data_el.get("datetime")
                            or data_el.get_text(strip=True)
                        )

                    # ── Link ────────────────────────────────────
                    href = titulo_el.get("href", "")
                    link = (
                        href if href.startswith("http")
                        else f"https://empregospernambuco.com.br{href}"
                    )

                    vagas.append(Vaga(
                        titulo=titulo_el.get_text(strip=True),
                        empresa=empresa_el.get_text(strip=True) if empresa_el else "N/D",
                        localizacao=local_el.get_text(strip=True) if local_el else "Pernambuco",
                        url=link,
                        plataforma="EmpregoPE",
                        data_postagem=data_post,
                    ))

                except (AttributeError, KeyError) as e:
                    debug(f"[EmpregoPE] Erro no card: {e}")

            coletadas = len(vagas) - antes
            if coletadas:
                success(f"[EmpregoPE] {coletadas} vagas para '{keyword}'")
            else:
                warn(f"[EmpregoPE] Cards encontrados mas sem dados extraídos para '{keyword}'.")

        return vagas


# ═══════════════════════════════════════════════════════════════
# SCRAPER 4 — ComunidadeEmpregoPE
# ═══════════════════════════════════════════════════════════════

class ComunidadeEmpregoPEScraper(BaseScraper):
    """Scraper para comunidadeempregope.com.br."""

    nome     = "ComunidadeEmpregoPE"
    BASE_URL = "https://comunidadeempregope.com.br"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []
        endpoints = ["/", "/vagas", "/empregos", "/oportunidades", "/jobs"]

        soup_principal: BeautifulSoup | None = None
        for endpoint in endpoints:
            resp = self._get(f"{self.BASE_URL}{endpoint}")
            if resp:
                soup_principal = BeautifulSoup(resp.text, "html.parser")
                if soup_principal.select("[class*='job'], [class*='vaga'], article"):
                    break

        if not soup_principal:
            warn("[ComunidadeEmpregoPE] Sem conexão com o site.")
            return []

        cards = (
            soup_principal.select("article, .post, [class*='vaga'], [class*='job']")
            or soup_principal.select("div.entry, div.card")
        )

        keywords_lower = [k.lower() for k in self.keywords]

        for card in cards[: self.max_vagas * 3]:
            try:
                titulo_el  = card.select_one("h1 a, h2 a, h3 a, .entry-title a")
                empresa_el = card.select_one("[class*='company'], [class*='empresa'], .author")
                local_el   = card.select_one("[class*='location'], [class*='local'], [class*='city']")
                desc_el    = card.select_one("p, .excerpt, .summary, [class*='desc']")
                data_el    = card.select_one("time[datetime], .entry-date, [class*='date'], [class*='data']")

                if not titulo_el:
                    continue

                titulo = titulo_el.get_text(strip=True)
                desc   = desc_el.get_text(strip=True) if desc_el else ""
                texto  = (titulo + " " + desc).lower()

                if not any(kw in texto for kw in keywords_lower):
                    continue

                href = titulo_el.get("href", "")
                link = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                if data_el:
                    data_post = data_el.get("datetime") or data_el.get_text(strip=True)
                else:
                    data_post = ""

                vagas.append(Vaga(
                    titulo=titulo,
                    empresa=empresa_el.get_text(strip=True) if empresa_el else "N/D",
                    localizacao=local_el.get_text(strip=True) if local_el else "Pernambuco",
                    url=link,
                    plataforma="ComunidadeEmpregoPE",
                    descricao=desc[:300],
                    data_postagem=data_post,
                ))

                if len(vagas) >= self.max_vagas:
                    break

            except (AttributeError, KeyError) as e:
                debug(f"[ComunidadeEmpregoPE] Erro no card: {e}")

        if vagas:
            success(f"[ComunidadeEmpregoPE] {len(vagas)} vagas coletadas.")
        else:
            warn("[ComunidadeEmpregoPE] Sem vagas relevantes encontradas.")

        return vagas


# ═══════════════════════════════════════════════════════════════
# SCRAPER 5 — BlogspotRSS (InformeVagasPE)
# ═══════════════════════════════════════════════════════════════

class BlogspotRSSScraper(BaseScraper):
    """Scraper via feed RSS do Blogspot para informevagaspe.blogspot.com."""

    nome    = "BlogspotPE"
    RSS_URL = "https://informevagaspe.blogspot.com/feeds/posts/default?alt=rss&max-results=50"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []
        log(f"[BlogspotPE] 📡 Lendo feed RSS: {self.RSS_URL}")

        resp = self._get(self.RSS_URL)
        if not resp:
            return []

        try:
            root  = ET.fromstring(resp.content)
            items = root.findall(".//item")
        except ET.ParseError as e:
            error(f"[BlogspotPE] Erro ao parsear RSS: {e}")
            return []

        keywords_lower = [k.lower() for k in self.keywords]

        for item in items[: self.max_vagas * 3]:
            try:
                titulo   = item.findtext("title", "").strip()
                link     = item.findtext("link", "").strip()
                desc_raw = item.findtext("description", "").strip()
                pubdate  = item.findtext("pubDate", "").strip()

                desc_soup = BeautifulSoup(desc_raw, "html.parser")
                desc      = desc_soup.get_text(separator=" ", strip=True)[:500]

                texto = (titulo + " " + desc).lower()
                if not any(kw in texto for kw in keywords_lower):
                    continue

                empresa = self._extrair_empresa(desc)
                local   = self._extrair_local(desc) or "Pernambuco"

                vagas.append(Vaga(
                    titulo=titulo or "Vaga no InformeVagasPE",
                    empresa=empresa,
                    localizacao=local,
                    url=link,
                    plataforma="BlogspotPE",
                    descricao=desc[:300],
                    data_postagem=pubdate,
                ))

                if len(vagas) >= self.max_vagas:
                    break

            except Exception as e:
                debug(f"[BlogspotPE] Erro no item: {e}")

        if vagas:
            success(f"[BlogspotPE] {len(vagas)} vagas relevantes no feed.")
        else:
            warn("[BlogspotPE] Sem posts relevantes às keywords no feed.")

        return vagas

    def _extrair_empresa(self, texto: str) -> str:
        padroes = [
            r"empresa[:\s]+([A-Z][^\n,\.]{2,40})",
            r"contratante[:\s]+([A-Z][^\n,\.]{2,40})",
            r"(?:vaga|oportunidade)\s+(?:na|no|em)\s+([A-Z][^\n,\.]{2,40})",
        ]
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return "N/D"

    def _extrair_local(self, texto: str) -> str:
        cidades_pe = [
            "Recife", "Jaboatão", "Caruaru", "Olinda",
            "Paulista", "Cabo de Santo Agostinho", "Camaragibe",
            "Garanhuns", "Petrolina", "Vitória de Santo Antão",
        ]
        for cidade in cidades_pe:
            if cidade.lower() in texto.lower():
                return f"{cidade} - PE"
        return ""


# ═══════════════════════════════════════════════════════════════
# SCRAPER 6 — Google News RSS (Concursos e Seleções)
# ═══════════════════════════════════════════════════════════════

class GoogleNewsScraper(BaseScraper):
    """
    Coleta notícias de concursos e seleções via Google News RSS.

    Melhorias:
    - Filtra apenas notícias do último mês
    - Evita URLs duplicadas
    - Limita duplicatas de título+empresa
    """

    nome     = "GoogleNews"
    RSS_BASE = "https://news.google.com/rss/search"
    QUERIES_PE: list[str] = [
        "concursos pernambuco abertos",
        "seleção simplificada pernambuco",
        "processo seletivo recife PE",
        "edital concurso público pernambuco",
    ]

    def _parse_data_rss(self, data_str: str) -> datetime | None:
        """Tenta parsear data no formato 'Thu, 06 May 2026 19:04:32 GMT'"""
        if not data_str:
            return None
        try:
            # Formato Google News: 'Thu, 06 May 2026 19:04:32 GMT'
            return datetime.strptime(data_str.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        except ValueError:
            return None

    def _é_dentro_do_ultimo_mes(self, pubdate_str: str) -> bool:
        """Verifica se a data está dentro do último mês"""
        data = self._parse_data_rss(pubdate_str)
        if not data:
            return True  # Se não conseguir parsear, inclui mesmo assim

        hoje = datetime.now()
        dias_diff = (hoje - data).days

        return 0 <= dias_diff <= 30

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []
        urls_vistos: set[str] = set()  # Dedup por URL dentro do scraper

        for query in self.QUERIES_PE:
            log(f"[GoogleNews] 📰 Query: '{query}'")
            params = {"q": query, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}
            resp   = self._get(self.RSS_BASE, params=params)
            if not resp:
                continue

            try:
                root  = ET.fromstring(resp.content)
                items = root.findall(".//item")
            except ET.ParseError as e:
                error(f"[GoogleNews] Erro XML na query '{query}': {e}")
                continue

            antes = len(vagas)
            for item in items[: self.max_vagas * 2]:  # Procura mais para compensar filtros
                try:
                    titulo   = item.findtext("title", "").strip()
                    link     = item.findtext("link", "").strip()
                    fonte    = item.findtext("source", "").strip()
                    pubdate  = item.findtext("pubDate", "").strip()
                    desc_raw = item.findtext("description", "").strip()

                    if not titulo or not link:
                        continue

                    # ✅ Filtro 1: Evita URLs duplicadas
                    if link in urls_vistos:
                        continue
                    urls_vistos.add(link)

                    # ✅ Filtro 2: Apenas artigos do último mês
                    if not self._é_dentro_do_ultimo_mes(pubdate):
                        continue

                    desc_soup = BeautifulSoup(desc_raw, "html.parser")
                    desc      = desc_soup.get_text(strip=True)[:300]

                    vaga = Vaga(
                        titulo=titulo,
                        empresa=fonte or "Google News",
                        localizacao="Pernambuco",
                        url=link,
                        plataforma="GoogleNews",
                        descricao=desc,
                        data_postagem=pubdate,
                    )

                    vagas.append(vaga)

                    # Para quando atingir max_vagas
                    if len(vagas) >= self.max_vagas:
                        break

                except Exception as e:
                    debug(f"[GoogleNews] Erro no item: {e}")

            coletadas = len(vagas) - antes
            if coletadas:
                success(f"[GoogleNews] {coletadas} artigos para '{query}' (últimas 30 dias, sem dupes)")

        return vagas


# ═══════════════════════════════════════════════════════════════
# SCRAPER 7 — InfoJobs Geolocalizado
# ═══════════════════════════════════════════════════════════════

class InfoJobsGeoScraper(StaticUrlScraper):
    """Versão geolocalizada do scraper InfoJobs com seletores confirmados."""

    nome     = "InfoJobsGeo"
    BASE_URL = "https://www.infojobs.com.br"

    URLS: list[str] = [
        (
            "https://www.infojobs.com.br/vagas-de-emprego-fiscal+de+preven%c3%a7%c3%a3o+de+perdas"
            "-em-recife,-pe.aspx?Antiguedad=3&sprd=25&splat=-8.037708&splng=-34.9540847"
        ),
        (
            "https://www.infojobs.com.br/empregos.aspx"
            "?splng=-34.9540847&palabra=Porteiro&splat=-8.037708&sprd=25&poblacion=5207362"
        ),
        (
            "https://www.infojobs.com.br/empregos.aspx"
            "?palabra=Porteiro&sprd=25&splng=-34.9540847&splat=-8.037708&poblacion=5207273"
        ),
    ]

    def _extrair(self, soup: BeautifulSoup, url: str) -> list[Vaga]:
        vagas: list[Vaga] = []
        cards = soup.select("div.js_rowCard")

        if not cards:
            snippet = soup.body.prettify()[:2000] if soup.body else "body vazio"
            debug(f"[InfoJobsGeo] Nenhum card — HTML snippet:\n{snippet}")
            return []

        debug(f"[InfoJobsGeo] {len(cards)} cards encontrados.")

        for card in cards:
            try:
                titulo_el  = card.select_one("h2")
                link_div   = card.select_one("div.js_cardLink[data-href]")
                empresa_el = card.select_one("a[href*='/empresa-']")
                salario_el = card.select_one("[class*='salary'], [class*='salario']")
                data_el    = card.select_one("div.js_date[data-value]")
                data_texto = card.select_one("div.text-medium.small.text-nowrap")

                if not titulo_el or not link_div:
                    continue

                if data_el and data_el.get("data-value"):
                    data_post = data_el["data-value"][:10]       # "2026/04/30"
                elif data_texto:
                    data_post = data_texto.get_text(strip=True)  # "30 abr"
                else:
                    data_post = ""

                vagas.append(Vaga(
                    titulo=titulo_el.get_text(strip=True),
                    empresa=empresa_el.get_text(strip=True) if empresa_el else "N/D",
                    localizacao="Recife - PE",
                    url=self.BASE_URL + link_div["data-href"],
                    plataforma="InfoJobsGeo",
                    salario=salario_el.get_text(strip=True) if salario_el else "A combinar",
                    data_postagem=data_post,
                ))

            except (AttributeError, KeyError) as e:
                debug(f"[InfoJobsGeo] Erro no card: {e}")

        return vagas


# ═══════════════════════════════════════════════════════════════
# REGISTRO
# ═══════════════════════════════════════════════════════════════

# Importa scrapers extras (GoRecife, Solides, BNE, VagasComBr, VagasPE, Jobrapido)
try:
    from scrapers_extras_pe import SCRAPERS_EXTRAS_PE
except ImportError:
    SCRAPERS_EXTRAS_PE = {}

SCRAPERS_PE: dict[str, type[BaseScraper]] = {
    # ── Fontes originais ──────────────────────────────────────────
    "empregope":           EmpregoPEScraper,
    "comunidadeempregope": ComunidadeEmpregoPEScraper,
    "blogspot_pe":         BlogspotRSSScraper,
    "google_news":         GoogleNewsScraper,
    "infojobs_geo":        InfoJobsGeoScraper,
    # ── Fontes extras (scrapers_extras_pe.py) ─────────────────────
    **SCRAPERS_EXTRAS_PE,
}


# ═══════════════════════════════════════════════════════════════
# TESTE STANDALONE
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.DEBUG, format="%(message)s")

    parser = argparse.ArgumentParser(description="Testar scrapers PE individualmente.")
    parser.add_argument(
        "--scraper", "-s",
        choices=list(SCRAPERS_PE.keys()),
        default="google_news",
        help="Qual scraper testar (padrão: google_news)",
    )
    args = parser.parse_args()

    KEYWORDS = ["Porteiro", "Vigia", "Fiscal de Loja", "Prevenção de Perdas"]
    LOCAL    = "Recife, PE"

    cls     = SCRAPERS_PE[args.scraper]
    scraper = cls(keywords=KEYWORDS, localizacao=LOCAL, max_vagas=5, delay=1.5)

    print(f"\n{'═' * 55}")
    print(f"  Testando: {cls.__name__}")
    print(f"{'═' * 55}\n")

    vagas = scraper.buscar()

    print(f"\n{'─' * 55}")
    print(f"  Total: {len(vagas)} vagas")
    print(f"{'─' * 55}")

    for i, v in enumerate(vagas, 1):
        print(f"\n[{i}] {v.titulo}")
        print(f"    Empresa   : {v.empresa}")
        print(f"    Local     : {v.localizacao}")
        print(f"    Salário   : {v.salario}")
        print(f"    Postado em: {v.data_postagem or 'N/D'}")
        print(f"    URL       : {v.url}")