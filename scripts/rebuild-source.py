#!/usr/bin/env python3
"""Rebuild the Countries SQLite fixture from the pinned DataTug geo reference data.

The recipe input is the vendored geo inGitDB directory of
github.com/datatug/datatug-demo-project at the revision pinned in manifest.json
(`demo-project-1/data/geo`). It holds three collections derived from GeoNames
(countries), the World Bank (population_wb) and a hand-checked alias list
(country_aliases); see data-source/LICENSE.md for attribution and changes.

Usage:
  rebuild-source.py --geo <dir>            write data-source/source.sqlite
  rebuild-source.py --geo <dir> --check    rebuild into a temporary file and compare

`--check` verifies the recipe inputs against the manifest's tree digest, rebuilds
the database and compares its complete logical contents (schema SQL and every
row with its SQLite storage class) with the committed fixture. SQLite file bytes
may differ between SQLite library versions; the committed file is the published
artifact and is pinned by manifest.source.databaseSha256.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data-source" / "source.sqlite"
MANIFEST = ROOT / "manifest.json"

COLLECTIONS = ("countries", "population_wb", "country_aliases")
INPUT_FILES = ("DATA-LICENSE.md", ".ingitdb/root-collections.yaml", ".ingitdb/settings.yaml")
CONTINENTS = {"AF", "AS", "EU", "NA", "OC", "SA", "AN"}

GEONAMES = "geonames-countryinfo"
WORLD_BANK = "worldbank-sp-pop-totl"
ALIASES = "datatug-country-aliases"

# Spellings used by the Northwind sample (Orders.ShipCountry, Customers.Country,
# Suppliers.Country) that do not equal a GeoNames English name and are not yet
# in the vendored alias list. Hand-checked; no third-party content.
EXTRA_ALIASES = (
    ("UK", "GB", "northwind Orders.ShipCountry, Customers.Country and Suppliers.Country; manual match: Northwind spells it 'UK'; countries.name is 'United Kingdom'"),
)

SOURCES = (
    {
        "source_id": GEONAMES,
        "publisher": "GeoNames",
        "dataset": "countryInfo.txt (GeoNames geographical database)",
        "url": "https://download.geonames.org/export/dump/countryInfo.txt",
        "licence": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Country names, ISO 3166-1 codes, continent, capital, area, currency, calling code, TLD and GeoName ID: (c) GeoNames, https://www.geonames.org/, licensed under CC BY 4.0.",
        "modifications": "Modified: re-keyed by upper-case ISO 3166-1 alpha-2 code, columns renamed, the English name kept as name, the undated GeoNames population dropped (population comes from the World Bank), and stored as SQLite. GeoNames does not endorse this database.",
        "retrieved_at": None,
        "source_updated": None,
    },
    {
        "source_id": WORLD_BANK,
        "publisher": "The World Bank",
        "dataset": "World Development Indicators, SP.POP.TOTL (Population, total)",
        "url": "https://data.worldbank.org/indicator/SP.POP.TOTL",
        "licence": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Population: The World Bank, World Development Indicators, indicator SP.POP.TOTL, retrieved from the World Bank Indicators API v2 (https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&mrnev=1). Data (c) The World Bank, licensed under CC BY 4.0.",
        "modifications": "Modified: only the most recent non-empty observation per country is kept, with its year; World Bank aggregates and entities without a GeoNames country are dropped; rows are joined to countries by ISO 3166-1 alpha-3 code. Values are the World Bank's figures as published. The World Bank does not endorse this database.",
        "retrieved_at": None,  # filled from the vendored records' fetched_at
        "source_updated": None,  # filled from the vendored records' source_updated
    },
    {
        "source_id": ALIASES,
        "publisher": "DataTug",
        "dataset": "Country aliases (hand-checked spellings used by Chinook and Northwind)",
        "url": "https://github.com/datatug/datatug-demo-project/tree/main/demo-project-1/data/geo/country_aliases",
        "licence": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Hand-checked mapping data by DataTug; no third-party content. Each alias row states in source which system spells it that way and how it was matched.",
        "modifications": "The vendored Chinook aliases plus Northwind spellings that differ from the GeoNames English name.",
        "retrieved_at": None,
        "source_updated": None,
    },
)

SCHEMA = """
CREATE TABLE sources (
  source_id TEXT PRIMARY KEY NOT NULL,
  publisher TEXT NOT NULL,
  dataset TEXT NOT NULL,
  url TEXT NOT NULL,
  licence TEXT NOT NULL,
  licence_url TEXT NOT NULL,
  attribution TEXT NOT NULL,
  modifications TEXT NOT NULL,
  retrieved_at TEXT,
  source_updated TEXT
);
CREATE TABLE countries (
  iso2 TEXT PRIMARY KEY NOT NULL CHECK (length(iso2) = 2),
  iso3 TEXT NOT NULL CHECK (length(iso3) = 3),
  name TEXT NOT NULL,
  continent TEXT,
  capital TEXT,
  currency_code TEXT,
  currency_name TEXT,
  area_km2 REAL,
  phone_prefix TEXT,
  tld TEXT,
  geonameid INTEGER,
  country_source_id TEXT NOT NULL REFERENCES sources (source_id),
  population INTEGER,
  population_year INTEGER,
  population_source_id TEXT REFERENCES sources (source_id),
  population_source_url TEXT
);
CREATE UNIQUE INDEX countries_iso3 ON countries (iso3);
CREATE TABLE country_aliases (
  alias TEXT PRIMARY KEY NOT NULL,
  country_iso2 TEXT NOT NULL REFERENCES countries (iso2),
  source TEXT NOT NULL
);
CREATE VIEW country_names AS
  SELECT name AS label, iso2, 'name' AS matched_by FROM countries
  UNION ALL
  SELECT alias AS label, country_iso2 AS iso2, 'alias' AS matched_by FROM country_aliases
  WHERE alias NOT IN (SELECT name FROM countries);
