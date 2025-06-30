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

# https://xon.sh/envvars.html#prompt
$PROMPT = '{YELLOW}{env_name}{RESET} {cwd}{gitstatus.branch}{gitstatus.ahead}{gitstatus.behind} {RED}{last_return_code_if_nonzero:[{BOLD_INTENSE_RED}{}{RED}] }{RESET}{BOLD_BLUE}{prompt_end}{RESET} '
$RIGHT_PROMPT = '{localtime}'
# $PROMPT_REFRESH_INTERVAL = 1
# $UPDATE_PROMPT_ON_KEYPRESS = True


####################################
# PROMPT_FIELDS["gitstatus.ahead"] #
####################################

# https://xon.sh/api/_autosummary/cmd/xonsh.prompt.gitstatus.html
gitstatus_ahead = $PROMPT_FIELDS["gitstatus.ahead"]
gitstatus_ahead.suffix = "{RESET}"

#####################################
# PROMPT_FIELDS["gitstatus.behind"] #
#####################################

gitstatus_behind = $PROMPT_FIELDS["gitstatus.behind"]
gitstatus_behind.suffix = "{RESET}"


#####################################
# PROMPT_FIELDS["gitstatus.branch"] #
#####################################

def branch_updater(fld: PromptField, ctx: PromptFields):
    branch_updater.old(fld, ctx)
    color = vc.branch_color()
    fld.prefix = f" {color}"


gitstatus_branch = $PROMPT_FIELDS["gitstatus.branch"]
gitstatus_branch.suffix = "{RESET}"
branch_updater.old = gitstatus_branch.updator
gitstatus_branch.updator = branch_updater

###############################
# PROMPT_FIELDS["prompt_end"] #
###############################

$PROMPT_FIELDS['prompt_end'] = "@>"


##############################
# PROMPT_FIELDS["shelldate"] #
##############################

def get_shelldate():
    get_shelldate.fulldate %= 10
    get_shelldate.fulldate += 1
    if get_shelldate.fulldate == 1:
        return time.strftime('%Y-%m-%d')
    return time.strftime('%H:%M')


get_shelldate.fulldate = 0

# https://xon.sh/xonshrc.html#display-different-date-information-every-10th-time
$PROMPT_FIELDS['shelldate'] = get_shelldate
