# Subscription Source Catalog

Публичный каталог источников и кандидатов для VPN Global Monitor.

Репозиторий содержит код каталога, документацию и безопасные generated metadata. Сетевой discovery и catalog compute выполняются на инфраструктуре владельца проекта, а не на GitHub-hosted Actions.

## Назначение

Каталог выполняет:

```text
public source discovery
→ fetch
→ parse
→ protocol filtering
→ public digest dedup
→ endpoint GeoIP hint
→ source quality/corroboration
→ country ranking
→ safe handoff to VGM
```

Каталог не определяет, работает ли узел фактически. Он также не является источником истины для страны выхода.

## Execution boundary

Внешние сетевые workloads выполняются вне GitHub Actions:

```text
owner-operated VPS
  ↓
discovery + third-party fetch + catalog compute
  ↓
validation + privacy/security checks
  ↓
sanitized generated metadata
  ↓
GitHub repository
```

GitHub Actions предназначены только для conventional software-development CI репозитория: unit tests, compile/static validation и security-boundary tests. Scheduled discovery, third-party subscription fetching и catalog computation в GitHub Actions не выполняются.

## Поддерживаемые протоколы поиска

```text
VLESS
VMess
Trojan
Shadowsocks
Hysteria2
```

WireGuard не входит в поисковый контракт каталога. `wg://`, `wireguard://`, приватные WireGuard-профили, PrivateKey и PresharedKey блокируются на публичной границе.

TUIC, SSR и другие протоколы не включаются в основной pipeline без отдельного утверждённого контракта.

## Что публикуется

Публичные exports содержат только безопасные данные, необходимые для отбора кандидатов:

- `node_digest` — непрозрачный selection handle;
- `source_id`;
- protocol;
- passive `endpoint_country`;
- pre-score;
- source count / independent source count;
- source quality metadata;
- freshness metadata.

Raw proxy URI, UUID, passwords, tokens, private keys и другие credentials в generated exports не публикуются.

## Country semantics

`endpoint_country` означает только пассивную геолокацию адреса endpoint.

```text
endpoint_country != verified_exit_country
```

Фактическая страна выхода определяется только приватным VPN Global Monitor после реальной L3-проверки через сам узел.

## Handoff

Основной контракт для VGM:

```text
exports/country_handoff_v4.json
schema: subscription-source-country-handoff-v4
```

Он предоставляет безопасный bounded список кандидатов по странам и ranking metadata для Country Query Planner.

Legacy handoff может временно существовать только ради совместимости потребителей. Его наличие не меняет основной контракт v4.

## Generated state

Каталог хранит generated state и exports:

```text
data/sources.json
data/node_index/
data/geo_cache.json
exports/
SOURCES.md
```

Эти файлы являются машинным состоянием каталога, а не ручной документацией. Их изменение выполняет owner-operated catalog pipeline после локальной валидации.

## GitHub Actions

В репозитории остаётся только обычный CI разработки ПО. CI не выполняет scheduled discovery, массовые обращения к third-party subscription/source URL или catalog compute.

## VPS execution

Reference deployment contract находится в `deploy/vps/` и `docs/vps-pipeline.md`. Runtime script устанавливается в `/usr/local/bin`; systemd запускает его независимо от SSH/Termius-сессии. Секреты хранятся только на VPS и не коммитятся в репозиторий.

## Безопасность

Публичный репозиторий никогда не должен содержать:

- private subscription URL;
- credential-bearing source URL;
- raw proxy URI export;
- API token;
- private key;
- персональный/provider account inventory;
- WireGuard client profile;
- runtime database приватного VGM.

Направление данных только одностороннее:

```text
public catalog → safe metadata → private VGM
```

Приватный VGM не выгружает свои credentials, trusted inventory или реальные runtime secrets обратно в этот репозиторий.

## Роль в общей системе

```text
Internet
  ↓
owner-operated Catalog Pipeline
  ↓ sanitized metadata
Subscription Source Catalog (GitHub)
  ↓ safe candidate metadata
VPN Global Monitor Query Planner
  ↓
private materialization
  ↓
VPS validation
  ↓
verified exit country + latency
  ↓
TOP-N
```

Каталог отвечает за широкий поиск и предварительный отбор. Решение о реальной работоспособности и качестве узла принимает только приватный validation plane.
