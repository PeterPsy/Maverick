export function websiteUrl(value) {
  if (typeof value !== "string" || !value.length || value.length > 4096 || /[\\\s\u0000-\u001f]/u.test(value)) throw new Error("invalid_website_url");
  const url = new URL(value), host = url.hostname.toLowerCase().replace(/\.$/u, "");
  if (url.protocol !== "https:" || url.port || url.username || url.password || host.includes(":") || host === "localhost" || /\.(localhost|local|internal)$/u.test(host)) throw new Error("website_scope_required");
  if (!/^(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/u.test(host) || !host.includes(".") || host.split(".").some(label=>!label || label.length>63 || label.startsWith("-") || label.endsWith("-"))) throw new Error("website_scope_required");
  if (/^\d+\.\d+\.\d+\.\d+$/u.test(host)) {
    const [a,b,c]=host.split(".").map(Number);
    if (a===0 || a===10 || a===127 || a>=224 || a===169 && b===254 || a===172 && b>=16 && b<=31 || a===192 && (b===168 || b===0 || b===2) || a===100 && b>=64 && b<=127 || a===198 && (b===18 || b===19 || b===51 && c===100) || a===203 && b===0 && c===113) throw new Error("website_scope_required");
  }
  url.hostname=host;
  return url.href;
}
