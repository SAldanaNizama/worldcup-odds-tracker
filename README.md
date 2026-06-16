# Worldcup Odds Tracker

Ingesta periódica de cuotas del Mundial desde [The Odds API](https://the-odds-api.com/) hacia Supabase.

## Estructura

```
worldcup-odds-tracker/
├─ .github/
│  └─ workflows/
│     └─ ingest-odds.yml
├─ scripts/
│  └─ ingest_odds.py
├─ requirements.txt
├─ .env.example
└─ README.md
```

## Configuración local

1. Instala dependencias:

   ```bash
   pip install -r requirements.txt
   ```

2. Copia `.env.example` a `.env` y completa tus credenciales:

   ```bash
   cp .env.example .env
   ```

3. Ejecuta la ingesta:

   ```bash
   python scripts/ingest_odds.py
   ```

   Salida esperada si todo va bien:

   ```
   API requests used: 1
   API requests remaining: 499
   Eventos recibidos: 10
   Ingesta completada. Odds insertadas: 120
   ```

## Verificar en Supabase

Después de la primera ingesta, ejecuta en el SQL Editor de Supabase:

```sql
select 
  external_id,
  home_team_name,
  away_team_name,
  start_time,
  status
from events
order by start_time asc;
```

```sql
select 
  o.selection,
  o.odds,
  o.implied_probability,
  o.snapshot_time,
  b.name as bookmaker,
  m.name as market
from odds_snapshots o
join bookmakers b on b.id = o.bookmaker_id
join markets m on m.id = o.market_id
order by o.snapshot_time desc
limit 50;
```

Objetivo de esta fase: ver `events` con partidos, `odds_snapshots` con cuotas históricas e `ingestion_logs` con estado `success`.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `SUPABASE_URL` | URL de tu proyecto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (solo backend/scripts) |
| `ODDS_API_KEY` | API key de The Odds API |
| `ODDS_SPORT_KEY` | Deporte (default: `soccer_fifa_world_cup`) |
| `ODDS_REGIONS` | Región de casas de apuestas (default: `eu`) |
| `ODDS_MARKETS` | Mercados (default: `h2h`) |
| `ODDS_ODDS_FORMAT` | Formato de cuota (default: `decimal`) |

No subas tu `.env` al repositorio.

## Probar el sport key

Antes de correr la ingesta, verifica que el deporte esté disponible en tu plan. Consulta los deportes activos en:

```
https://api.the-odds-api.com/v4/sports/?apiKey=TU_API_KEY
```

Busca algo como `soccer_fifa_world_cup`. Si no aparece, el problema es cobertura o plan de la API, no el script.

## Tablas Supabase requeridas

- `events` — columnas `home_team_name`, `away_team_name`
- `bookmakers`
- `markets`
- `odds_snapshots`
- `ingestion_logs`

Para verificar columnas de `events`:

```sql
select column_name
from information_schema.columns
where table_name = 'events'
order by ordinal_position;
```

Si tu tabla usa `home_team` / `away_team` en lugar de `home_team_name` / `away_team_name`, ajusta el script en consecuencia.

## GitHub Actions

El workflow `.github/workflows/ingest-odds.yml` ejecuta la ingesta cada 6 horas (`0 */6 * * *`, UTC) y también permite lanzarla manualmente (`workflow_dispatch`).

### Secrets en GitHub

En **Repository → Settings → Secrets and variables → Actions → New repository secret**, agrega:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ODDS_API_KEY`

Configura los secrets solo después de confirmar que la ingesta funciona en local.
