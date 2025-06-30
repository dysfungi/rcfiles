"""
References:
    https://xon.sh/tutorial.html#customizing-the-prompt
"""
import time
from xonsh.built_ins import XSH


$PROMPT = '{shelldate} {YELLOW}{env_name}{RESET}{BOLD_GREEN}{user}@{hostname}{BOLD_BLUE} {cwd}{branch_color}{curr_branch: {}}{RESET} {RED}{last_return_code_if_nonzero:[{BOLD_INTENSE_RED}{}{RED}] }{RESET}{BOLD_BLUE}{prompt_end}{RESET} '


def get_shelldate():
    get_shelldate.fulldate %= 10
    get_shelldate.fulldate += 1
    if get_shelldate.fulldate == 1:
        return time.strftime('%Y-%m-%d')
    return time.strftime('%H:%M')

get_shelldate.fulldate = 0


$PROMPT_FIELDS['prompt_end'] = "@>"
# https://xon.sh/xonshrc.html#display-different-date-information-every-10th-time
$PROMPT_FIELDS['shelldate'] = get_shelldate