"""

EXPECTED = {"countries": 252, "population_wb": 216, "country_aliases": 24}


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def input_files(geo: Path) -> list[Path]:
    files = [geo / name for name in INPUT_FILES]
    for collection in COLLECTIONS:
        files.append(geo / collection / ".collection" / "definition.yaml")
        records = sorted((geo / collection / "$records").glob("*.json"))
        if len(records) != EXPECTED[collection]:
            raise ValueError(f"{collection} has {len(records)} records, expected {EXPECTED[collection]}")
        files.extend(records)
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"recipe input is missing or not a regular file: {path}")
    return files


def tree_digest(geo: Path) -> tuple[str, int]:
    """SHA-256 over sorted 'relative-path NUL sha256 LF' lines of every recipe input."""
    lines = sorted(
        f"{path.relative_to(geo).as_posix()}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in input_files(geo)
    )
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest(), len(lines)


def records(geo: Path, collection: str) -> dict[str, dict]:
    return {path.stem: load_json(path) for path in sorted((geo / collection / "$records").glob("*.json"))}


def build(geo: Path, output: Path) -> None:
    countries = records(geo, "countries")
    population = records(geo, "population_wb")
    aliases = records(geo, "country_aliases")

    fetched = {item["fetched_at"] for item in population.values()}
    updated = {item["source_updated"] for item in population.values()}
    if len(fetched) != 1 or len(updated) != 1:
        raise ValueError("population_wb must come from one World Bank retrieval")
    if {item["indicator"] for item in population.values()} != {"SP.POP.TOTL"}:
        raise ValueError("population_wb must hold only the SP.POP.TOTL indicator")

    output.unlink(missing_ok=True)
    db = sqlite3.connect(output)
    try:
        db.execute("PRAGMA page_size = 4096")
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        for source in SOURCES:
            row = dict(source)
            if row["source_id"] == WORLD_BANK:
                row["retrieved_at"], row["source_updated"] = next(iter(fetched)), next(iter(updated))
            db.execute(
                "INSERT INTO sources VALUES (:source_id, :publisher, :dataset, :url, :licence, :licence_url, :attribution, :modifications, :retrieved_at, :source_updated)",
                row,
            )
        for key, item in sorted(countries.items()):
            iso2 = item["iso2"]
            if key.upper() != iso2 or len(iso2) != 2 or not iso2.isupper():
                raise ValueError(f"countries/{key} is not keyed by its ISO alpha-2 code")
            if item.get("continent") not in CONTINENTS:
                raise ValueError(f"countries/{key} has an unknown continent")
            observation = population.get(key)
            if observation is not None and (observation["country"] != key or observation["iso3"] != item["iso3"]):
                raise ValueError(f"population_wb/{key} does not match its country by ISO codes")
            area = item.get("area_km2")
            db.execute(
                "INSERT INTO countries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    iso2,
                    item["iso3"],
                    item["names"]["en"],
                    item["continent"],
                    item.get("capital"),
                    item.get("currency_code"),
                    item.get("currency_name"),
                    float(area) if area is not None else None,
                    item.get("phone_prefix"),
                    item.get("tld"),
                    item["geonameid"],
                    GEONAMES,
                    observation["population"] if observation else None,
                    observation["year"] if observation else None,
                    WORLD_BANK if observation else None,
                    observation.get("source_url") if observation else None,
                ),
            )
        unknown = set(population) - set(countries)
        if unknown:
            raise ValueError(f"population_wb has rows without a country: {sorted(unknown)}")
        alias_rows = [(item["alias"], item["country"].upper(), item["source"]) for item in aliases.values()]
        alias_rows.extend(EXTRA_ALIASES)
        for row in sorted(alias_rows):
            db.execute("INSERT INTO country_aliases VALUES (?, ?, ?)", row)
        db.commit()
        validate(db)
        db.execute("VACUUM")
    finally:
        db.close()


def validate(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("SQLite foreign key check failed")
    # The rows the public demo depends on (Northwind ship countries).
    expected = {
        "Canada": ("CA", "CAN", "CAD"),
        "Italy": ("IT", "ITA", "EUR"),
        "Belgium": ("BE", "BEL", "EUR"),
        "USA": ("US", "USA", "USD"),
        "UK": ("GB", "GBR", "GBP"),
        "Venezuela": ("VE", "VEN", "VES"),
    }
    for label, codes in expected.items():
        row = db.execute(
            "SELECT c.iso2, c.iso3, c.currency_code, c.population, c.population_year, s.publisher "
            "FROM country_names n JOIN countries c ON c.iso2 = n.iso2 "
            "LEFT JOIN sources s ON s.source_id = c.population_source_id WHERE n.label = ?",
            (label,),
        ).fetchall()
        if len(row) != 1 or row[0][:3] != codes or not row[0][3] or row[0][5] != "The World Bank":
            raise ValueError(f"{label} does not resolve to {codes} with a World Bank population: {row}")


def snapshot(path: Path) -> dict[str, object]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        schema = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        tables = [name for kind, name, _, _ in schema if kind == "table" and not name.startswith("sqlite_")]
        rows = {}
        for name in tables:
            columns = [column[1] for column in db.execute(f'PRAGMA table_info("{name}")')]
            selection = ", ".join(f'"{column}", typeof("{column}")' for column in columns)
            rows[name] = db.execute(f'SELECT {selection} FROM "{name}" ORDER BY rowid').fetchall()
        return {"schema": schema, "rows": rows}
    finally:
        db.close()


def check(geo: Path) -> None:
    manifest = load_json(MANIFEST)
    recipe = manifest["source"]["recipe"]
    digest, count = tree_digest(geo)
    if recipe != [{"path": "demo-project-1/data/geo", "files": count, "treeSha256": digest}]:
        raise SystemExit(f"recipe inputs differ from manifest.source.recipe: {count} files, treeSha256 {digest}")
    committed = FIXTURE.read_bytes()
    if hashlib.sha256(committed).hexdigest() != manifest["source"]["databaseSha256"]:
        raise SystemExit("data-source/source.sqlite differs from manifest.source.databaseSha256")
    with tempfile.TemporaryDirectory(prefix="countries-rebuild-") as temporary:
        rebuilt = Path(temporary) / "source.sqlite"
        build(geo, rebuilt)
        if snapshot(rebuilt) != snapshot(FIXTURE):
            raise SystemExit("rebuilt Countries database differs logically from data-source/source.sqlite")
    print(f"Countries source verified: {count} recipe files, treeSha256 {digest}")


def main(argv: list[str]) -> None:
    if len(argv) not in (2, 3) or argv[0] != "--geo" or (len(argv) == 3 and argv[2] != "--check"):
        raise SystemExit("usage: rebuild-source.py --geo <dir> [--check]")
    geo = Path(argv[1]).resolve()
    if len(argv) == 3:
        check(geo)
        return
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    build(geo, FIXTURE)
    digest, count = tree_digest(geo)
    print(f"wrote {FIXTURE.relative_to(ROOT)} sha256 {hashlib.sha256(FIXTURE.read_bytes()).hexdigest()}; {count} recipe files, treeSha256 {digest}")


if __name__ == "__main__":
    main(sys.argv[1:])
