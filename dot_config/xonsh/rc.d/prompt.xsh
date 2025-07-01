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

# https://xon.sh/envvars.html#interactive-prompt
$BOTTOM_TOOLBAR = "{branch_color}{gitstatus.branch}{BOLD_BLUE}{gitstatus.ahead}{BOLD_RED}{gitstatus.behind}{RESET}{env_name: {YELLOW}{}}{RESET}"
$MULTILINE_PROMPT = "`·.,¸,.·*¯`·.,¸,.·*¯"
$PROMPT = "\n".join([
    "{PURPLE}{localtime}{RESET} {INTENSE_WHITE}{short_cwd}{RESET} {BOLD_INTENSE_GREEN}{prompt_end}{RESET} ",
])
$RIGHT_PROMPT = "{last_return_code_if_nonzero:{RED}[{BOLD_INTENSE_RED}{}{RED}] }{RESET}{current_job}"
# $PROMPT_REFRESH_INTERVAL = 1
# $UPDATE_PROMPT_ON_KEYPRESS = True


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

$PROMPT_FIELDS["prompt_end"] = "@>"


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
