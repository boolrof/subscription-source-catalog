# Subscription Source Catalog

Публичный каталог источников и кандидатов для VPN Global Monitor.

Репозиторий автоматически находит и обрабатывает публичные subscription/source URL, извлекает поддерживаемые proxy URI, выполняет безопасную предварительную дедупликацию и пассивную геолокацию endpoint, а затем публикует ограниченные метаданные для приватного query engine.

## Назначение

Каталог уменьшает объём работы, который приходится выполнять приватному VPS.

Он отвечает за дешёвые операции:

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

Каталог хранит generated state и exports, используемые последующими workflow и VGM:

```text
data/sources.json
data/node_index.json
data/geo_cache.json
exports/
SOURCES.md
```

Эти файлы являются машинным состоянием каталога, а не ручной документацией. Их изменение выполняется workflow/compute pipeline.

## GitHub Actions

### Discovery

Периодически ищет и проверяет новые публичные источники в пределах заданного budget.

### Compute

Пересчитывает node index, country ranking и safe handoff exports.

### CI

Проверяет parser, security boundary, deterministic compute contracts и отсутствие запрещённых данных.

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
Subscription Source Catalog
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
