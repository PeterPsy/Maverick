# M6 PWA cache — scheda esecutiva di chiusura

Data: 6 settembre 2026. **Preparazione, non certificazione di rilascio.**
Il codice è verificato; i tre gate operativi sotto restano aperti.

## 1. Identità e decisioni prima dell'esecuzione

Candidato proposto: `724c93e50c8e55585b88246ab489ca918185be00`.
Non usare il `design` corrente come sinonimo: altri agenti continuano a modificarlo.
Il [binding dei dieci manifest](pwa_cache_website_concurrency_candidate_2026-09-06.json)
e il [rapporto delle regressioni](pwa_cache_website_concurrency_validation_2026-09-06.md)
sono i riferimenti del candidato. Una modifica a codice/asset richiede nuova
identità e nuove evidenze; un documento preparatorio non ricertifica altri commit.

| Decisione del release/product owner | Stato |
|---|---|
| Confermare candidato, release owner e operatore del deployment | Da confermare |
| Indicare ambiente/URL di collaudo e target del rollout | Da indicare; nessun riavvio condiviso autorizzato implicitamente |
| Confermare isolamento del pilot, account/workspace di prova e accesso ai dispositivi | Da indicare; solo dati sintetici nel collaudo |
| Fissare versioni numeriche minime e correnti di OS/browser | Aperta nel piano, sezione 15.2; non deducibile dai nomi dei profili |
| Approvare scope delle cohort, finestre, soglie e finestra di manutenzione | Da approvare prima di cambiare flag |
| Assegnare operatore/reviewer della matrice fisica e della redazione | Da indicare |

Proposta, **non ancora approvata**: ambiente di collaudo separato dal servizio
condiviso; baseline di 30 minuti; pilot presidiato di almeno 60 minuti con letture
fredde/calde e recovery in ciascuna delle otto app; per un rollout multiutente,
24 ore di osservazione per incremento. Tempo senza traffico non è evidenza:
concordare prima anche il campione minimo e i limiti di regressione su errori,
richieste, byte, tempi e retry rispetto alla baseline. Le soglie di sicurezza
sono invece tolleranza zero, come nel runbook M6.

Scope non riducibile implicitamente: Website Studio, Storage, App Store,
Fitness Coach, Calendar, Chat, CRM e Mail; Storage file cache è una dimensione
distinta. Per i byte serve l'approvazione Storage dell'esatto file/versione:
il consenso CRM/Mail non approva automaticamente allegati o file sconosciuti.

## 2. Preflight del candidato

- [ ] Operatore: attestare che il deployment serve codice e tutti i dieci
  manifest del candidato, non soltanto il bundle Website Studio.
- [ ] Operatore: verificare HTTPS con trust ordinario, origini isolate app/widget,
  login e due scope di prova; nessun bypass dei certificati o dell'owner check.
