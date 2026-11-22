"""Check generated primary pages, local navigation, source rows and snapshot provenance.

This checks links' structure/local targets and recorded provenance, NOT the current
availability or truth of every external website. Live API connectivity is separate.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote

ROOT = Path('docs')
OFFICIAL = {'docs.kalshi.com', 'external-api.demo.kalshi.co', 'demo-api.kalshi.co', 'docs.github.com'}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.rows = [], set(), []
        self.row, self.in_body, self.view = None, False, ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids:
                errors.append(f'{current}: duplicate id {attrs["id"]}')
            self.ids.add(attrs['id'])
        if tag == 'body':
            self.view = attrs.get('data-view', '')
        if tag == 'tbody':
            self.in_body = True
        if tag == 'tr' and self.in_body:
            self.row = []
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])
                if self.row is not None:
                    self.row.append(attrs[key])

    def handle_endtag(self, tag):
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == 'tbody':
            self.in_body = False


errors = []
parsers = {}
current = ''
for html in ROOT.rglob('*.html'):
    current = html
    parser = Links()
    parser.feed(html.read_text())
    parsers[html.resolve()] = parser
    for row in parser.rows:
        if not any(urlsplit(url).scheme == 'https' and urlsplit(url).hostname in OFFICIAL for url in row):
            errors.append(f'{html}: static table row missing an official source')
    if parser.view in {'all', 'gas', 'elections', 'culture', 'crypto', 'golf'}:
        for identifier in ('market-rows', 'all-feed', 'screen-feed', 'paper-rows', 'chart', 'book-rows', 'coverage', 'connection', 'search', 'sort'):
            if identifier not in parser.ids:
                errors.append(f'{html}: missing {identifier}')
    if parser.view == 'portfolio':
        for identifier in ('paper-rows', 'strategy-cards', 'connection'):
            if identifier not in parser.ids:
                errors.append(f'{html}: missing {identifier}')
for html, parser in parsers.items():
    for link in parser.links:
        parsed = urlsplit(link)
        if parsed.scheme or link.startswith('//'):
            if parsed.scheme in {'javascript', 'data'}:
                errors.append(f'{html}: unsafe executable link')
            continue
        target = html if not parsed.path else (html.parent / unquote(parsed.path)).resolve()
        if target.is_dir():
            target /= 'index.html'
        if not target.exists():
            errors.append(f'{html}: missing {link}')
        elif parsed.fragment and target in parsers and parsed.fragment not in parsers[target].ids:
            errors.append(f'{html}: missing fragment {link}')
for script in (ROOT / 'assets').glob('*.mjs'):
    for path in re.findall(r"from\s+['\"](\.[^'\"]+)['\"]", script.read_text()):
        if not (script.parent / path).exists():
            errors.append(f'{script}: missing module {path}')
snapshot = json.loads((ROOT / 'data/snapshot.json').read_text())
for event in snapshot.get('events', []):
    if event.get('topic') not in {'gas', 'elections', 'culture', 'crypto', 'golf'}:
        errors.append(f'Snapshot event outside scoped topics: {event.get("event_ticker")}')
    for record in [event, *event.get('markets', [])]:
        url = urlsplit(record.get('source_url', ''))
        if url.scheme != 'https' or url.hostname not in {'external-api.demo.kalshi.co', 'demo-api.kalshi.co'}:
            errors.append('Snapshot record missing official demo endpoint')
        if not record.get('observed_at'):
            errors.append('Snapshot record missing original observation timestamp')
        for evidence in [*record.get('history_snapshots', {}).values(), record.get('orderbook_snapshot')]:
            if evidence is None:
                continue
            evidence_url = urlsplit(evidence.get('source_url', ''))
            if evidence_url.scheme != 'https' or evidence_url.hostname != 'external-api.demo.kalshi.co':
                errors.append('Candle/depth snapshot missing official source')
            if not evidence.get('observed_at'):
                errors.append('Candle/depth snapshot missing original observation time')
if snapshot.get('events') and not snapshot.get('generated_at'):
    errors.append('Nonempty snapshot requires an observation generation timestamp')
for manifest in [ROOT / 'data/verification.json', Path('services/kalshi/verification.json')]:
    data = json.loads(manifest.read_text())
    for row in data['facts'] + data['flagged_for_review']:
        if urlsplit(row['source_url']).hostname not in OFFICIAL:
            errors.append(f'{manifest}: unofficial verification source {row["id"]}')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'Checked {len(parsers)} primary pages, all local links/fragments/imports, official source links on every static table row, and snapshot provenance.')
