# Browser Cache And Space

Maverick may keep disposable copies of verified app assets, selected read-only
data, and eligible versioned files in your browser. These copies can reduce
repeat downloads and make reopening content faster. The server remains the
source of truth, and cached data never grants access or confirms an action.

## View aggregate usage

Open **Settings → Cache** to see aggregate storage and activity for this browser
container. The page can show total bytes and entries, browser quota estimates,
cache reuse, evictions, request wait/retry timing, and service-worker recovery.
It does not list file names, messages, records, URLs, users, or workspace data.

Browser storage is best-effort. The browser may evict it, a Maverick update may
replace it, and some environments may not offer persistent storage. The
dashboard therefore does not promise that any item will remain on the device.

## Clear cache

Select **Clear cache**, then confirm. This removes Maverick's structured-data
and versioned-file cache from this browser container and cancels related pending
retries. It does not delete server files, workspace records, static app assets,
or storage belonging to other sites.

After clearing, features fetch required data again through their normal loading
flow. If cleanup reports that work is still pending, retry the action; Maverick
does not treat an incomplete durable deletion as success.

