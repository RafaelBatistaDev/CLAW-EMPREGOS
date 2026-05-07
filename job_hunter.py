#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nome do Script  : job_hunter.py
Descrição       : Bot de busca de vagas em múltiplas plataformas.
                  Suporta: LinkedIn, Indeed BR, InfoJobs, Gupy API,
                  e scrapers regionais de Pernambuco via scrapers_pe.py.
Autor           : recifecrypto
Versão          : 1.5.0
"""

import argparse
import hashlib
import json
import logging
import sys
import unicodedata
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Importa scrapers regionais
try:
    from scrapers_pe import SCRAPERS_PE
except ImportError:
    SCRAPERS_PE = {}

# ─────────────────────────────────────────────
# 2. CONSTANTES E DIRETÓRIOS
# ─────────────────────────────────────────────
USER_HOME   = Path.home()
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "vagas"
LOG_DIR     = USER_HOME / ".local" / "log"
CONFIG_FILE = BASE_DIR / "config_vagas.json"

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE  = LOG_DIR / f"job_hunter_{TIMESTAMP}.log"
JSON_OUT  = DATA_DIR / f"vagas_{TIMESTAMP}.json"

HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 15

# Plataformas isentas do filtro geográfico (filtradas no frontend/JS)
PLATAFORMAS_SEM_FILTRO_GEO: set[str] = {"Gupy"}


# ─────────────────────────────────────────────
# 3. CORES ANSI
# ─────────────────────────────────────────────
class Color:
    G = "\033[1;32m"
    B = "\033[1;34m"
    Y = "\033[1;33m"
    R = "\033[1;31m"
    C = "\033[1;36m"
    M = "\033[1;35m"
    N = "\033[0m"


# ─────────────────────────────────────────────
# 4. LOGGING
# ─────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("job_hunter")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s — %(message)s"))
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


logger = _setup_logging()


def section(titulo: str) -> None:
    borda = "═" * 55
    logger.info(f"\n{Color.M}{borda}\n  {titulo}\n{borda}{Color.N}")

def log(msg: str)     -> None: logger.info(f"{Color.B}[INFO]{Color.N}    {msg}")
def success(msg: str) -> None: logger.info(f"{Color.G}[OK]{Color.N}      {msg}")
def warn(msg: str)    -> None: logger.warning(f"{Color.Y}[AVISO]{Color.N}  {msg}")
def erro(msg: str)    -> None: logger.error(f"{Color.R}[ERRO]{Color.N}   {msg}")
def debug(msg: str)   -> None: logger.debug(f"{Color.C}[DEBUG]{Color.N}  {msg}")


def bootstrap() -> None:
    for d in (DATA_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    ).lower()


# ─────────────────────────────────────────────
# 5. MODELOS
# ─────────────────────────────────────────────
@dataclass
class Vaga:
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


# ─────────────────────────────────────────────
# 6. BASE SCRAPER
# ─────────────────────────────────────────────
class BaseScraper(ABC):
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
        self,
        url:    str,
        params: dict | None = None,
    ) -> requests.Response | None:
        """GET com log explícito de erros — nunca silencia falhas."""
        time.sleep(self.delay)
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as e:
            warn(f"[{self.nome}] HTTP {e.response.status_code}: {url}")
        except requests.exceptions.ConnectionError:
            warn(f"[{self.nome}] Sem conexão: {url}")
        except requests.exceptions.Timeout:
            warn(f"[{self.nome}] Timeout ({REQUEST_TIMEOUT}s): {url}")
        except requests.exceptions.RequestException as e:
            warn(f"[{self.nome}] Request error: {e}")
        return None

    @abstractmethod
    def buscar(self) -> list[Vaga]: ...


# ─────────────────────────────────────────────
# 7. SCRAPERS
# ─────────────────────────────────────────────
class GupyScraper(BaseScraper):
    """
    Gupy não suporta filtro geográfico real via API — retorna vagas nacionais.
    Filtro por localização fica a cargo do frontend/JS.
    """
    nome     = "Gupy"
    BASE_URL = "https://portal.api.gupy.io/api/job"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []

        for kw in self.keywords:
            resp = self._get(self.BASE_URL, params={
                "name":   kw,
                "limit":  self.max_vagas,
                "offset": 0,
            })
            if not resp:
                continue

            for job in resp.json().get("data", []):
                city  = job.get("city",  "") or ""
                state = job.get("state", "") or ""

                vagas.append(Vaga(
                    titulo      = job.get("name", ""),
                    empresa     = job.get("careerPageName", "N/D"),
                    localizacao = f"{city} - {state}",
                    url         = job.get("jobUrl", ""),
                    plataforma  = "Gupy",
                ))

        return vagas


class IndeedScraper(BaseScraper):
    nome     = "Indeed"
    BASE_URL = "https://br.indeed.com/empregos"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []

        for kw in self.keywords:
            resp = self._get(self.BASE_URL, params={"q": kw, "l": self.localizacao})
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.select(".job_seen_beacon")[: self.max_vagas]:
                titulo_el  = card.select_one("h2.jobTitle")
                empresa_el = card.select_one("[data-testid='company-name'], .companyName")
                local_el   = card.select_one("[data-testid='text-location'], .companyLocation")
                link_el    = card.select_one("h2.jobTitle a")

                if not titulo_el:
                    continue

                href = link_el.get("href", "") if link_el else ""
                url  = href if href.startswith("http") else f"https://br.indeed.com{href}"

                vagas.append(Vaga(
                    titulo      = titulo_el.get_text(strip=True),
                    empresa     = empresa_el.get_text(strip=True) if empresa_el else "N/D",
                    localizacao = local_el.get_text(strip=True) if local_el else self.localizacao,
                    url         = url,
                    plataforma  = "Indeed",
                ))

        return vagas


class InfoJobsScraper(BaseScraper):
    nome     = "InfoJobs"
    BASE_URL = "https://www.infojobs.com.br"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []

        for kw in self.keywords:
            kw_f  = kw.lower().replace(" ", "-")
            loc_f = self.localizacao.lower().replace(",", "").replace(" ", "-")
            resp  = self._get(f"{self.BASE_URL}/vagas-de-emprego-{kw_f}-em-{loc_f}.aspx")
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            for card in soup.select("div.js_rowCard")[: self.max_vagas]:
                titulo_el = card.select_one("h2")
                if not titulo_el:
                    continue

                # Empresa: link da empresa → span.text-nowrap (texto direto, sem SVG filho)
                empresa = "N/D"
                empresa_link = card.select_one("a.text-body.text-decoration-none")
                if empresa_link:
                    span = empresa_link.select_one("span.text-nowrap")
                    if span:
                        empresa = span.find(string=True, recursive=False)
                        empresa = empresa.strip() if empresa else span.get_text(strip=True)

                # Localização: div.mb-8 sem o span de distância
                localizacao = self.localizacao
                local_el = card.select_one("div.mb-8")
                if local_el:
                    for spam in local_el.select("span.js_divUserVagaDistance"):
                        spam.decompose()
                    localizacao = local_el.get_text(strip=True)

                # Salário: pai do ícone icon-money
                salario = ""
                money_icon = card.select_one("svg.icon-money")
                if money_icon:
                    salario = money_icon.find_parent().get_text(strip=True)

                # Link: data-href no card interno
                link_el = card.select_one("[data-href]")
                href = link_el.get("data-href", "") if link_el else ""
                url  = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                vagas.append(Vaga(
                    titulo      = titulo_el.get_text(strip=True),
                    empresa     = empresa,
                    localizacao = localizacao,
                    url         = url,
                    plataforma  = "InfoJobs",
                    salario     = salario,
                ))

        return vagas


class LinkedInScraper(BaseScraper):
    nome     = "LinkedIn"
    BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def buscar(self) -> list[Vaga]:
        vagas: list[Vaga] = []

        for kw in self.keywords:
            resp = self._get(self.BASE_URL, params={
                "keywords": kw,
                "location": self.localizacao,
            })
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for card in soup.select(".base-card")[: self.max_vagas]:
                titulo_el  = card.select_one(".base-search-card__title")
                empresa_el = card.select_one(".base-search-card__subtitle")
                local_el   = card.select_one(".job-search-card__location")
                link_el    = card.select_one("a.base-card__full-link")

                if not titulo_el:
                    continue

                vagas.append(Vaga(
                    titulo      = titulo_el.get_text(strip=True),
                    empresa     = empresa_el.get_text(strip=True) if empresa_el else "N/D",
                    localizacao = local_el.get_text(strip=True) if local_el else self.localizacao,
                    url         = link_el.get("href", "") if link_el else "",
                    plataforma  = "LinkedIn",
                ))

        return vagas


# ─────────────────────────────────────────────
# 8. MAPA DE SCRAPERS
# ─────────────────────────────────────────────
SCRAPERS_MAP: dict[str, type[BaseScraper]] = {
    "gupy":     GupyScraper,
    "indeed":   IndeedScraper,
    "infojobs": InfoJobsScraper,
    "linkedin": LinkedInScraper,
}
SCRAPERS_MAP.update(SCRAPERS_PE)


# ─────────────────────────────────────────────
# 9. FUNÇÕES DE NEGÓCIO
# ─────────────────────────────────────────────
def carregar_config(caminho: Path) -> dict:
    """Carrega config JSON ou cria um padrão se não existir."""
    if not caminho.exists():
        cfg = {
            "keywords":                   ["Porteiro", "Vigia", "Fiscal de Loja"],
            "localizacao":                "Recife, PE",
            "max_vagas_por_plataforma":   20,
            "delay_entre_requisicoes":    2.5,
            "plataformas":                ["gupy", "linkedin", "indeed", "infojobs"],
        }
        caminho.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"Config criada em: {caminho}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def filtrar_por_localizacao(vagas: list[Vaga], localizacao: str) -> list[Vaga]:
    """
    Remove vagas fora da localização alvo.
    Plataformas em PLATAFORMAS_SEM_FILTRO_GEO são isentas (ex: Gupy — filtro no JS).
    """
    termos = [
        normalizar_texto(t)
        for t in localizacao.replace(",", " ").split()
        if len(t) > 1
    ]

    def é_local(v: Vaga) -> bool:
        if v.plataforma in PLATAFORMAS_SEM_FILTRO_GEO:
            return True  # isento — filtrado no frontend
        loc = normalizar_texto(v.localizacao)
        return any(t in loc for t in termos)

    antes  = len(vagas)
    vagas  = [v for v in vagas if é_local(v)]
    depois = len(vagas)

    removidas = antes - depois
    if removidas:
        warn(f"{removidas} vagas fora de '{localizacao}' removidas pelo filtro geográfico.")

    return vagas


def categorize_vagas(vagas: list[Vaga], keywords: list[str]) -> list[Vaga]:
    """Atribui categoria à vaga com base nas keywords encontradas no título/descrição."""
    kw_n = [normalizar_texto(k) for k in keywords]
    for v in vagas:
        v.categoria = "Outros"
        texto = normalizar_texto(v.titulo + v.descricao)
        for i, kn in enumerate(kw_n):
            if kn in texto:
                v.categoria = keywords[i].capitalize()
                break
    return vagas


def salvar_json(vagas: list[Vaga], caminho: Path) -> None:
    """Salva lista de vagas em JSON estruturado."""
    payload = {
        "meta": {
            "total":     len(vagas),
            "gerado_em": datetime.now().isoformat(),
        },
        "vagas": [v.to_dict() for v in vagas],
    }
    caminho.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def executar_busca(config: dict) -> list[Vaga]:
    """Executa busca em todas as plataformas configuradas e retorna vagas únicas e filtradas."""
    todas: list[Vaga] = []

    for nome in config.get("plataformas", []):
        cls = SCRAPERS_MAP.get(nome.lower())
        if not cls:
            warn(f"Plataforma desconhecida ignorada: '{nome}'")
            continue

        section(f"🔍 {nome.upper()}")
        try:
            resultado = cls(
                config["keywords"],
                config["localizacao"],
                config["max_vagas_por_plataforma"],
                config["delay_entre_requisicoes"],
            ).buscar()

            if resultado:
                isento = cls.nome in PLATAFORMAS_SEM_FILTRO_GEO
                sufixo = " (nacional — filtro no JS)" if isento else ""
                success(f"{len(resultado)} vagas coletadas em {nome}{sufixo}")
                for v in resultado[:3]:
                    log(f"   → {v.titulo} | {v.empresa} | {v.localizacao}")
                if len(resultado) > 3:
                    log(f"   ... e mais {len(resultado) - 3} vagas.")
            else:
                warn(f"Nenhuma vaga retornada por {nome}.")

            todas.extend(resultado)

        except Exception as e:
            erro(f"{nome}: {e}")

     # Deduplicação por id_unico (MD5 de título+empresa+plataforma) e por URL
    vistos:  set[str]   = set()
    urls_vistos: set[str] = set()
    unicas:  list[Vaga] = []
    for v in todas:
        # Evita duplicatas por ID único ou por URL
        if v.id_unico not in vistos and v.url not in urls_vistos:
            vistos.add(v.id_unico)
            urls_vistos.add(v.url)
            unicas.append(v)

    duplicadas = len(todas) - len(unicas)
    if duplicadas:
        log(f"{duplicadas} duplicatas removidas (por título/empresa/URL).")

    # Filtro geográfico global (Gupy isento)
    unicas = filtrar_por_localizacao(unicas, config["localizacao"])

    return unicas


# ─────────────────────────────────────────────
# 10. ENTRY POINT
# ─────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Job Hunter — busca de vagas em PE")
    p.add_argument("--config", type=Path, default=CONFIG_FILE, help="Caminho para config JSON")
    return p.parse_args()


def main() -> None:
    bootstrap()
    args = parse_args()
    cfg  = carregar_config(args.config)

    section("⚙️  CONFIGURAÇÃO")
    log(f"Keywords   : {cfg['keywords']}")
    log(f"Localização: {cfg['localizacao']}")
    log(f"Plataformas: {cfg.get('plataformas', [])}")
    log(f"Max/plat.  : {cfg['max_vagas_por_plataforma']}")
    log(f"Sem filtro : {sorted(PLATAFORMAS_SEM_FILTRO_GEO)} (nacional — filtro no JS)")
    log(f"Log        : {LOG_FILE}")

    vagas = executar_busca(cfg)
    vagas = categorize_vagas(vagas, cfg["keywords"])

    section("📊 RESULTADO FINAL")
    if vagas:
        success(f"Total de vagas únicas: {len(vagas)}")

        por_plat: dict[str, int] = {}
        for v in vagas:
            por_plat[v.plataforma] = por_plat.get(v.plataforma, 0) + 1
        for plat, qtd in sorted(por_plat.items(), key=lambda x: -x[1]):
            icone = "🌐" if plat in PLATAFORMAS_SEM_FILTRO_GEO else "📍"
            log(f"   {icone} {plat:<12}: {qtd} vagas")

        salvar_json(vagas, JSON_OUT)
        success(f"JSON salvo em: {JSON_OUT}")
    else:
        warn("Nenhuma vaga coletada. Verifique config_vagas.json e o log.")
        log(f"Log: {LOG_FILE}")


if __name__ == "__main__":
    main()