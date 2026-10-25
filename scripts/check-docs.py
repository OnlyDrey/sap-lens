"""Offline repository Markdown/image/anchor checks. No network or file mutations."""
import argparse
from html import unescape
from pathlib import Path
import re
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]


def visible(text):
    return re.sub(r'(?ms)^[ ]{0,3}(```|~~~)[^\n]*\n.*?^[ ]{0,3}\1[^\n]*(?:\n|$)',lambda match:'\n'*match[0].count('\n'),text)


def anchors(text):
    text=visible(text);result=set(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']',text));counts={}
    for heading in re.findall(r'(?m)^[ ]{0,3}#{1,6}\s+(.+?)\s*#*$',text):
        heading=re.sub(r'<[^>]+>','',unescape(heading)).lower().strip()
        slug=re.sub(r'[^\w\- ]','',heading).replace(' ','-')
        number=counts.get(slug,0);counts[slug]=number+1
        result.add(slug+('-'+str(number) if number else ''))
    return result


def check(paths,root=ROOT):
    failures=[];cache={}
    for path in paths:
        text=visible(path.read_text(encoding='utf-8'))
        targets=[(match.start(),match[1].strip('<>')) for match in re.finditer(r'!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)',text)]
        targets += [(match.start(),match[1]) for match in re.finditer(r'\b(?:href|src)=["\']([^"\']+)["\']',text)]
        for position,value in targets:
            if re.match(r'^[a-zA-Z][\w+.-]*:',value) or value.startswith('//'):continue
            target,_,fragment=unescape(value).partition('#');target=unquote(target.split('?',1)[0]);fragment=unquote(fragment)
            destination=(path.parent/target).resolve() if target else path.resolve()
            error=None
            if not destination.is_relative_to(root.resolve()) or not destination.exists():error='missing/nonrepository target'
            elif fragment and destination.is_file() and destination.suffix.lower()=='.md':
                if destination not in cache:cache[destination]=anchors(destination.read_text(encoding='utf-8'))
                if fragment not in cache[destination]:error='missing Markdown anchor'
            if error:failures.append((str(path.relative_to(root)),text[:position].count('\n')+1,value,error))
    return failures


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args()
    paths=[ROOT/name for name in ('README.md','AGENTS.md','LICENSE.md') if (ROOT/name).exists()]
    paths += sorted((ROOT/'docs').rglob('*.md'))+sorted((ROOT/'examples').rglob('*.md'))
    failures=check(paths)
    for path,line,target,error in failures:print(f'{path}:{line}: {error}: {target}')
    print(f'Documentation links: {len(paths)} Markdown files, {len(failures)} failures. External URLs were not fetched.')
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
