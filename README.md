# Countries

Countries is a small reference database for joining sample data to real
countries: 252 countries and territories keyed by ISO 3166-1 alpha-2 code, with
the alpha-3 code, English name, continent, capital, currency (ISO 4217 code and
name), and the latest World Bank total population with its year and source.
`country_aliases` maps the spellings other sample databases use (Northwind's
`USA` and `UK`, Chinook's billing countries) to a country, and the
`country_names` view lists every name and alias for joining a free-text
country column. Publication at <https://countries.demodb.dev/> is planned and
remains unverified until the website and read-only service are deployed.

```sql
-- Northwind order 11045 ships to Canada
SELECT c.name, c.iso2, c.iso3, c.currency_code, c.population, c.population_year,
       s.publisher AS population_source
FROM country_names n
JOIN countries c ON c.iso2 = n.iso2
LEFT JOIN sources s ON s.source_id = c.population_source_id
WHERE n.label = 'Canada';
```

| Recordset | Rows | Key |
|---|---|---|
| `countries` | 252 (216 with a World Bank population, all for 2025) | `iso2` |
| `country_aliases` | 25 | `alias`, references `countries.iso2` |
| `sources` | 3 | `source_id`, referenced by `countries` |
| `country_names` (view) | every name and differing alias | |

## Licence and attribution

The data is licensed under [CC BY 4.0](LICENSE). It is derived and modified
from GeoNames `countryInfo.txt` (© GeoNames, CC BY 4.0) and the World Bank
World Development Indicators `SP.POP.TOTL` (© The World Bank, CC BY 4.0); the
aliases are hand-checked DataTug mapping data. The full attribution and the
list of changes are in [`data-source/LICENSE.md`](data-source/LICENSE.md) and
in the `sources` table. Neither GeoNames nor the World Bank endorses this
database. The generated ModelSpec model and MeaningGraph meaning files are
CC0-1.0.

## Reproducing the fixture

`data-source/source.sqlite` is rebuilt from the geo reference data vendored in
[datatug/datatug-demo-project](https://github.com/datatug/datatug-demo-project)
at the commit pinned in `manifest.json` (`source.revision`, path
`demo-project-1/data/geo`). `source.recipe` pins the digest of every input
file; `source.databaseSha256` pins the committed SQLite bytes, and the
published `artifacts/countries.sqlite` is the same file byte for byte.

Provider exports, ModelSpec, MeaningGraph and the OVDB descriptor are
generated from `manifest.json` and `data-source/source.sqlite` by DemoDB's
immutable shared generator. CI fetches the pinned recipe inputs, rebuilds the
database and compares its full logical contents with the committed file,
downloads the generator from the pinned DemoDB websites revision, checks its
digest, regenerates every artifact, and rejects any uncommitted result.

```sh
python3 scripts/rebuild-source.py --geo /path/to/datatug-demo-project/demo-project-1/data/geo --check
python3 /path/to/demo-db-websites/scripts/provider-tools/generate.py --root .
git diff --exit-code
```

The intended read-only OVDB endpoint is configured to support schema, keyed
reads and queries after publication; those live capabilities are not yet
verified.
