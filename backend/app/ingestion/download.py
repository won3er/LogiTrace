"""Download dos arquivos brutos das fontes públicas (sem scraping: apenas arquivos e APIs publicados)."""

from __future__ import annotations

import logging
import shutil
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("logitrace.download")

IBGE_LOG = "https://geoftp.ibge.gov.br/organizacao_do_territorio/redes_e_fluxos_geograficos/logistica_dos_transportes"
IBGE_API = "https://servicodados.ibge.gov.br/api"

FILES: list[tuple[str, str]] = [
    ("ibge/municipios.json", f"{IBGE_API}/v1/localidades/municipios"),
    ("ibge/malha_municipios.geojson",
     f"{IBGE_API}/v3/malhas/paises/BR?formato=application/vnd.geo%2Bjson&qualidade=intermediaria&intrarregiao=municipio"),
    ("ibge/malha_ufs.geojson",
     f"{IBGE_API}/v3/malhas/paises/BR?formato=application/vnd.geo%2Bjson&qualidade=intermediaria&intrarregiao=UF"),
    ("ibge/pop_censo2022.json", "https://apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/2022"),
    ("ibge/pib_municipal.json", "https://apisidra.ibge.gov.br/values/t/5938/n6/all/v/37/p/last"),
    ("ibge/base_de_dados_2014.zip", f"{IBGE_LOG}/2014/base_de_dados_2014.zip"),
    ("ourairports/airports.csv", "https://davidmegginson.github.io/ourairports-data/airports.csv"),
] + [
    (f"ibge/fluxos_2024/{name}.zip", f"{IBGE_LOG}/2024/Base_de_dados/Fluxos_Consolidados_de_Mercadorias/{name}.zip")
    for name in ("Fluxos_Aereos", "Fluxos_Aquaviarios", "Fluxos_Ferroviarios", "Fluxos_Rodoviarios")
]


def _extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"Entrada de ZIP fora do destino: {member}")
        z.extractall(dest)


def download_all(raw_dir: Path, force: bool = False) -> list[str]:
    done: list[str] = []
    for rel, url in FILES:
        path = raw_dir / rel
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("baixando %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": "LogiTrace/1.0 (ingestão de dados públicos)"})
        with urllib.request.urlopen(req, timeout=600) as resp, open(path, "wb") as f:  # noqa: S310 - URLs fixas
            shutil.copyfileobj(resp, f)
        done.append(rel)
    base_zip = raw_dir / "ibge" / "base_de_dados_2014.zip"
    if base_zip.exists() and not (raw_dir / "ibge" / "base_2014" / "2014").exists():
        _extract(base_zip, raw_dir / "ibge" / "base_2014")
    for z in (raw_dir / "ibge" / "fluxos_2024").glob("*.zip"):
        dest = z.with_suffix("")
        if not dest.exists():
            _extract(z, dest)
    return done
