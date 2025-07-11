from _utils import rc


@rc(interactive=True)
def __python_aliases(aliases):
    from pprint import pprint
    from sys import stderr

    @aliases.register
    def _p(args):
        if $XONSH_DEBUG:
            print(f"DEBUG: {args=}", file=stderr)
        print(*args)

    @aliases.register
    def _pp(args):
        if $XONSH_DEBUG:
            print(f"DEBUG: {args=}", file=stderr)
        pprint(args)


@rc(interactive=True)
def __miscellaneous_aliases(aliases):

    @aliases.register
    @aliases.return_command
    def _caff(args):
        hours = int(args[0]) if args else 8
        hours_in_minutes = hours * 60 * 60
        print(f"Caffeinating for {hours} hour(s)")
        return ["caffeinate", "-t", str(hours_in_minutes)]
