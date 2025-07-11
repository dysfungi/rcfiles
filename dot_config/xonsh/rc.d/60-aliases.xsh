import logging

from _utils import rc


logger = logging.getLogger(__name__)


@rc(interactive=True)
def __python_aliases(aliases):
    from pprint import pprint

    @aliases.register
    def _p(args):
        logger.debug("args=%r", args)
        print(*args)

    @aliases.register
    def _pp(args):
        logger.debug("args=%r", args)
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
