/** Exact configured development hosts and Core-generated local app frames. */
export function isAdminDevTarget(targets, scheme, host, port) {
  const frame = /^af-[0-9a-f]{24}\.sidecars\.([a-z0-9-]+\.localhost)$/.exec(host);
  const parent = frame ? frame[1] : host;
  return targets.has(`${scheme}://${parent}:${port}`);
}

/** A browser also uses CONNECT for plaintext ws on a configured HTTP dev port. */
export function proxyTunnelUrl(authority, targets) {
  const url = new URL(`https://${authority}`);
  const port = Number(url.port || 443);
  if (isAdminDevTarget(targets, "http", url.hostname, port)) url.protocol = "http:";
  return url;
}
