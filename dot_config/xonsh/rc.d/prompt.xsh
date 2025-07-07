"""
References:
    https://xon.sh/tutorial.html#customizing-the-prompt
"""
import time
from xonsh.built_ins import XSH
from xonsh.prompt import gitstatus, vc
from xonsh.prompt.base import PromptField, PromptFields


##########
# PROMPT #
##########

# $PROMPT_REFRESH_INTERVAL = 1
# $UPDATE_PROMPT_ON_KEYPRESS = True

# https://xon.sh/envvars.html#interactive-prompt
# $BOTTOM_TOOLBAR = "{branch_color}{gitstatus.branch}{BOLD_BLUE}{gitstatus.ahead}{BOLD_RED}{gitstatus.behind}{env_name: {YELLOW}{}}"
try:
    from xontrib.prompt_vi_mode import vi_mode
except ImportError as exc:
    print(exc)
    $VI_MODE = True
else:
    # https://github.com/xonsh/xonsh/issues/5301#issuecomment-1995160635
    $BOTTOM_TOOLBAR = vi_mode
# $MULTILINE_PROMPT = "`·.,¸,.·*¯`·.,¸,.·*¯"
$MULTILINE_PROMPT = "{GREEN}╰──────────────{INTENSE_GREEN}··{RESET}"
$PROMPT = "\n".join([
    "{GREEN}┬─[{INTENSE_WHITE}{short_cwd}{GREEN}]─[{branch_color}{gitstatus.branch}{BOLD_INTENSE_BLUE}{gitstatus.ahead}{BOLD_RED}{gitstatus.behind}{GREEN}]─({YELLOW}{env_name}{GREEN})",
    "{GREEN}╰─[{PURPLE}{localtime}{GREEN}]─{prompt_end} ",
])
$RIGHT_PROMPT = "{last_return_code_if_nonzero:{RED}[{BOLD_INTENSE_RED}{}{RED}]}{RESET}"
$TITLE = "{current_job:{} | }{user}"

#############################
# PROMPT_FIELDS["env_name"] #
#############################

$PROMPT_FIELDS["env_prefix"] = $PROMPT_FIELDS["env_postfix"] = ""

####################################
# PROMPT_FIELDS["gitstatus.ahead"] #
####################################

# https://xon.sh/api/_autosummary/cmd/xonsh.prompt.gitstatus.html
gitstatus_ahead = $PROMPT_FIELDS["gitstatus.ahead"]

#####################################
# PROMPT_FIELDS["gitstatus.behind"] #
#####################################

gitstatus_behind = $PROMPT_FIELDS["gitstatus.behind"]

#####################################
# PROMPT_FIELDS["gitstatus.branch"] #
#####################################

gitstatus_branch = $PROMPT_FIELDS["gitstatus.branch"]
gitstatus_branch.prefix = ""
gitstatus_branch.suffix = "{RESET}"

###############################
# PROMPT_FIELDS["prompt_end"] #
###############################

$PROMPT_FIELDS["prompt_end"] = "{INTENSE_GREEN}@>{RESET}"


##############################
# PROMPT_FIELDS["shelldate"] #
##############################

class MyTime(PromptField):
    _name = "mytime"
    _count: int = 0
    prefix = "{PURPLE}"
    suffix = "{RESET}"

    def update(self, ctx):
        self._count %= 10
        self._count += 1
        self.value = (
            time.strftime("%Y-%m-%d")
            if self._count == 1
            else  time.strftime("%H:%M")
        )


# https://xon.sh/xonshrc.html#display-different-date-information-every-10th-time
$PROMPT_FIELDS["mytime"] = MyTime()

################################
# PROMPT_FIELDS["time_format"] #
################################

$PROMPT_FIELDS["time_format"] = "%s"
