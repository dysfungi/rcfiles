import sys as _sys


def _cdargs_resolve(alias):
    for f in (p'~/.config/cdargs', p'~/.cdargs'):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == alias:
                return parts[1]
    return None


@aliases.register('cdb')
def _cdb(args):
    if not args:
        cdargs
        return
    target = _cdargs_resolve(args[0])
    if target:
        cd @(target)
    else:
        print(f"cdargs: bookmark '{args[0]}' not found", file=_sys.stderr)


@aliases.register('mark')
def _mark(args):
    if not args:
        print("usage: mark <alias>", file=_sys.stderr)
        return 1
    # Capture $(pwd) into a local first: Python 3.14's PEP 701 f-string parser
    # cannot handle xonsh $()/@() subproc substitution inside an f-string literal.
    _pwd = $(pwd).strip()
    cdargs @(f"--add=:{args[0]}:{_pwd}")


@aliases.register('ca')
def _ca(args):
    if not args:
        print("usage: ca <alias>", file=_sys.stderr)
        return 1
    # See _mark: $() subproc syntax is illegal inside f-strings on Python 3.14.
    _pwd = $(pwd).strip()
    cdargs @(f"--add=:{args[0]}:{_pwd}")
