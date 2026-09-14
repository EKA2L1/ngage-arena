# Shared accounts protocol

`AccountStore` owns the single `community.sqlite3` account namespace, scrypt password verifiers and provider/device bindings. Every protocol receives the same store from `arena.runtime`; games receive its connection and use canonical account IDs. Never create a per-game password database.

Password authentication uses the SDK credential format. Tomb Raider's device-only identity starts separate from password accounts even when nicknames match. Explicit operator binding requires the account password and refuses to transfer an already-bound identity. Tomb Raider retains its local player IDs for stable replay/challenge ownership; `Store.account_id` resolves the shared account.

On first start, an existing `ashen.sqlite3` is backed up into `community.sqlite3` without modifying the source. Subsequent starts do not reimport it. Separate directories are not merged by matching names.

```sh
.venv/bin/python -m arena.services.accounts.store --data data create Player
.venv/bin/python -m arena.services.accounts.store --data data link-tomb 'Local player' --account Player
```

Both commands prompt for the account password. Back up the entire stopped data directory, including `identity.key`. A bound device identity is an account credential.
