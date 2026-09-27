# Политика безопасности

## Публичная граница

Этот репозиторий публичный. В него запрещено добавлять приватные subscription URL, credentials, токены, API keys, private keys, персональные/provider конфигурации и любые данные, позволяющие восстановить приватный доступ.

Каталог принимает только публичные HTTP/HTTPS source URL. URL с userinfo credentials, подозрительными auth/query parameters или credential-like значениями должны отклоняться до публикации.

## WireGuard

WireGuard полностью исключён из публичного search contract.

Запрещены:

- `wg://`;
- `wireguard://`;
- `PrivateKey`;
- `PresharedKey`;
- полный WireGuard client profile;
- account-derived WireGuard inventory;
- экспорт provider/private WireGuard nodes.

PublicKey, Endpoint и country metadata сами по себе не считаются секретом, но не должны использоваться как обходной путь для публикации персонального inventory.

## Proxy credentials

Публичный каталог не должен публиковать raw VLESS/VMess/Trojan/Shadowsocks/Hysteria2 URI или поля, из которых можно восстановить credential.

В safe exports допускаются только bounded selection metadata, например digest/source/protocol/passive country/ranking/freshness information.

## Направление данных

Разрешено только:

```text
public catalog → safe metadata → private VPN Global Monitor
```

Запрещено возвращать из приватного VGM/VPS в публичный каталог:

- trusted inventory;
- raw URI;
- credentials;
- runtime SQLite;
- exit IP history, если она раскрывает приватный operational state;
- provider account data.

## Fail closed

Если источник или payload неоднозначен с точки зрения секрета, он отклоняется.

Secrets не должны появляться в:

- issues;
- pull requests;
- Actions logs;
- commit messages;
- generated documentation;
- artifacts.
