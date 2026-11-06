# Summary

Generated 2026-11-06 00:29 UTC

Cell values: what the server received on the wire (`sent_host`), what an aborted browser request had prepared (`prepared`), the client's own refusal (`refused`), or why the client did not participate (`skip`).

| case | mode | input | httpx | requests | aiohttp | urllib | curl | node | chromium |
|---|---|---|---|---|---|---|---|---|---|
| H01 | url | baseline: plain host with port | localhost:8321 | localhost:8321 | localhost:8321 | localhost:8321 | localhost:8321 | localhost:8321 | localhost:8321 |
| H02 | url | uppercase host input | localhost:8321 | localhost:8321 | localhost:8321 | LOCALHOST:8321 | LOCALHOST:8321 | localhost:8321 | localhost:8321 |
| H03 | override | baseline: explicit override, well-formed value | localhost:8321 | localhost:8321 | localhost:8321 | localhost:8321 | localhost:8321 | skip: node does not suppor | skip: chromium does not su |
| H04 | url | credentials in the URL; the Host must still point at localhost | localhost:8321 | localhost:8321 | localhost:8321 | user:pass@localhost:8321 | localhost:8321 | refused: Request cannot be | refused: fetch-error: Fail |
| H05 | url | the shape behind the MCP python-sdk finding: empty password, then @evil.com | evil.com:8321 | evil.com:8321 | evil.com:8321 | localhost:@evil.com:8321 | evil.com:8321 | skip: fetch skipped by iso | refused: fetch-error: Fail |
| H06 | url | two @ signs: which part is userinfo and which is the host? | localhost:8321 | localhost:8321 | localhost:8321 | user@evil.com@localhost:83 | refused: curl: (3) URL rej | refused: Request cannot be | refused: fetch-error: Fail |
| H07 | override | explicit override carrying userinfo | localhost:@evil.com | localhost:@evil.com | localhost:@evil.com | localhost:@evil.com | localhost:@evil.com | skip: node does not suppor | skip: chromium does not su |
| H08 | override | override with a port-looking prefix, then userinfo | localhost:0@evil.com | localhost:0@evil.com | localhost:0@evil.com | localhost:0@evil.com | localhost:0@evil.com | skip: node does not suppor | skip: chromium does not su |
| H09 | url | octal for 127.0.0.1; resolvers and parsers disagree | refused: InvalidURL: Inval | 0177.0.0.1:8321 | 0177.0.0.1:8321 | 0177.0.0.1:8321 | 127.0.0.1:8321 | skip: fetch skipped by iso | 127.0.0.1:8321 |
| H10 | url | decimal integer for 127.0.0.1 | 2130706433:8321 | 2130706433:8321 | 2130706433:8321 | 2130706433:8321 | 127.0.0.1:8321 | skip: fetch skipped by iso | 127.0.0.1:8321 |
| H11 | url | short form for 127.0.0.1 | 127.1:8321 | 127.1:8321 | 127.1:8321 | 127.1:8321 | 127.0.0.1:8321 | skip: fetch skipped by iso | 127.0.0.1:8321 |
| H12 | url | trailing dot: absolute FQDN | localhost.:8321 | localhost:8321 | localhost:8321 | localhost.:8321 | localhost.:8321 | skip: fetch skipped by iso | refused: fetch-error: Fail |
| H13 | url | percent-encoded first letter of localhost | %6cocalhost:8321 | localhost:8321 | %6cocalhost:8321 | localhost:8321 | localhost:8321 | skip: fetch skipped by iso | localhost:8321 |
| H14 | url | IDN input; punycode form is xn--lcalhost-n4a | xn--lcalhost-n4a:8321 | xn--lcalhost-n4a:8321 | xn--lcalhost-n4a:8321 | löcalhost:8321 | xn--lcalhost-n4a:8321 | skip: fetch skipped by iso | refused: fetch-error: Fail |
| H15 | url | underscore: invalid per RFC but accepted by many resolvers | under_score:8321 | under_score:8321 | under_score:8321 | under_score:8321 | under_score:8321 | skip: fetch skipped by iso | refused: fetch-error: Fail |
| H16 | url | baseline IPv6 literal | [::1]:8321 | [::1]:8321 | [::1]:8321 | [::1]:8321 | [::1]:8321 | [::1]:8321 | [::1]:8321 |
| H17 | url | IPv6 with a zone id (Linux loopback form) | refused: ConnectError: [Er | refused: ConnectionError:  | refused: ClientConnectorEr | refused: URLError: <urlope | [::1]:8321 | refused: URL parse threw:  | refused: fetch-error: Fail |
| H18 | url | empty port after the colon | refused: ConnectError: [Er | refused: ConnectionError:  | refused: ClientConnectorEr | refused: URLError: <urlope | refused: curl: (7) Failed  | refused: fetch failed | refused: fetch-error: Fail |
| H19 | url | port zero | refused: ConnectError: [Er | refused: ConnectionError:  | refused: ClientConnectorEr | refused: URLError: <urlope | refused: curl: (7) Failed  | skip: fetch skipped by iso | refused: fetch-error: Fail |
| H20 | url | port above 65535 | refused: OverflowError: co | refused: parse_url refused | refused: yarl refused: Por | refused: urlsplit refused: | refused: curl: (3) URL rej | refused: URL parse threw:  | refused: fetch-error: Fail |
| H21 | url | non-ASCII digits; a port must be ASCII digits per RFC 3986 | refused: ConnectError: [Er | refused: parse_url refused | refused: ClientConnectorEr | refused: urlsplit refused: | refused: curl: (3) URL rej | refused: URL parse threw:  | refused: fetch-error: Fail |
| H22 | override | trailing space in the header value | refused: LocalProtocolErro | localhost | localhost | localhost | localhost | skip: node does not suppor | skip: chromium does not su |
| H23 | override | port that is not a number | localhost:abc | localhost:abc | localhost:abc | localhost:abc | localhost:abc | skip: node does not suppor | skip: chromium does not su |
| H24 | override | CRLF injection attempt through the Host value | refused: LocalProtocolErro | refused: InvalidHeader: In | refused: ValueError: Newli | refused: ValueError: Inval | localhost | skip: node does not suppor | skip: chromium does not su |
| H25 | override | empty Host value | (empty) | (empty) | (empty) | (empty) | (empty) | skip: node does not suppor | skip: chromium does not su |
| H26 | override | non-ASCII digits via override | refused: UnicodeEncodeErro | refused: UnicodeEncodeErro | localhost:Û¸Û°Û¸Û° | refused: UnicodeEncodeErro | localhost:Û¸Û°Û¸Û° | skip: node does not suppor | skip: chromium does not su |

Full data with parse results, per-request raw headers and raw values: results/*.json