- [ ] QA: eseguire il gate automatico del
  [runbook M6](../runbooks/pwa_cache_operations_m6.md#automated-hardening-gate)
  prima di ogni cambio di rollout; conservare risultati riferiti al candidato.
- [ ] Operatore: salvare una copia protetta della configurazione precedente e
  provare l'accesso alla procedura normale di restart/health. Non pubblicare env,
  password, cookie o token nel rapporto.
- [ ] QA: misurare baseline server-first con data cache e file cache disabilitate.
- [ ] Owner: autorizzare l'abilitazione **nel solo collaudo isolato** necessaria
  per provare realmente gli adapter; non è l'avvio del rollout agli utenti.

Verifiche aggiuntive eseguite durante questa preparazione: audit PWA superato,
21 test Python audit/device e 2 test Settings superati. Esecuzione da export Git
integrale del candidato; 3.559 file tracciati verificati prima e dopo, dipendenze
locali già installate riutilizzate. Non sono una nuova esecuzione dei 653 test
del rapporto precedente, né una prova fisica o un drill operativo.

## 3. PWA-098: matrice da eseguire sui dispositivi reali

Usare la [matrice candidate-bound](pwa_cache_website_concurrency_device_matrix_2026-09-06.json)
come template, conservando lo storico pending. La copia compilabile tramite
Storage è prevista in
`storage/generated/development/maverick-pwa-m6-device-evidence.json`, ma non è
ancora pubblicata: vedere il blocco di accesso in fondo a questa scheda.
Non cambiare `release_id` per riutilizzare risultati di un'altra build.

| Profilo canonico | Scenari comuni | Scenario privato aggiuntivo | Esito attuale |
|---|---:|---:|---|
| `safari-macos-minimum-browser` | 8 | 1 | pending |
| `safari-macos-current-browser` | 8 | 1 | pending |
| `safari-macos-current-dock` | 8 | — | pending |
| `safari-ios-ipados-minimum-browser` | 8 | 1 | pending |
| `safari-iphone-current-browser` | 8 | 1 | pending |
| `safari-iphone-current-home-screen` | 8 | — | pending |
| `chrome-edge-current-desktop-browser` | 8 | 1 | pending |
| `chrome-current-desktop-app` | 8 | — | pending |

Totale: **8 profili, 69 esiti**, non necessariamente otto dispositivi diversi.
Browser, Dock e Home Screen vanno eseguiti come contenitori distinti. Un Chrome
pilotato sul server o WebKit emulato non sostituisce i dispositivi fisici.
Non dedurre il supporto della versione minima dal solo risultato sulla corrente.

### Preparazione di ogni contenitore

Usare un profilo/container dedicato e dati sintetici, senza cancellare il profilo
personale. Registrare OS e versione browser effettivi e verificare il candidato
servito. Preparare almeno una lettura cache-eligible di ogni app inclusa, due
scope di test distinguibili e un file/versione approvato. Per i controlli
distruttivi del solo cache store, lavorare sotto supervisione dell'operatore;
non riempire il disco del dispositivo o cancellare l'intera origine.

### Scenari e criterio di pass

| Chiave JSON | Procedura sul dispositivo e condizione di successo |
|---|---|
| `cold-launch` | Primo avvio con rete nel contenitore di test vuoto; login, shell normale, app e letture valide. Verificare worker/precache del manifest e assenza di UI offline o authority da cache. |
| `warm-launch` | Scaldare le letture delle otto app e il file approvato; chiudere e riaprire lo stesso contenitore. Verificare cache hit eleggibili, lease/expiry e normale percorso server-first per miss o risorse escluse. Non richiedere login o autorizzazioni offline. |
| `worker-update` | Sul solo host di collaudo seguire il drill A→B del runbook worker: due client, install interrotta, A preservata, ripristino e attivazione B. B deve essere il candidato esatto. Registrare separatamente identità del predecessore; se A e B hanno lo stesso worker/build id non è un test di update. |
| `worker-recovery` | Sul cache statico posseduto rimuovere/corrompere una sola entry; recovery senza rete deve fallire preservando le altre entry verificate; con rete deve restituire `MAVERICK_SW_RECOVERED` e ripristinare il precache. |
| `quota-pressure` | Con fixture sintetiche e limiti concordati esercitare pressione/LRU e percorso di mancata persistenza nel browser reale, per dati e file. La risposta server valida deve restare visibile, l'eviction bounded e la UI normale. Registrare il metodo; non chiamare una semplice navigazione una prova di quota. Se la pressione non è stata esercitata, lasciare pending. |
| `intermittent-network` | Scaldare, interrompere e ripristinare trasporto durante letture; tree/iframe restano, miss in loading normale, retry bounded/cancellabile. Cambiare dati sintetici A→B durante l'interruzione e verificare recovery anche senza richiesta pendente; Website Studio deve aggiornare la route corrente e quelle già calde. Nessun invio differito o duplicato. |
| `logout-cleanup` | Con dati/file caldi e una lettura pendente fare logout; UI autenticata ritirata subito, pending cancellati, cleanup durevole completato. Un altro login non vede A; una vecchia risposta tardiva non ripubblica. Un cleanup `pending` non passa. |
| `workspace-switch-cleanup` | Passare da scope A a B durante una lettura; B non mostra dati/file di A, vecchie richieste cancellate e cleanup completato. Tornare ad A senza far rivivere pubblicazioni obsolete. |
| `private-storage-degradation` | Solo per i cinque profili browser: eseguire anche in navigazione privata. Con storage negato/effimero la risposta server resta valida, senza crash, persistenza promessa o UI di modalità. Annotare la condizione osservata; non assumere che privato significhi sempre storage negato. |

Per update/recovery usare i passaggi completi del
[runbook worker](../runbooks/pwa_shell_v2.md#update-and-interrupted-install-drill).
Un fallimento richiede correzione e nuova verifica, non trasformazione in skip.
Prima di collaudare B va quindi concordato anche un predecessore verificato con
worker/build id differente: i precedenti fix solo Website Studio non lo forniscono.
Predecessore disponibile in Git, **proposto solo per il laboratorio sintetico**:
`dac2d8fc695d180a5b304bd674bda147962305a4`, build Shell
`96448267645e6924e4af1c44df494bf9787c95893cb4891bea06b45997208574`.
B ha build Shell `84699ab3435c079dbb87461c448bb3f805c2d1edec5245780ccc05246cf8cf4b`;
i due manifest hanno 16 entry precache e identità diverse, verificate in Git.
Questo controllo non è l'esecuzione dell'update sul dispositivo.

### Raccolta e validazione

Compilare soltanto gli esiti realmente osservati. Nel JSON canonico mantenere
solo i campi previsti: release id, timestamp UTC con timezone, ambiente fisico,
OS/browser, profili e pass/fail; `redaction_reviewed: true` solo dopo revisione.
Tenere il diario operativo separato e redatto: niente URL, nomi file, contenuti,
identificativi personali, cookie, token, HAR grezzi o screenshot di dati reali.

```sh
python3 scripts/pwa_device_regression.py verify \
  --input /secure/release-evidence/pwa-device-regression.json \
  --expected-release-id 724c93e50c8e55585b88246ab489ca918185be00
```

Il template attuale è stato verificato e correttamente rifiutato (exit 1):
69 pending, timestamp assente e redazione non attestata. Nessun gate superato.
Archiviare hash ed esito del JSON completato. Per un tag di release usare
l'identità concordata prima delle prove e verificarne il legame immutabile al
commit: non rietichettare un'evidenza dopo il test. Il workflow di promozione
richiede un prerelease/tag esatto e la verifica fisica; non pubblicare fuori gate.

## 4. Rollout controllato, solo dopo la matrice fisica

1. Confermare risultati preflight/device, owner e finestra. Rileggere baseline
   con cache dati/file off e verificare che tutte le app funzionino normalmente.
2. Cambiare una dimensione alla volta: prima Website Studio, poi Storage
   catalog/preview, file cache separatamente e tutte le altre app approvate.
   Non cambiare insieme worker, schema e tutti gli adapter.
3. Per un ambiente multiutente seguire la progressione raccomandata
   **1 → 5 → 25 → 50 → 100%**, osservando ogni passo prima di autorizzare il prossimo.
   Su un ambiente con un solo utente/workspace le percentuali possono selezionare
   nessuno: concordare uno scope pilot isolato significativo, senza spacciare
   100% del pilot per 100% degli utenti reali.
4. Le cohort workspace e utente si intersecano, anche fra gate globale e per-app.
   Esplicitare tutte le percentuali; omissione significa 100% di un flag già on.
   Non cercare una percentuale che includa il proprio utente senza prima
   approvare la popolazione aggiuntiva che ne deriverebbe.
5. Applicare flag tramite la configurazione del deployment, non con un semplice
   `export` nella shell dell'agente. Riavviare Core con la procedura concordata,
   verificare `/health`, poi ricaricare Base Shell.
6. Dalla sessione autenticata verificare `/api/pwa/config` e il
   `data_cache_enabled` delle app nella risposta `/api/apps` del workspace.
   La sola proiezione globale non prova il gate per-app. Provare almeno una
   sessione inclusa e una esclusa, senza esportarne le identità.
7. Misurare per app letture cold/warm, revalidation, recovery, miss/expiry e
   cancellation; per Storage includere bytes approvati e bytes esclusi.
   Usare Settings → Cache per gli aggregati; non raccogliere payload tecnici.
8. Chiudere la finestra soltanto con campione sufficiente, metriche entro le
   soglie approvate e nessun incidente. Un solo test sintetico o contatori a
   zero non costituiscono osservazione di una cohort.

Registro per **ogni** passo: candidato; inizio/fine UTC; dimensione/app; flag e
percentuali prima/dopo; conteggio sessioni incluse/escluse; richieste/byte/tempi,
hit/miss/error/eviction/quota/retry e attese; esito; decisione dell'owner.
Le attese correnti sono della sola finestra Shell osservata, non di tutti gli utenti.

## 5. Drill rollback operativo presidiato

Eseguire sullo stesso candidato e deployment concordato, dopo un pilot realmente
attivo, non soltanto con mock o unit test. Conservare tutti gli orari e gli esiti.

1. Scaldare cache dati/file approvate e avviare una lettura controllata; preparare
   sentinel sintetiche in namespace non posseduti per verificare che restino intatte.
2. Disabilitare il flag della sola app; applicare e riavviare tramite procedura
   normale, health, reload. Verificare il gate per-app off e letture server-first
   ancora valide, senza cancellare i byte come prerequisito.
3. Provare anche lo stop cohort con una percentuale a zero, quindi il kill switch
   globale dati per il caso multi-app; verificare config e server-first dopo
   ogni restart/reload. Non riabilitare altre cohort per errore.
4. Disabilitare separatamente `MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE`; verificare
   fetch/preview server-first del file e che il rollback non richieda la sua
   cancellazione sul server o una pulizia immediata di tutti i byte locali.
5. Provare il kill switch worker come nel runbook: disabilitare
   `MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2`, health e load con rete. Unregister
   `/sw.js` e rimozione dei soli tre namespace statici posseduti; IndexedDB,
   OPFS e sentinel estranee preservate. Config irraggiungibile non equivale a off.
6. Nello scope di prova eseguire anche Settings → Clear cache: risultato complete,
   attese cancellate, dati/file privati rimossi e nessuna pubblicazione tardiva.
   Storico resettato soltanto dopo completamento. Non usare Clear site data.
7. Ripristinare solo la configurazione approvata dall'owner, health e reload;
   se non è approvata riattivazione, lasciare il pilot disabilitato. Misurare
   tempo da comando di stop a config osservata/off e ripristino server-first.

Rollback immediato e stop promozione per cross-scope, authority da cache,
render expired, metriche non redatte, retry storm/duplicati, cleanup fallito o
cache che blocca una risposta server valida. Non attendere la fine della finestra.

## 6. Firma di chiusura, non anticipabile

- [ ] PWA-098: tutti i 69 esiti fisici pass, versioni coerenti con la decisione
  di supporto, JSON redatto/fresco, verifier exit 0 sul candidato esatto.
- [ ] Rollout: scope completo delle otto app e file cache, cohort eseguite con
  metriche e finestre approvate; configurazione finale e go/no-go registrati.
- [ ] Rollback: drill reale con flag/config, restart/health, server-first,
  cleanup e isolamento documentati; owner ne accetta l'esito.
- [ ] Rilettura finale dei manifest serviti e delle evidenze: nessun candidato
  diverso o modifica concorrente entrata nel deployment senza ricertificazione.
- [ ] Aggiornamento guarded tramite Storage del piano (stato, M5/M6, PWA-098,
  rollout/rollback e Definition of Done); rilettura integrale e hash verificato.

Solo allora dichiarare M6 e il piano chiusi. Allo stato di questo documento
nessun flag condiviso è cambiato, nessun servizio condiviso è stato riavviato
e nessuna riga fisica, cohort o drill è dichiarata passata.

### Pubblicazione e sincronizzazione ancora da eseguire

La creazione della copia operativa in
`storage/generated/development/maverick-pwa-cache-m6-closeout.md` è stata
rifiutata dalla superficie ufficiale con `authentication_required`; anche i
successivi controlli read-only Core e Storage restituiscono lo stesso errore.
Nessun file Storage è stato creato da questa preparazione e il piano non è
stato modificato. Occorre ripristinare l'accesso ufficiale, poi pubblicare la
scheda e la matrice e aggiornare il piano con confronto SHA e rilettura completa.
Non è stato usato un accesso diretto ai file per aggirare l'autenticazione.
Ultima lettura integrale valida del piano: 8 pagine, 95.978 byte, SHA-256
`7af042a2e0fcf116dec63d7a88f8032a0a028a5e36f9a2a9fd8cfec9a66837d6`.
