import logging

from _utils import rc


logger = logging.getLogger(__name__)


@rc(interactive=True)
def __python_aliases(aliases):
    from pprint import pprint

    @aliases.register("p")
    def _print(args):
        logger.debug("args=%r", args)
        print(*args)

    @aliases.register("pp")
    def _pretty_print(args):
        logger.debug("args=%r", args)
        for arg in args:
            pprint(arg)


@rc(interactive=True)
def __gnu_aliases(aliases):
    if !(command -v gsed >/dev/null):
        aliases["sed"] = ["gsed"]


@rc(interactive=True)
def __fun_aliases(aliases):
    aliases["starwars"] = ["telnet", "towel.blinkenlights.nl"]

    aliases["sitenamr"] = r"grep '^[a-z].*[^aeiou]er$' /usr/share/dict/words | shuf -n 1 | sed -r -e 's/er$/r/' -e r's/^(\w)/\1/'"
    aliases["sitenamd"] = r"grep '^[a-z].*[^aeiou]ed$' /usr/share/dict/words | shuf -n 1 | sed -r -e 's/ed$/d/' -e r's/^(\w)/\1/'"


@rc(interactive=True)
def __miscellaneous_aliases(aliases):
    import requests

    @aliases.register
    @aliases.return_command
    def _caff(args):
        hours = int(args[0]) if args else 8
        hours_in_minutes = hours * 60 * 60
        print(f"Caffeinating for {hours} hour(s)")
        return ["caffeinate", "-t", str(hours_in_minutes)]

    @aliases.register("eip")
    def _external_ip(args):
        response = requests.get("https://icanhazip.com")
        print(response.text.strip())

    aliases["iip"] = "/sbin/ifconfig | awk '/inet / { print $2; }' | grep -Fv 127.0.0.1"

    @aliases.register("aip")
    def _all_ip(args):
        internal = $(iip)
        external = $(eip)
        print(f"External IP:\n{external}\n\nInternal IP:\n{internal}")
