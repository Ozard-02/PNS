# Future Improvements

## High Priority

- [ ] **CI/CD pipeline with GHCR**
  - GitHub Actions: build & push immagine su `ghcr.io/Ozard-02/PNS` a ogni push su `main`
  - Webhook Flask sulla VM per pull automatico e restart del container
  - HMAC-SHA256 per sicurezza webhook
  - Vedi `plan.md` per dettagli implementativi

- [ ] **Separare configurazione VM dal codice**
  - `docker-compose.prod.yml` o override per usare `image:` invece di `build: .`
  - Script di setup VM documentato

## Medium Priority

- [ ] **Notifiche su fallimento**
  - Notificare via Telegram/email se il daily run fallisce
  - O se il webhook non riesce a riavviare il container

- [ ] **Healthcheck sul container**
  - Endpoint o probe che verifichi che cron sia vivo
  - Restart automatico se morto

- [ ] **Backup automatico del DB**
  - Backup periodico di `/data/eventi.db` su storage esterno
  - Opzionale: retention policy (es. ultimi 7 giorni)

- [ ] **Log centralizzati**
  - Invece di docker logs, mandare i log a un file fuori dal container con rotazione

## Low Priority / Nice to have

- [ ] **Dashboard web leggera**
  - Mostrare ultimi eventi trovati, feedback, stato del container

- [ ] **Test automatizzati in CI**
  - Unit test per `db.py`, `profile_engine.py`, `search_client.py`
  - Eseguirli in GitHub Actions prima del build

- [ ] **Multi-arch image**
  - Build per `linux/amd64` e `linux/arm64` (utile se la VM è su ARM)

- [ ] **Lock file per esecuzioni concorrenti**
  - Evitare che due run di `main.py` partano in contemporanea se cron e manuale si sovrappongono
