"""Keep saved web entry points usable after a canonical hostname change."""

from urllib.parse import quote, urlsplit

from core.installation.validation import hostname


def document_redirect(configuration: dict, *, path: str, request_host: str,
                      method='GET', query='', app_frame=False) -> str | None:
    if (method not in {'GET', 'HEAD'} or app_frame or not configuration.get('managed')
            or not (path in {'/', '/app'} or path.startswith('/app/'))):
        return None
    try:
        source = urlsplit('//' + request_host).hostname or ''
        if source in {'localhost', '127.0.0.1', '::1'} or source.endswith('.localhost'):
            return None
        source, target = hostname(source), hostname(configuration['hostname'])
    except ValueError:
        return None
    if source == target:
        return None
    location = 'https://' + target + quote(path, safe='/')
    return location + ('?' + quote(query, safe="=&%:+,/?@~!$'()*[]") if query else '')
