"""Verify local navigation, module imports, sources, and standalone HTML targets."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT=Path('docs')
class Links(HTMLParser):
    def __init__(self): super().__init__();self.links=[];self.ids=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id'):self.ids.add(attrs['id'])
        for key in ('href','src'):
            if attrs.get(key):self.links.append(attrs[key])
errors=[]
for html in ROOT.rglob('*.html'):
    parser=Links();parser.feed(html.read_text())
    for link in parser.links:
        parsed=urlsplit(link)
        if parsed.scheme or link.startswith('//') or link.startswith('#'):continue
        target=(html.parent/unquote(parsed.path))
        if target.is_dir():target/= 'index.html'
        if not target.exists():errors.append(f'{html}: missing {link}')
    if html.name=='index.html' and html.parent.name not in ('review',):
        for id in ('market-rows','all-feed','screen-feed','paper-rows','chart','book-rows','coverage','connection'):
            if id not in parser.ids:errors.append(f'{html}: missing {id}')
if errors:raise SystemExit('\n'.join(errors))
print('Verified',len(list(ROOT.rglob('*.html'))),'HTML pages and local link targets')
